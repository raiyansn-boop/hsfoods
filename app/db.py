"""SQLite data layer for HSFOODS.

Uses Python's stdlib ``sqlite3`` — no ORM, no external DB server. The database
file lives at ``hsfoods/data/hsfoods.db`` and is created automatically.

Includes the Lifetime Referral & Wallet engine: item-wise referral rules
(bonus / cap / margin guard), a referral ledger with provisional → approved →
reversed / review states, and wallet + liability reporting.
"""
from __future__ import annotations

import json
import os
import sqlite3
import secrets
import string
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "hsfoods.db"

# ---- referral configuration (env-overridable) ------------------------------
# Default bonus when a product has no explicit item-wise rule.
DEFAULT_BONUS_PCT = float(os.getenv("REFERRAL_DEFAULT_PCT", "5"))
# Days after delivery before a provisional reward can be approved (return window).
RETURN_WINDOW_DAYS = int(os.getenv("REFERRAL_RETURN_WINDOW_DAYS", "7"))
# A reward may not exceed this fraction of the line's gross margin, else it is
# held for manual review (margin guard).
MARGIN_GUARD_FRACTION = float(os.getenv("REFERRAL_MARGIN_GUARD", "0.5"))
# Loyalty cashback: every customer earns this % of each order into their OWN
# wallet (clears after delivery + return window, same as referral rewards).
LOYALTY_RATE = float(os.getenv("LOYALTY_RATE_PCT", "2"))

