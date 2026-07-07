from fastapi import APIRouter

from .. import db

router = APIRouter(prefix="/api/customers", tags=["customers"])


@router.get("")
def list_customers():
    conn = db.get_conn()
    try:
        customers = conn.execute("SELECT * FROM customers").fetchall()
        names = {c["id"]: c["name"] for c in customers}
        result = []
        for c in customers:
            orders = conn.execute(
                "SELECT total, created_at FROM orders WHERE phone = ? ORDER BY created_at",
                (c["phone"],),
            ).fetchall()
            wallet = db.wallet_summary(conn, c["id"])
            result.append({
                "id": c["id"],
                "name": c["name"],
                "phone": c["phone"],
                "createdAt": c["created_at"],
                "orderCount": len(orders),
                "totalSpent": sum(o["total"] for o in orders),
                "lastOrderAt": orders[-1]["created_at"] if orders else None,
                "address": c["address"],
                "referralCode": c["referral_code"],
                "referredBy": names.get(c["referred_by"]) if c["referred_by"] else None,
                "walletBalance": wallet["balance"],
                "walletPending": wallet["pending"],
            })
        result.sort(key=lambda x: x["totalSpent"], reverse=True)
        return result
    finally:
        conn.close()
