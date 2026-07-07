"""Customer-facing storefront API for the HSFOODS customer PWA.

Mirrors the WhatsApp bot's checkout (address, wallet, payment, referral +
loyalty) as clean REST endpoints for a touch ordering app.
"""
import json
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db

router = APIRouter(prefix="/api/shop", tags=["shop"])


class CheckoutItem(BaseModel):
    productId: str
    qty: float = 1


class Checkout(BaseModel):
    phone: str
    name: str = ""
    address: str = ""
    items: list[CheckoutItem]
    paymentMode: str = "cod"          # cod | upi
    useWallet: bool = False
    referralCode: str | None = None


@router.get("/menu")
def menu():
    """Active, sellable products grouped by active category (storefront view)."""
    conn = db.get_conn()
    try:
        cat_active = {c["name"]: c["active"] for c in conn.execute("SELECT name, active FROM categories").fetchall()}
        rows = conn.execute("SELECT * FROM products WHERE active = 1 ORDER BY category, name").fetchall()
        products = []
        for r in rows:
            p = db.product_to_dict(r)
            if cat_active.get(p["category"], 1):   # skip products in deactivated categories
                products.append(p)
        cats = []
        for p in products:
            if p["category"] not in cats:
                cats.append(p["category"])
        return {"categories": cats, "products": products}
    finally:
        conn.close()


@router.get("/context")
def context(phone: str):
    """Known-customer info for the app: name, saved address, wallet, referral code."""
    conn = db.get_conn()
    try:
        cust = conn.execute("SELECT * FROM customers WHERE phone = ?", (phone,)).fetchone()
        if not cust:
            return {"known": False}
        w = db.wallet_summary(conn, cust["id"])
        return {
            "known": True,
            "name": cust["name"], "address": cust["address"],
            "referralCode": cust["referral_code"],
            "wallet": w["balance"], "walletPending": w["pending"],
        }
    finally:
        conn.close()


@router.get("/orders")
def my_orders(phone: str):
    """This customer's orders, newest first (for the Orders/tracking tab)."""
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM orders WHERE phone = ? ORDER BY created_at DESC LIMIT 30", (phone,)
        ).fetchall()
        return [db.order_to_dict(r) for r in rows]
    finally:
        conn.close()


@router.post("/checkout", status_code=201)
def checkout(body: Checkout):
    if not body.phone.strip():
        raise HTTPException(status_code=400, detail="phone required")
    if not body.items:
        raise HTTPException(status_code=400, detail="cart is empty")
    if body.paymentMode not in ("cod", "upi"):
        raise HTTPException(status_code=400, detail="paymentMode must be cod or upi")

    conn = db.get_conn()
    try:
        cust = db.get_or_create_customer(conn, body.phone, body.name.strip() or None, body.referralCode)
        if body.address.strip():
            conn.execute("UPDATE customers SET address = ? WHERE phone = ?", (body.address.strip(), body.phone))

        lines = []
        for it in body.items:
            p = conn.execute("SELECT * FROM products WHERE id = ? AND active = 1", (it.productId,)).fetchone()
            if not p or it.qty <= 0:
                continue
            lines.append({
                "productId": p["id"], "name": p["name"], "emoji": p["emoji"],
                "price": p["price"], "unit": p["unit"], "qty": it.qty,
            })
        if not lines:
            raise HTTPException(status_code=400, detail="no valid items")

        gross = round(sum(l["price"] * l["qty"] for l in lines), 2)
        wallet_used = 0.0
        if body.useWallet:
            wallet_used = round(min(db.wallet_summary(conn, cust["id"])["balance"], gross), 2)
        total = round(gross - wallet_used, 2)

        if total <= 0:
            pay_mode, pay_status = "wallet", "paid"
        else:
            pay_mode, pay_status = body.paymentMode, "pending"

        now = datetime.now(timezone.utc).isoformat()
        oid = db.new_id("ord")
        code = "HS" + str(int(time.time() * 1000))[-6:]
        address = body.address.strip() or cust["address"]
        conn.execute(
            "INSERT INTO orders (id, code, phone, items, total, status, channel, created_at, "
            "wallet_used, address, payment_mode, payment_status) "
            "VALUES (?, ?, ?, ?, ?, 'placed', 'app', ?, ?, ?, ?, ?)",
            (oid, code, body.phone, json.dumps(lines), total, now, wallet_used, address, pay_mode, pay_status),
        )
        if wallet_used > 0:
            db.redeem_wallet(conn, cust["id"], oid, wallet_used)
        db.compute_referral_for_order(conn, body.phone, oid, lines)
        loyalty = db.compute_loyalty_for_order(conn, body.phone, oid, lines)
        conn.commit()

        upi_link = None
        if pay_mode == "upi" and total > 0:
            cfg = db.payment_config(conn)
            if cfg["upiVpa"]:
                upi_link = db.upi_link(cfg["upiVpa"], cfg["upiName"], total, code)

        return {
            "code": code, "gross": gross, "walletUsed": wallet_used, "total": total,
            "paymentMode": pay_mode, "paymentStatus": pay_status,
            "loyalty": loyalty, "upiLink": upi_link, "address": address,
        }
    finally:
        conn.close()