LEDGER_STATES = ("provisional", "approved", "reversed", "review")
REVIEW_REASONS = ("self_referral", "cap_breach", "return_window", "low_margin")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _add_column(conn, table: str, name: str, decl: str) -> None:
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if name not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def init_db() -> None:
    """Create tables / run lightweight migrations."""
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                id        TEXT PRIMARY KEY,
                name      TEXT NOT NULL,
                price     REAL NOT NULL,
                unit      TEXT NOT NULL DEFAULT 'kg',
                stock     REAL NOT NULL DEFAULT 0,
                emoji     TEXT NOT NULL DEFAULT '🍎',
                category  TEXT NOT NULL DEFAULT 'Daily',
                active    INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS templates (
                id         TEXT PRIMARY KEY,
                name       TEXT NOT NULL,
                category   TEXT NOT NULL DEFAULT 'General',
                body       TEXT NOT NULL,
                used       INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS categories (
                id     TEXT PRIMARY KEY,
                name   TEXT UNIQUE NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS customers (
                id         TEXT PRIMARY KEY,
                phone      TEXT UNIQUE NOT NULL,
                name       TEXT NOT NULL DEFAULT 'WhatsApp Customer',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS orders (
                id         TEXT PRIMARY KEY,
                code       TEXT NOT NULL,
                phone      TEXT NOT NULL,
                items      TEXT NOT NULL,
                total      REAL NOT NULL,
                status     TEXT NOT NULL DEFAULT 'placed',
                channel    TEXT NOT NULL DEFAULT 'whatsapp',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conversations (
                phone TEXT PRIMARY KEY,
                state TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id         TEXT PRIMARY KEY,
                phone      TEXT NOT NULL,
                direction  TEXT NOT NULL,    -- 'in' | 'out'
                source     TEXT NOT NULL,    -- 'customer' | 'bot' | 'admin'
                text       TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS broadcasts (
                id         TEXT PRIMARY KEY,
                message    TEXT NOT NULL,
                audience   TEXT NOT NULL,     -- 'all' | 'ordered' | 'wallet'
                recipients INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS redemptions (
                id          TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,     -- whose wallet was debited
                order_id    TEXT NOT NULL,     -- order the credit was spent on
                amount      REAL NOT NULL,
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS referral_ledger (
                id             TEXT PRIMARY KEY,
                referrer_id    TEXT NOT NULL,      -- customer who earns
                referred_phone TEXT NOT NULL,      -- customer who ordered
                order_id       TEXT NOT NULL,
                order_item     TEXT,               -- product id (optional)
                item_name      TEXT,               -- display label
                base_amount    REAL NOT NULL,      -- amount the bonus is computed on
                reward         REAL NOT NULL,
                status         TEXT NOT NULL DEFAULT 'provisional',
                review_reason  TEXT,
                created_at     TEXT NOT NULL,
                approved_at    TEXT
            );
            """
        )

        # drop the earlier simple rewards table if present (superseded by ledger)
        conn.execute("DROP TABLE IF EXISTS rewards")

        # customers: referral identity + lifetime link
        _add_column(conn, "customers", "referral_code", "TEXT")
        _add_column(conn, "customers", "referred_by", "TEXT")
        # customers: saved delivery address
        _add_column(conn, "customers", "address", "TEXT")

        # products: item-wise referral rule + cost (for margin guard)
        _add_column(conn, "products", "cost", "REAL")
        _add_column(conn, "products", "ref_bonus_type", "TEXT DEFAULT 'percent'")
        _add_column(conn, "products", "ref_bonus_value", f"REAL DEFAULT {DEFAULT_BONUS_PCT}")
        _add_column(conn, "products", "ref_cap", "REAL DEFAULT 0")

        # referral_ledger: distinguish referral rewards from loyalty cashback
        _add_column(conn, "referral_ledger", "kind", "TEXT DEFAULT 'referral'")

        # products: item-wise loyalty cashback rule (per-product override of the global rate)
        _add_column(conn, "products", "loyalty_bonus_type", "TEXT DEFAULT 'percent'")
        _add_column(conn, "products", "loyalty_bonus_value", f"REAL DEFAULT {LOYALTY_RATE}")

        # orders: delivery timestamp (drives return-window approval)
        _add_column(conn, "orders", "delivered_at", "TEXT")
        # orders: wallet credit applied at checkout
        _add_column(conn, "orders", "wallet_used", "REAL DEFAULT 0")
        # orders: delivery address snapshot at order time
        _add_column(conn, "orders", "address", "TEXT")
        # orders: payment tracking
        _add_column(conn, "orders", "payment_mode", "TEXT")      # cod | upi | wallet
        _add_column(conn, "orders", "payment_status", "TEXT")    # pending | paid

        # backfill referral codes for existing customers
        for row in conn.execute(
            "SELECT id FROM customers WHERE referral_code IS NULL OR referral_code = ''"
        ).fetchall():
            conn.execute(
                "UPDATE customers SET referral_code = ? WHERE id = ?",
                (unique_ref_code(conn), row["id"]),
            )

        # backfill categories from existing product values
        for row in conn.execute(
            "SELECT DISTINCT category FROM products WHERE category IS NOT NULL AND category != ''"
        ).fetchall():
            ensure_category(conn, row["category"])

        _seed_templates(conn)
        conn.commit()


_DEFAULT_TEMPLATES = [
    ("Order Confirmation", "Order placed",
     "Hi {name}! 🍃 Your HSFOODS order is confirmed.\n\nWe're packing it now 📦 — out for delivery in ~10 minutes.\n\nThank you for shopping with us! 🥭"),
    ("Out for Delivery", "Status update",
     "🛵 Hi {name}, your HSFOODS order is out for delivery and will reach you shortly!"),
    ("Order Delivered", "Status update",
     "✅ Delivered! Hi {name}, hope you enjoy your fresh fruits 🍎\n\nOrder again anytime — just message *menu*."),
    ("Payment Reminder", "Payment",
     "💳 Hi {name}, a friendly reminder to complete the UPI payment for your HSFOODS order. Thank you! 🙏"),
    ("Weekly Offer", "Marketing",
     "🎉 Hi {name}! This week at HSFOODS:\n🥭 Alphonso Mango 20% off\n🍓 Strawberries fresh in\n\nReply *menu* to order — 10-minute delivery! ⚡"),
]


def _seed_templates(conn) -> None:
    if conn.execute("SELECT COUNT(*) AS n FROM templates").fetchone()["n"]:
        return
    for name, category, body in _DEFAULT_TEMPLATES:
        conn.execute(
            "INSERT INTO templates (id, name, category, body, used, created_at) "
            "VALUES (?, ?, ?, ?, 0, ?)",
            (new_id("tpl"), name, category, body, _now()),
        )


def render_template(body: str, name: str | None = None, phone: str | None = None) -> str:
    return (body
            .replace("{name}", name or "there")
            .replace("{phone}", phone or "")
            .replace("{store}", "HSFOODS"))


def get_setting(conn, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def payment_config(conn) -> dict:
    """Payment modes available to the bot right now."""
    vpa = get_setting(conn, "upi_vpa")
    return {
        "codEnabled": get_setting(conn, "cod_enabled", "1") == "1",
        "upiEnabled": get_setting(conn, "upi_enabled", "0") == "1" and bool(vpa),
        "upiVpa": vpa,
        "upiName": get_setting(conn, "upi_name", "HSFOODS"),
    }


def whatsapp_config(conn) -> dict:
    """WhatsApp Cloud API credentials — settings table first, then env fallback."""
    return {
        "token": get_setting(conn, "wa_token") or os.getenv("WHATSAPP_TOKEN", ""),
        "phoneId": get_setting(conn, "wa_phone_id") or os.getenv("WHATSAPP_PHONE_ID", ""),
        "wabaId": get_setting(conn, "wa_waba_id") or os.getenv("WHATSAPP_WABA_ID", ""),
        "verifyToken": get_setting(conn, "wa_verify_token") or os.getenv("WHATSAPP_VERIFY_TOKEN", "hsfoods-verify"),
    }


def upi_link(vpa: str, name: str, amount: float, note: str) -> str:
    from urllib.parse import quote
    return (
        f"upi://pay?pa={quote(vpa)}&pn={quote(name)}"
        f"&am={amount:.2f}&cu=INR&tn={quote(note)}"
    )


def ensure_category(conn, name: str) -> None:
    """Register a category by name if it doesn't exist yet (active by default)."""
    name = (name or "").strip()
    if name:
        conn.execute(
            "INSERT OR IGNORE INTO categories (id, name, active) VALUES (?, ?, 1)",
            (new_id("cat"), name),
        )


def new_id(prefix: str = "id") -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


# ---- referral codes --------------------------------------------------------

def gen_ref_code() -> str:
    return "HS" + "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))


def unique_ref_code(conn) -> str:
    while True:
        code = gen_ref_code()
        if not conn.execute("SELECT 1 FROM customers WHERE referral_code = ?", (code,)).fetchone():
            return code


# ---- referral ledger -------------------------------------------------------

def _line_reward(product: sqlite3.Row | None, price: float, qty: float):
    """Compute the raw bonus for one order line given its product's rule."""
    if product is None:
        btype, bval, cap = "percent", DEFAULT_BONUS_PCT, 0.0
    else:
        btype = product["ref_bonus_type"] or "percent"
        bval = product["ref_bonus_value"] if product["ref_bonus_value"] is not None else DEFAULT_BONUS_PCT
        cap = product["ref_cap"] or 0.0
    base = price * qty
    raw = base * (bval / 100.0) if btype == "percent" else bval * qty
    return base, round(raw, 2), cap


def get_or_create_customer(conn, phone: str, name: str | None = None, referral_code: str | None = None):
    """Fetch or create a customer (used by the customer app checkout)."""
    cust = conn.execute("SELECT * FROM customers WHERE phone = ?", (phone,)).fetchone()
    if cust:
        if name and cust["name"] in (None, "", "WhatsApp Customer", "App Customer"):
            conn.execute("UPDATE customers SET name = ? WHERE phone = ?", (name, phone))
        return conn.execute("SELECT * FROM customers WHERE phone = ?", (phone,)).fetchone()

    referred_by = None
    if referral_code:
        ref = conn.execute(
            "SELECT id, phone FROM customers WHERE referral_code = ?", (referral_code.strip().upper(),)
        ).fetchone()
        if ref and ref["phone"] != phone:
            referred_by = ref["id"]
    conn.execute(
        "INSERT INTO customers (id, phone, name, created_at, referral_code, referred_by) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (new_id("cust"), phone, name or "App Customer", _now(), unique_ref_code(conn), referred_by),
    )
    conn.commit()
    return conn.execute("SELECT * FROM customers WHERE phone = ?", (phone,)).fetchone()


def compute_referral_for_order(conn, phone: str, order_id: str, items: list[dict]):
    """Create provisional/review ledger entries for an order's referrer.

    Item-wise: one entry per line. Applies cap and margin-guard rules and flags
    entries for manual review where required. Returns the created entries.
    """
    cust = conn.execute(
        "SELECT referred_by FROM customers WHERE phone = ?", (phone,)
    ).fetchone()
    if not cust or not cust["referred_by"]:
        return []

    referrer = conn.execute(
        "SELECT id, phone FROM customers WHERE id = ?", (cust["referred_by"],)
    ).fetchone()
    if not referrer:
        return []

    created = []
    for line in items:
        product = conn.execute(
            "SELECT * FROM products WHERE id = ?", (line.get("productId"),)
        ).fetchone()
        price = line.get("price", 0)
        qty = line.get("qty", 0)
        base, raw, cap = _line_reward(product, price, qty)

        reward = raw
        reason = None
        # cap guard
        if cap and raw > cap:
            reward = round(cap, 2)
            reason = "cap_breach"
        # margin guard (only if we know the product cost)
        if product is not None and product["cost"] is not None:
            margin = max(0.0, (price - product["cost"])) * qty
            if reward > margin * MARGIN_GUARD_FRACTION:
                reason = reason or "low_margin"
        # self-referral guard (should be blocked upstream, but double-check)
        if referrer["phone"] == phone:
            reason = "self_referral"

        status = "review" if reason else "provisional"
        entry_id = new_id("rl")
        conn.execute(
            "INSERT INTO referral_ledger "
            "(id, referrer_id, referred_phone, order_id, order_item, item_name, "
            " base_amount, reward, status, review_reason, created_at, kind) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'referral')",
            (entry_id, referrer["id"], phone, order_id, line.get("productId"),
             line.get("name"), base, reward, status, reason, _now()),
        )
        created.append({"id": entry_id, "reward": reward, "status": status, "reason": reason})
    return created


def compute_loyalty_for_order(conn, phone: str, order_id: str, items: list[dict]):
    """Credit the customer's OWN wallet with loyalty cashback, item-wise.

    Each product carries its own loyalty rule (percent or flat); the per-line
    amounts are summed into one aggregate cashback entry. Provisional until the
    order is delivered + return window, so cancelled orders earn nothing.
    """
    cust = conn.execute("SELECT id FROM customers WHERE phone = ?", (phone,)).fetchone()
    if not cust:
        return None

    reward, base = 0.0, 0.0
    for line in items:
        price = line.get("price", 0)
        qty = line.get("qty", 0)
        base += price * qty
        product = conn.execute(
            "SELECT loyalty_bonus_type, loyalty_bonus_value FROM products WHERE id = ?",
            (line.get("productId"),),
        ).fetchone()
        if product is not None:
            btype = product["loyalty_bonus_type"] or "percent"
            bval = product["loyalty_bonus_value"] if product["loyalty_bonus_value"] is not None else LOYALTY_RATE
        else:
            btype, bval = "percent", LOYALTY_RATE
        reward += price * qty * (bval / 100.0) if btype == "percent" else bval * qty

    reward = round(reward, 2)
    if reward <= 0:
        return None
    conn.execute(
        "INSERT INTO referral_ledger "
        "(id, referrer_id, referred_phone, order_id, order_item, item_name, "
        " base_amount, reward, status, review_reason, created_at, kind) "
        "VALUES (?, ?, ?, ?, NULL, 'Loyalty cashback', ?, ?, 'provisional', NULL, ?, 'loyalty')",
        (new_id("rl"), cust["id"], phone, order_id, round(base, 2), reward, _now()),
    )
    return reward


def mark_delivered(conn, order_id: str) -> None:
    conn.execute("UPDATE orders SET delivered_at = ? WHERE id = ?", (_now(), order_id))


def process_approvals(conn) -> dict:
    """Promote provisional entries to approved once delivery + return window passed.

    This is the wallet-credit step: only successfully delivered orders past the
    return window get credited. Returns counts/total approved.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETURN_WINDOW_DAYS)).isoformat()
    rows = conn.execute(
        """
        SELECT rl.id, rl.reward FROM referral_ledger rl
        JOIN orders o ON o.id = rl.order_id
        WHERE rl.status = 'provisional'
          AND rl.review_reason IS NULL
          AND o.status = 'delivered'
          AND o.delivered_at IS NOT NULL
          AND o.delivered_at <= ?
        """,
        (cutoff,),
    ).fetchall()
    total = 0.0
    for r in rows:
        conn.execute(
            "UPDATE referral_ledger SET status = 'approved', approved_at = ? WHERE id = ?",
            (_now(), r["id"]),
        )
        total += r["reward"]
    conn.commit()
    return {"approved": len(rows), "total": round(total, 2)}


def reverse_order_rewards(conn, order_id: str, delivered: bool) -> None:
    """Handle a cancelled/returned order.

    Provisional rewards are reversed outright. Rewards already approved (paid to
    a wallet) on a delivered order that is now returned are flagged for manual
    review (return_window) so an operator can claw them back deliberately.
    """
    conn.execute(
        "UPDATE referral_ledger SET status = 'reversed' "
        "WHERE order_id = ? AND status = 'provisional'",
        (order_id,),
    )
    conn.execute(
        "UPDATE referral_ledger SET status = 'review', review_reason = 'return_window' "
        "WHERE order_id = ? AND status = 'approved'",
        (order_id,),
    )
    conn.commit()


def set_ledger_status(conn, entry_id: str, status: str) -> bool:
    if status not in LEDGER_STATES:
        return False
    approved_at = _now() if status == "approved" else None
    cur = conn.execute(
        "UPDATE referral_ledger SET status = ?, approved_at = ?, "
        "review_reason = CASE WHEN ? = 'review' THEN review_reason ELSE NULL END "
        "WHERE id = ?",
        (status, approved_at, status, entry_id),
    )
    conn.commit()
    return cur.rowcount > 0


def wallet_summary(conn, customer_id: str) -> dict:
    """Spendable balance (approved minus redeemed) + pending totals for a customer."""
    row = conn.execute(
        """
        SELECT
          COALESCE(SUM(CASE WHEN status = 'approved'    THEN reward END), 0) AS earned,
          COALESCE(SUM(CASE WHEN status = 'provisional' THEN reward END), 0) AS pending
        FROM referral_ledger WHERE referrer_id = ?
        """,
        (customer_id,),
    ).fetchone()
    redeemed = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS r FROM redemptions WHERE customer_id = ?",
        (customer_id,),
    ).fetchone()["r"]
    return {
        "balance": round(max(0.0, row["earned"] - redeemed), 2),
        "pending": round(row["pending"], 2),
        "earned": round(row["earned"], 2),
        "redeemed": round(redeemed, 2),
    }


def log_message(conn, phone: str, source: str, text: str) -> dict:
    """Record one chat message. source: 'customer' | 'bot' | 'admin'."""
    row = {
        "id": new_id("msg"),
        "phone": phone,
        "direction": "in" if source == "customer" else "out",
        "source": source,
        "text": text,
        "created_at": _now(),
    }
    conn.execute(
        "INSERT INTO messages (id, phone, direction, source, text, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (row["id"], row["phone"], row["direction"], row["source"], row["text"], row["created_at"]),
    )
    conn.commit()
    return row


def redeem_wallet(conn, customer_id: str, order_id: str, amount: float) -> None:
    """Debit a customer's wallet against an order (caller caps at balance)."""
    conn.execute(
        "INSERT INTO redemptions (id, customer_id, order_id, amount, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (new_id("rdm"), customer_id, order_id, round(amount, 2), _now()),
    )


# ---- row helpers -----------------------------------------------------------

def product_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "price": row["price"],
        "unit": row["unit"],
        "stock": row["stock"],
        "emoji": row["emoji"],
        "category": row["category"],
        "active": bool(row["active"]),
        "cost": row["cost"],
        "ref_bonus_type": row["ref_bonus_type"] or "percent",
        "ref_bonus_value": row["ref_bonus_value"] if row["ref_bonus_value"] is not None else DEFAULT_BONUS_PCT,
        "ref_cap": row["ref_cap"] or 0,
        "loyalty_bonus_type": (row["loyalty_bonus_type"] if "loyalty_bonus_type" in row.keys() else None) or "percent",
        "loyalty_bonus_value": (row["loyalty_bonus_value"] if "loyalty_bonus_value" in row.keys() and row["loyalty_bonus_value"] is not None else LOYALTY_RATE),
    }


def order_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "code": row["code"],
        "phone": row["phone"],
        "items": json.loads(row["items"]),
        "total": row["total"],
        "status": row["status"],
        "channel": row["channel"],
        "createdAt": row["created_at"],
        "deliveredAt": row["delivered_at"],
        "walletUsed": row["wallet_used"] or 0,
        "address": row["address"],
        "paymentMode": row["payment_mode"],
        "paymentStatus": row["payment_status"],
    }


def ledger_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "referrerId": row["referrer_id"],
        "referredPhone": row["referred_phone"],
        "orderId": row["order_id"],
        "orderItem": row["order_item"],
        "itemName": row["item_name"],
        "baseAmount": row["base_amount"],
        "reward": row["reward"],
        "status": row["status"],
        "reviewReason": row["review_reason"],
        "kind": row["kind"] if "kind" in row.keys() else "referral",
        "createdAt": row["created_at"],
        "approvedAt": row["approved_at"],
    }
