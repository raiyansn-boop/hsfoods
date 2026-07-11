import json
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from .. import db
from ..models import OrderCreate, OrderUpdate
from ..slip import build_slip
from .whatsapp import _send_whatsapp

router = APIRouter(prefix="/api/orders", tags=["orders"])

STATUSES = ["placed", "packed", "out_for_delivery", "delivered", "cancelled"]


@router.get("")
def list_orders(status: str | None = None):
    conn = db.get_conn()
    try:
        if status:
            rows = conn.execute(
                "SELECT * FROM orders WHERE status = ? ORDER BY created_at DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM orders ORDER BY created_at DESC").fetchall()
        return [db.order_to_dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/{order_ref}/slip")
def order_slip(order_ref: str):
    """Barcode delivery slip as a PDF."""
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM orders WHERE id = ? OR code = ?", (order_ref, order_ref)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="not found")
        order = db.order_to_dict(row)
        cust = conn.execute(
            "SELECT name FROM customers WHERE phone = ?", (order["phone"],)
        ).fetchone()
        upi = None
        if order["paymentMode"] == "upi" and order["paymentStatus"] != "paid" and order["total"] > 0:
            cfg = db.payment_config(conn)
            if cfg["upiVpa"]:
                upi = db.upi_link(cfg["upiVpa"], cfg["upiName"], order["total"], order["code"])
        pdf = build_slip(order, cust["name"] if cust else None, upi_link=upi)
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{order["code"]}-slip.pdf"'},
        )
    finally:
        conn.close()


@router.get("/{order_ref}")
def get_order(order_ref: str):
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM orders WHERE id = ? OR code = ?", (order_ref, order_ref)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="not found")
        return db.order_to_dict(row)
    finally:
        conn.close()


@router.post("", status_code=201)
def create_order(body: OrderCreate):
    if not body.items:
        raise HTTPException(status_code=400, detail="items array required")
    conn = db.get_conn()
    try:
        lines = []
        for it in body.items:
            p = conn.execute("SELECT * FROM products WHERE id = ?", (it.productId,)).fetchone()
            if not p:
                continue
            lines.append({
                "productId": p["id"], "name": p["name"], "emoji": p["emoji"],
                "price": p["price"], "unit": p["unit"], "qty": it.qty,
            })
            conn.execute("UPDATE products SET stock = MAX(0, stock - ?) WHERE id = ?", (it.qty, p["id"]))
        if not lines:
            raise HTTPException(status_code=400, detail="no valid products")
        now = datetime.now(timezone.utc).isoformat()
        oid = db.new_id("ord")
        code = "HS" + str(int(time.time() * 1000))[-6:]
        total = sum(l["price"] * l["qty"] for l in lines)
        conn.execute(
            "INSERT INTO orders (id, code, phone, items, total, status, channel, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'placed', 'manual', ?)",
            (oid, code, body.phone, json.dumps(lines), total, now),
        )
        db.compute_referral_for_order(conn, body.phone, oid, lines)
        db.compute_loyalty_for_order(conn, body.phone, oid, lines)
        conn.commit()
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (oid,)).fetchone()
        return db.order_to_dict(row)
    finally:
        conn.close()


STATUS_NOTES = {
    "packed": "📦 Good news! Your HSFOODS order *{code}* is packed and being prepared.",
    "out_for_delivery": "🛵 Your HSFOODS order *{code}* is out for delivery — arriving soon!",
    "delivered": "✅ Your HSFOODS order *{code}* has been delivered. Enjoy your fresh picks! 🍎\nReply *menu* to order again.",
    "cancelled": "❌ Your HSFOODS order *{code}* was cancelled. Reply *menu* if you'd like to reorder.",
}


@router.patch("/{order_ref}")
async def update_order(order_ref: str, body: OrderUpdate):
    if body.status is not None and body.status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {', '.join(STATUSES)}")
    if body.payment_status is not None and body.payment_status not in ("pending", "paid"):
        raise HTTPException(status_code=400, detail="payment_status must be pending or paid")
    notify = None
    conn = db.get_conn()
    try:
        existing = conn.execute(
            "SELECT * FROM orders WHERE id = ? OR code = ?", (order_ref, order_ref)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="not found")

        if body.payment_status is not None:
            conn.execute(
                "UPDATE orders SET payment_status = ? WHERE id = ?",
                (body.payment_status, existing["id"]),
            )
            conn.commit()

        if body.status is not None and body.status != existing["status"]:
            was_delivered = existing["delivered_at"] is not None
            conn.execute(
                "UPDATE orders SET status = ? WHERE id = ?", (body.status, existing["id"])
            )
            conn.commit()

            # notify the customer when the order actually advances
            note = STATUS_NOTES.get(body.status)
            if note:
                text = note.format(code=existing["code"])
                db.log_message(conn, existing["phone"], "bot", text)
                notify = (existing["phone"], text)

            # referral side-effects of the status transition
            if body.status == "delivered":
                db.mark_delivered(conn, existing["id"])
                # cash is collected at the door — mark COD orders paid on delivery
                if existing["payment_mode"] == "cod" and existing["payment_status"] != "paid":
                    conn.execute(
                        "UPDATE orders SET payment_status = 'paid' WHERE id = ?", (existing["id"],)
                    )
                    conn.commit()
                db.process_approvals(conn)  # approves anything already past its window
            elif body.status == "cancelled":
                db.reverse_order_rewards(conn, existing["id"], delivered=was_delivered)

        row = conn.execute("SELECT * FROM orders WHERE id = ?", (existing["id"],)).fetchone()
        result = db.order_to_dict(row)
    finally:
        conn.close()

    if notify:
        phone, text = notify
        await _send_whatsapp(phone, {"text": text, "buttons": [], "menu": []})
    return result
