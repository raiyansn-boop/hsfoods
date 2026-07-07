"""HSFOODS WhatsApp bot engine.

Stateful, per-phone-number conversation that turns plain-text messages into real
orders. Used by both the Meta webhook and the in-browser simulator.
"""
from __future__ import annotations

import json
import re
import string
import time
from datetime import datetime, timezone

from . import db


def _money(n: float) -> str:
    return f"₹{n:.2f}"


# ---- product matching ------------------------------------------------------

def _active_products(conn) -> list[dict]:
    # a product is sellable only if it AND its category are active
    rows = conn.execute(
        """
        SELECT p.* FROM products p
        LEFT JOIN categories c ON c.name = p.category
        WHERE p.active = 1 AND COALESCE(c.active, 1) = 1
        """
    ).fetchall()
    return [db.product_to_dict(r) for r in rows]


def _lettered_products(conn) -> list[tuple[str, dict]]:
    """In-stock products paired with their menu letter (A, B, C, …).

    Grouped by category (stable within-category order) so the menu can show
    section headers — letters run continuously across categories.
    """
    in_stock = [p for p in _active_products(conn) if p["stock"] > 0]
    in_stock.sort(key=lambda p: (p["category"] or "Other").lower())
    return list(zip(string.ascii_uppercase, in_stock))


def _find_product(conn, query: str) -> dict | None:
    products = _active_products(conn)
    q = query.strip().lower()
    if not q:
        return None

    for p in products:  # exact
        if p["name"].lower() == q:
            return p
    for p in products:  # starts-with
        if p["name"].lower().startswith(q):
            return p

    tokens = q.split()
    for p in products:  # all tokens present
        name = p["name"].lower()
        if all(t in name for t in tokens):
            return p
    for p in products:  # any token present
        name = p["name"].lower()
        if any(t in name for t in tokens):
            return p
    return None


def _parse_items(conn, text: str):
    letter_map = {letter: p for letter, p in _lettered_products(conn)}
    cleaned = re.sub(r"^\s*order\b", "", text, flags=re.IGNORECASE)
    chunks = re.split(r"[,\n]+|\s+and\s+", cleaned, flags=re.IGNORECASE)
    items, unmatched = [], []
    for chunk in (c.strip() for c in chunks):
        if not chunk:
            continue

        # order by menu letter: "2 A", "2A", "2x A"
        m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*x?\s*([a-zA-Z])", chunk)
        if m and m.group(2).upper() in letter_map:
            items.append({"product": letter_map[m.group(2).upper()], "qty": float(m.group(1))})
            continue
        # bare menu letter means quantity 1: "A"
        if re.fullmatch(r"[a-zA-Z]", chunk) and chunk.upper() in letter_map:
            items.append({"product": letter_map[chunk.upper()], "qty": 1})
            continue

        # order by name: "2 mango"
        m = re.match(r"(\d+(?:\.\d+)?)\s*x?\s*(.+)", chunk, flags=re.IGNORECASE)
        if not m:
            continue
        qty = float(m.group(1))
        product = _find_product(conn, m.group(2))
        if product:
            items.append({"product": product, "qty": qty})
        else:
            unmatched.append(m.group(2).strip())
    return items, unmatched


# ---- session state ---------------------------------------------------------

def _get_session(conn, phone: str) -> dict:
    row = conn.execute("SELECT state FROM conversations WHERE phone = ?", (phone,)).fetchone()
    if row:
        return json.loads(row["state"])
    return {"stage": "new", "cart": [], "name": None}


def _save_session(conn, phone: str, session: dict) -> None:
    conn.execute(
        "INSERT INTO conversations (phone, state) VALUES (?, ?) "
        "ON CONFLICT(phone) DO UPDATE SET state = excluded.state",
        (phone, json.dumps(session)),
    )
    conn.commit()


def _cart_total(cart: list[dict]) -> float:
    return sum(line["price"] * line["qty"] for line in cart)


def _render_menu(conn) -> str:
    lines = [
        f"{letter}. {p['emoji']} {p['name']} — {_money(p['price'])}/{p['unit']}"
        for letter, p in _lettered_products(conn)
    ]
    return "\n".join(["🍃 *HSFOODS — Fresh Fruits Menu*", "", *lines])


