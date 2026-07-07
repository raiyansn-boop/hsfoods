from fastapi import APIRouter, HTTPException

from .. import db
from ..models import LedgerAction

router = APIRouter(prefix="/api/referrals", tags=["referrals"])


@router.get("")
def referrers():
    """Per-referrer summary: reach, accrued rewards by state, and wallet balance."""
    conn = db.get_conn()
    try:
        customers = conn.execute("SELECT * FROM customers").fetchall()
        ledger = [db.ledger_to_dict(r) for r in conn.execute("SELECT * FROM referral_ledger").fetchall()]

        result = []
        for c in customers:
            referred = conn.execute(
                "SELECT COUNT(*) AS n FROM customers WHERE referred_by = ?", (c["id"],)
            ).fetchone()["n"]
            # referral columns count referral rewards only (loyalty is separate)
            entries = [e for e in ledger if e["referrerId"] == c["id"] and e.get("kind", "referral") == "referral"]
            if referred == 0 and not entries:
                continue

            def total(state):
                return round(sum(e["reward"] for e in entries if e["status"] == state), 2)

            wallet = db.wallet_summary(conn, c["id"])
            result.append({
                "id": c["id"],
                "name": c["name"],
                "phone": c["phone"],
                "code": c["referral_code"],
                "referredCustomers": referred,
                "referredOrders": len({e["orderId"] for e in entries}),
                "provisional": total("provisional"),
                "approved": total("approved"),
                "reversed": total("reversed"),
                "review": total("review"),
                "redeemed": wallet["redeemed"],
                "walletBalance": wallet["balance"],
            })
        result.sort(key=lambda x: (x["approved"], x["provisional"]), reverse=True)
        return result
    finally:
        conn.close()


@router.get("/ledger")
def ledger(status: str | None = None):
    """Full referral ledger with display names; optional ?status= filter."""
    conn = db.get_conn()
    try:
        names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM customers").fetchall()}
        codes = {r["phone"]: r["name"] for r in conn.execute("SELECT phone, name FROM customers").fetchall()}
        order_codes = {r["id"]: r["code"] for r in conn.execute("SELECT id, code FROM orders").fetchall()}

        rows = conn.execute(
            "SELECT * FROM referral_ledger ORDER BY created_at DESC"
        ).fetchall()
        out = []
        for r in rows:
            e = db.ledger_to_dict(r)
            if status and e["status"] != status:
                continue
            e["referrerName"] = names.get(e["referrerId"], "—")
            e["referredName"] = codes.get(e["referredPhone"], e["referredPhone"])
            e["orderCode"] = order_codes.get(e["orderId"], e["orderId"])
            out.append(e)
        return out
    finally:
        conn.close()


@router.get("/liability")
def liability():
    """Referral liability report for accounting / MIS.

    - outstandingLiability = money likely owed but not yet realised (provisional + review)
    - paidOut             = approved rewards credited to wallets
    """
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT status, COALESCE(SUM(reward), 0) AS amt, COUNT(*) AS n "
            "FROM referral_ledger GROUP BY status"
        ).fetchall()
        by_state = {r["status"]: {"amount": round(r["amt"], 2), "count": r["n"]} for r in rows}
        for s in db.LEDGER_STATES:
            by_state.setdefault(s, {"amount": 0, "count": 0})

        provisional = by_state["provisional"]["amount"]
        review = by_state["review"]["amount"]
        approved = by_state["approved"]["amount"]
        redeemed = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS r FROM redemptions"
        ).fetchone()["r"]

        # split accrued (provisional+approved+review) liability by kind
        kind_rows = conn.execute(
            "SELECT COALESCE(kind, 'referral') AS kind, COALESCE(SUM(reward), 0) AS amt "
            "FROM referral_ledger WHERE status != 'reversed' GROUP BY COALESCE(kind, 'referral')"
        ).fetchall()
        by_kind = {r["kind"]: round(r["amt"], 2) for r in kind_rows}

        return {
            "byState": by_state,
            "byKind": by_kind,
            "referralAccrued": by_kind.get("referral", 0),
            "loyaltyAccrued": by_kind.get("loyalty", 0),
            "outstandingLiability": round(provisional + review, 2),
            "paidOut": approved,
            "redeemed": round(redeemed, 2),
            # approved credit sitting in wallets, not yet spent
            "walletFloat": round(approved - redeemed, 2),
            "returnWindowDays": db.RETURN_WINDOW_DAYS,
            "marginGuardFraction": db.MARGIN_GUARD_FRACTION,
            "loyaltyRate": db.LOYALTY_RATE,
        }
    finally:
        conn.close()


@router.post("/process")
def process():
    """Approve provisional rewards whose delivery + return window has elapsed."""
    conn = db.get_conn()
    try:
        return db.process_approvals(conn)
    finally:
        conn.close()


@router.patch("/ledger/{entry_id}")
def update_entry(entry_id: str, body: LedgerAction):
    """Manually resolve a ledger entry (approve / reverse / etc.)."""
    conn = db.get_conn()
    try:
        ok = db.set_ledger_status(conn, entry_id, body.status)
        if not ok:
            raise HTTPException(status_code=400, detail="invalid entry id or status")
        row = conn.execute("SELECT * FROM referral_ledger WHERE id = ?", (entry_id,)).fetchone()
        return db.ledger_to_dict(row)
    finally:
        conn.close()
