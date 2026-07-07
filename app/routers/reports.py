from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

from .. import db

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/summary")
def summary():
    conn = db.get_conn()
    try:
        orders = [db.order_to_dict(r) for r in
                  conn.execute("SELECT * FROM orders WHERE status != 'cancelled'").fetchall()]

        today = datetime.now(timezone.utc).date().isoformat()
        today_orders = [o for o in orders if o["createdAt"][:10] == today]

        revenue = sum(o["total"] for o in orders)
        today_revenue = sum(o["total"] for o in today_orders)

        # top sellers by quantity
        tally: dict[str, dict] = {}
        for o in orders:
            for l in o["items"]:
                t = tally.setdefault(l["name"], {"name": l["name"], "emoji": l["emoji"], "qty": 0, "revenue": 0})
                t["qty"] += l["qty"]
                t["revenue"] += l["price"] * l["qty"]
        top_products = sorted(tally.values(), key=lambda x: x["qty"], reverse=True)[:5]

        low_stock = [
            {"name": p["name"], "emoji": p["emoji"], "stock": p["stock"], "unit": p["unit"]}
            for p in (db.product_to_dict(r) for r in
                      conn.execute("SELECT * FROM products WHERE active = 1 AND stock <= 10").fetchall())
        ]

        # last 7 days revenue
        series = []
        for i in range(6, -1, -1):
            day = (datetime.now(timezone.utc).date() - timedelta(days=i)).isoformat()
            day_rev = sum(o["total"] for o in orders if o["createdAt"][:10] == day)
            series.append({"date": day, "revenue": day_rev})

        customers = conn.execute("SELECT COUNT(*) AS n FROM customers").fetchone()["n"]

        return {
            "totalRevenue": revenue,
            "totalOrders": len(orders),
            "todayRevenue": today_revenue,
            "todayOrders": len(today_orders),
            "avgOrderValue": (revenue / len(orders)) if orders else 0,
            "customers": customers,
            "topProducts": top_products,
            "lowStock": low_stock,
            "series": series,
            "channels": {
                "whatsapp": sum(1 for o in orders if o["channel"] == "whatsapp"),
                "manual": sum(1 for o in orders if o["channel"] == "manual"),
            },
        }
    finally:
        conn.close()