def _render_cart(cart: list[dict]) -> str:
    if not cart:
        return "Your basket is empty."
    lines = [f"• {l['emoji']} {l['name']} ×{_fmt_qty(l['qty'])} = {_money(l['price'] * l['qty'])}" for l in cart]
    return "\n".join([*lines, "", f"*Total: {_money(_cart_total(cart))}*"])


def _fmt_qty(q: float):
    return int(q) if float(q).is_integer() else q


def _receipt(order: dict) -> str:
    lines = [f"✅ *Order placed!*", f"Order *{order['code']}*"]
    if order.get("wallet_used", 0) > 0:
        lines += [
            f"Items: {_money(order['gross'])}",
            f"👛 Wallet applied: -{_money(order['wallet_used'])}",
            f"*To pay: {_money(order['total'])}*",
        ]
    else:
        lines.append(f"*Total: {_money(order['total'])}*")
    if order.get("address"):
        lines += ["", f"📍 Delivering to: {order['address']}"]
    mode = order.get("payment_mode")
    if mode == "upi" and order.get("upi_link"):
        lines += ["", "📲 *Pay now via UPI:*", order["upi_link"],
                  "_(tap the link, or scan the QR on your delivery slip)_"]
    elif mode == "cod":
        lines += ["", f"💵 Payment: *cash on delivery* — {_money(order['total'])}"]
    elif mode == "wallet":
        lines += ["", "👛 Paid in full with wallet credit — nothing to pay!"]
    if order.get("loyalty"):
        lines += ["", f"🎁 You'll earn *{_money(order['loyalty'])}* loyalty cashback "
                  "in your wallet after delivery!"]
    lines += ["", "🚚 Out for delivery in ~10 minutes.", "Thanks for shopping with HSFOODS! 🍃"]
    return "\n".join(lines)


def _add_to_cart(session: dict, items: list[dict]) -> None:
    for entry in items:
        product, qty = entry["product"], entry["qty"]
        existing = next((l for l in session["cart"] if l["productId"] == product["id"]), None)
        if existing:
            existing["qty"] += qty
        else:
            session["cart"].append({
                "productId": product["id"],
                "name": product["name"],
                "emoji": product["emoji"],
                "price": product["price"],
                "unit": product["unit"],
                "qty": qty,
            })


# ---- order placement -------------------------------------------------------

def _ensure_customer(conn, phone: str, session: dict):
    """Return the customer row for ``phone``, creating it (with a referral code
    and any session referrer) if it doesn't exist yet."""
    cust = conn.execute("SELECT * FROM customers WHERE phone = ?", (phone,)).fetchone()
    if cust:
        return cust

    referred_by = None
    code = session.get("referrer_code")
    if code:
        ref = conn.execute(
            "SELECT id, phone FROM customers WHERE referral_code = ?", (code,)
        ).fetchone()
        if ref and ref["phone"] != phone:
            referred_by = ref["id"]

    conn.execute(
        "INSERT INTO customers (id, phone, name, created_at, referral_code, referred_by) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (db.new_id("cust"), phone, session.get("name") or "WhatsApp Customer",
         datetime.now(timezone.utc).isoformat(), db.unique_ref_code(conn), referred_by),
    )
    conn.commit()
    return conn.execute("SELECT * FROM customers WHERE phone = ?", (phone,)).fetchone()


def _place_order(conn, phone: str, session: dict, use_wallet: bool = False,
                 address: str | None = None, payment_mode: str = "cod") -> dict:
    now = datetime.now(timezone.utc).isoformat()

    cust = _ensure_customer(conn, phone, session)
    if session.get("name") and cust["name"] != session["name"]:
        conn.execute("UPDATE customers SET name = ? WHERE phone = ?", (session["name"], phone))
    if address:
        conn.execute("UPDATE customers SET address = ? WHERE phone = ?", (address, phone))

    items = [dict(l) for l in session["cart"]]
    gross = _cart_total(items)

    wallet_used = 0.0
    if use_wallet:
        balance = db.wallet_summary(conn, cust["id"])["balance"]
        wallet_used = round(min(balance, gross), 2)
    total = round(gross - wallet_used, 2)

    if total <= 0:
        payment_mode, payment_status = "wallet", "paid"
    else:
        payment_status = "pending"

    order = {
        "id": db.new_id("ord"),
        "code": "HS" + str(int(time.time() * 1000))[-6:],
        "phone": phone,
        "items": items,
        "gross": gross,
        "wallet_used": wallet_used,
        "total": total,
        "status": "placed",
        "channel": "whatsapp",
        "created_at": now,
        "address": address or cust["address"],
        "payment_mode": payment_mode,
        "payment_status": payment_status,
    }
    if payment_mode == "upi" and total > 0:
        cfg = db.payment_config(conn)
        if cfg["upiVpa"]:
            order["upi_link"] = db.upi_link(cfg["upiVpa"], cfg["upiName"], total, order["code"])
    conn.execute(
        "INSERT INTO orders (id, code, phone, items, total, status, channel, created_at, "
        "wallet_used, address, payment_mode, payment_status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (order["id"], order["code"], order["phone"], json.dumps(items), total,
         order["status"], order["channel"], now, wallet_used, order["address"],
         payment_mode, payment_status),
    )
    if wallet_used > 0:
        db.redeem_wallet(conn, cust["id"], order["id"], wallet_used)
    for line in items:
        conn.execute(
            "UPDATE products SET stock = MAX(0, stock - ?) WHERE id = ?",
            (line["qty"], line["productId"]),
        )
    # accrue referral rewards (if any) — item-wise, runs on every order
    db.compute_referral_for_order(conn, phone, order["id"], items)
    # loyalty cashback into the customer's own wallet — item-wise per product
    order["loyalty"] = db.compute_loyalty_for_order(conn, phone, order["id"], items)
    conn.commit()
    return order


# ---- main entry point ------------------------------------------------------

def handle_message(phone: str, message: str) -> dict:
    """Handle one inbound message.

    Returns ``{"text": str, "buttons": [str], "menu": [{"id","title","description"}]}``
    — buttons are quick replies, menu is a tappable product list (WhatsApp
    interactive list message / simulator rows).
    """
    conn = db.get_conn()
    try:
        session = _get_session(conn, phone)
        text = (message or "").strip()
        lower = text.lower()

        if text:
            db.log_message(conn, phone, "customer", text)

        def reply(msg: str, stage: str | None = None, *,
                  buttons: list[str] | None = None,
                  menu: list[dict] | None = None) -> dict:
            if stage:
                session["stage"] = stage
            _save_session(conn, phone, session)
            db.log_message(conn, phone, "bot", msg)
            return {"text": msg, "buttons": buttons or [], "menu": menu or []}

        def _item_rows(category: str | None = None) -> list[dict]:
            in_basket = {l["productId"]: l["qty"] for l in session["cart"]}
            rows = []
            for letter, p in _lettered_products(conn):
                if category is not None and (p["category"] or "Other") != category:
                    continue
                desc = f"{_money(p['price'])}/{p['unit']}"
                if p["id"] in in_basket:
                    desc += f"  ·  🧺 ×{_fmt_qty(in_basket[p['id']])}"
                rows.append({
                    "id": letter,
                    "title": f"{p['emoji']} {p['name']}",
                    "description": desc,
                    "section": p["category"] or "Other",
                })
            return rows

        def _basket_line() -> str:
            if not session["cart"]:
                return ""
            n = sum(l["qty"] for l in session["cart"])
            return f"\n\n🧺 *Basket:* {_fmt_qty(n)} item{'s' if n != 1 else ''} · {_money(_cart_total(session['cart']))}"

        def _categories() -> list[str]:
            seen: list[str] = []
            for _, p in _lettered_products(conn):
                cat = p["category"] or "Other"
                if cat not in seen:
                    seen.append(cat)
            return seen

        if re.match(r"^(hi|hello|hey|start|menu|hsfoods)\b", lower):
            cats = _categories()
            session["last_category"] = cats[0] if len(cats) == 1 else None
            if len(cats) <= 1:
                # single category — go straight to items
                return reply(
                    "🍃 *HSFOODS — Today's Menu*\n\n"
                    "Tap an item to add it, or type quantities — "
                    'by letter *"2 A, 1 B"* or by name *"2 mango, 1 apple"*.' + _basket_line(),
                    "browsing",
                    menu=_item_rows(),
                    buttons=["cart", "help"],
                )
            counts = {c: len(_item_rows(c)) for c in cats}
            rows = [
                {"id": c, "title": f"🛍️ {c}", "description": f"{counts[c]} item{'s' if counts[c] != 1 else ''}"}
                for c in cats
            ]
            return reply(
                "🍃 *HSFOODS — Today's Menu*\n\nTap a category to browse:" + _basket_line(),
                "browsing",
                menu=rows,
                buttons=["cart", "help"],
            )

        # a category name (typed or tapped) opens that category's items
        cat_match = next((c for c in _categories() if c.lower() == lower), None)
        if cat_match:
            session["last_category"] = cat_match
            return reply(
                f"🛍️ *{cat_match}*\n\nTap items to add them, or type quantities like *\"2 A\"*." + _basket_line(),
                "browsing",
                menu=_item_rows(cat_match),
                buttons=["menu", "cart"],
            )

        if lower == "help":
            return reply(
                "*HSFOODS Bot — commands*\n\n• *menu* — see fruits\n"
                "• *2 A, 1 B* — add items by letter\n"
                "• *2 mango, 1 apple* — add items by name\n• *cart* — view basket\n"
                "• *confirm* — place order\n• *clear* — empty basket\n"
                "• *mycode* — get your referral code & earnings\n"
                "• *ref <CODE>* — use a friend's referral code\n"
                "• *wallet* (at checkout) — pay with wallet credit",
                buttons=["menu", "cart", "mycode"],
            )

        if lower in ("cart", "basket"):
            body = _render_cart(session["cart"])
            if session["cart"]:
                return reply(body, buttons=["confirm", "menu", "clear"])
            return reply(body, buttons=["menu"])

        if lower == "clear":
            session["cart"] = []
            return reply("🗑️ Basket cleared.", "browsing", buttons=["menu"])

        # apply someone else's referral code: "ref HSAB12"
        m = re.match(r"^(?:ref|refer|referral|use|invite)\s+([a-z0-9]{4,10})$", lower)
        if m:
            code = m.group(1).upper()
            ref = conn.execute(
                "SELECT id, phone, name FROM customers WHERE referral_code = ?", (code,)
            ).fetchone()
            if not ref:
                return reply(f"❌ Referral code *{code}* not found. Double-check and try again.")
            if ref["phone"] == phone:
                return reply("😅 You can't use your own referral code.")
            existing = conn.execute(
                "SELECT referred_by FROM customers WHERE phone = ?", (phone,)
            ).fetchone()
            if existing and existing["referred_by"]:
                return reply("✅ You already have a referrer linked. Type *menu* to order.")
            session["referrer_code"] = code
            if existing:  # customer already exists but had no referrer — link now
                conn.execute("UPDATE customers SET referred_by = ? WHERE phone = ?", (ref["id"], phone))
                conn.commit()
            return reply(
                f"🎉 Referral applied — *{ref['name']}* referred you!",
                buttons=["menu"],
            )

        def ask_address(use_wallet: bool) -> dict:
            session["use_wallet"] = use_wallet
            cust = _ensure_customer(conn, phone, session)
            if cust["address"]:
                return reply(
                    f"📍 Deliver to your saved address?\n_{cust['address']}_\n\n"
                    "Reply *yes* to confirm, or type a new address.",
                    "address_confirm",
                    buttons=["yes"],
                )
            return reply(
                "📍 Almost done! Please type your *delivery address* (house, street, area).",
                "address_new",
            )

        def place_with(payment_mode: str, address: str | None) -> dict:
            order = _place_order(
                conn, phone, session,
                use_wallet=session.pop("use_wallet", False),
                address=address,
                payment_mode=payment_mode,
            )
            session.pop("pending_address", None)
            session["cart"] = []
            session["stage"] = "browsing"
            return reply(_receipt(order), buttons=["menu", "mycode"])

        def finish_order(address: str | None) -> dict:
            """Address resolved — pick a payment mode (or place directly)."""
            cfg = db.payment_config(conn)
            gross = _cart_total(session["cart"])
            net = gross
            if session.get("use_wallet"):
                cust = _ensure_customer(conn, phone, session)
                net = round(gross - min(db.wallet_summary(conn, cust["id"])["balance"], gross), 2)
            modes = [m for m, on in (("cod", cfg["codEnabled"]), ("upi", cfg["upiEnabled"])) if on]
            if net <= 0 or not modes:
                return place_with("wallet" if net <= 0 else "cod", address)
            if len(modes) == 1:
                return place_with(modes[0], address)
            session["pending_address"] = address
            return reply(
                f"💳 How would you like to pay *{_money(net)}*?\n\n"
                "• *cod* — cash on delivery\n• *upi* — pay by UPI",
                "payment_mode",
                buttons=["cod", "upi"],
            )

        # payment-mode choice mid-checkout
        if session.get("stage") == "payment_mode":
            if lower in ("cod", "cash", "cash on delivery"):
                return place_with("cod", session.get("pending_address"))
            if lower == "upi":
                return place_with("upi", session.get("pending_address"))
            if lower not in ("help", "cart", "basket", "clear") \
                    and not re.match(r"^(hi|hello|hey|start|menu|hsfoods)\b", lower):
                return reply("💳 Please choose: *cod* or *upi*.", buttons=["cod", "upi"])

        # capture the delivery address mid-checkout (escapes: menu/help/cart/clear)
        if session.get("stage") in ("address_confirm", "address_new") \
                and lower not in ("help", "cart", "basket", "clear") \
                and not re.match(r"^(hi|hello|hey|start|menu|hsfoods)\b", lower):
            if session["stage"] == "address_confirm" and lower in ("yes", "y", "ok", "confirm"):
                return finish_order(None)  # keep the saved address
            if lower == "confirm":
                return reply("📍 Please type your delivery address first.")
            if len(text) >= 5:
                return finish_order(text)
            return reply("📍 That address looks too short — please include house, street and area.")

        # "wallet" during checkout = pay with wallet credit
        if lower == "wallet" and session.get("stage") == "wallet_offer":
            return ask_address(use_wallet=True)

        # show your own referral code + wallet preview
        if lower in ("mycode", "my code", "code", "refer", "referral", "invite", "wallet"):
            cust = _ensure_customer(conn, phone, session)
            wallet = db.wallet_summary(conn, cust["id"])
            pct = int(db.DEFAULT_BONUS_PCT)
            code = cust["referral_code"]
            return reply(
                f"🎁 *Your HSFOODS referral code: {code}*\n\n"
                f"Share it with friends! When they order, you earn up to *{pct}%* on *every* order "
                "they ever place — for life. 🍃\n\n"
                f"👛 *Wallet:* {_money(wallet['balance'])} available"
                f" · {_money(wallet['pending'])} pending\n"
                "_(pending clears after delivery + return window)_\n\n"
                f"They join by sending: *ref {code}*",
                buttons=["menu", "cart"],
            )

        if lower in ("confirm", "yes", "place order"):
            if not session["cart"]:
                return reply("Your basket is empty.", "browsing", buttons=["menu"])
            if session.get("stage") not in ("confirming", "wallet_offer"):
                return reply(
                    f"Please confirm your order:\n\n{_render_cart(session['cart'])}",
                    "confirming",
                    buttons=["confirm", "clear"],
                )
            # offer wallet credit once, if the customer has any
            if session.get("stage") == "confirming":
                cust = _ensure_customer(conn, phone, session)
                balance = db.wallet_summary(conn, cust["id"])["balance"]
                if balance > 0:
                    usable = min(balance, _cart_total(session["cart"]))
                    return reply(
                        f"👛 You have *{_money(balance)}* in your wallet — you can use "
                        f"*{_money(usable)}* on this order.",
                        "wallet_offer",
                        buttons=["wallet", "confirm"],
                    )
            # "confirm" at wallet_offer (or no balance) → collect the address
            return ask_address(use_wallet=False)

        items, unmatched = _parse_items(conn, text)
        if items:
            _add_to_cart(session, items)
            added = "\n".join(f"• {i['product']['emoji']} {i['product']['name']} ×{_fmt_qty(i['qty'])}" for i in items)
            msg = "🧺 Added:\n" + added
            if unmatched:
                msg += f"\n\n⚠️ Couldn't find: {', '.join(unmatched)}"
            msg += f"\n\n{_render_cart(session['cart'])}\n\n_Keep tapping to add more, or confirm._"
            # re-offer the items being browsed so multi-item taps flow without re-opening the menu
            last_cat = session.get("last_category")
            rows = _item_rows(last_cat) if last_cat else []
            return reply(msg, "browsing", menu=rows, buttons=["confirm", "menu", "clear"])

        if unmatched:
            return reply(
                f"😕 I couldn't find: {', '.join(unmatched)}.",
                buttons=["menu", "help"],
            )

        return reply("I didn't quite get that 🤔", buttons=["menu", "help"])
    finally:
        conn.close()
