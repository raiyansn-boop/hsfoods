"""Barcode packing-slip PDF for orders (A5, reportlab).

Note: the PDF base-14 fonts have no ₹ or emoji glyphs, so money is shown
as "Rs." and product emoji are omitted here.
"""
from __future__ import annotations

import io
from datetime import datetime

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import code128
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

W, H = A5  # 148 x 210 mm portrait

GREEN = (0.10, 0.64, 0.38)
INK = (0.11, 0.17, 0.13)
MUTED = (0.42, 0.49, 0.45)


def _rs(n: float) -> str:
    return f"Rs. {n:,.2f}"


def build_slip(order: dict, customer_name: str | None = None,
               upi_link: str | None = None) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A5)

    x0, x1 = 14 * mm, W - 14 * mm
    y = H - 16 * mm

    # header
    c.setFillColorRGB(*GREEN)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(x0, y, "HSFOODS")
    c.setFillColorRGB(*MUTED)
    c.setFont("Helvetica", 9)
    c.drawString(x0, y - 5 * mm, "Fresh groceries, delivered in minutes")
    c.setFont("Helvetica-Bold", 11)
    c.setFillColorRGB(*INK)
    c.drawRightString(x1, y, "DELIVERY SLIP")
    created = order.get("createdAt", "")
    try:
        stamp = datetime.fromisoformat(created).strftime("%d %b %Y, %I:%M %p")
    except ValueError:
        stamp = created[:16]
    c.setFont("Helvetica", 8)
    c.setFillColorRGB(*MUTED)
    c.drawRightString(x1, y - 5 * mm, stamp)

    y -= 12 * mm
    c.setStrokeColorRGB(*GREEN)
    c.setLineWidth(1.2)
    c.line(x0, y, x1, y)

    # barcode of the order code
    y -= 16 * mm
    barcode = code128.Code128(order["code"], barHeight=11 * mm, barWidth=0.42 * mm, humanReadable=False)
    barcode.drawOn(c, x0 - 2 * mm, y)
    c.setFont("Helvetica-Bold", 13)
    c.setFillColorRGB(*INK)
    c.drawString(x0 + barcode.width + 4 * mm, y + 4 * mm, order["code"])
    c.setFont("Helvetica", 8)
    c.setFillColorRGB(*MUTED)
    c.drawString(x0 + barcode.width + 4 * mm, y, f"{order.get('channel', '')} order")

    # customer block
    y -= 10 * mm
    c.setFont("Helvetica-Bold", 9)
    c.setFillColorRGB(*MUTED)
    c.drawString(x0, y, "DELIVER TO")
    y -= 5 * mm
    c.setFont("Helvetica-Bold", 10)
    c.setFillColorRGB(*INK)
    c.drawString(x0, y, f"{customer_name or 'Customer'}  ·  {order.get('phone', '')}")
    address = order.get("address") or "(no address on file)"
    c.setFont("Helvetica", 9)
    for line in _wrap(address, 70):
        y -= 4.5 * mm
        c.drawString(x0, y, line)

    # items table
    y -= 9 * mm
    c.setFont("Helvetica-Bold", 8)
    c.setFillColorRGB(*MUTED)
    c.drawString(x0, y, "ITEM")
    c.drawRightString(x1 - 42 * mm, y, "QTY")
    c.drawRightString(x1 - 22 * mm, y, "PRICE")
    c.drawRightString(x1, y, "AMOUNT")
    y -= 2 * mm
    c.setLineWidth(0.5)
    c.setStrokeColorRGB(*MUTED)
    c.line(x0, y, x1, y)

    c.setFillColorRGB(*INK)
    for line_item in order.get("items", []):
        y -= 6 * mm
        qty = line_item.get("qty", 0)
        qty_str = str(int(qty)) if float(qty).is_integer() else str(qty)
        c.setFont("Helvetica", 9)
        c.drawString(x0, y, f"{line_item.get('name', '')} ({line_item.get('unit', '')})")
        c.drawRightString(x1 - 42 * mm, y, qty_str)
        c.drawRightString(x1 - 22 * mm, y, _rs(line_item.get("price", 0)))
        c.drawRightString(x1, y, _rs(line_item.get("price", 0) * qty))

    y -= 3 * mm
    c.line(x0, y, x1, y)

    # totals
    gross = sum(i.get("price", 0) * i.get("qty", 0) for i in order.get("items", []))
    wallet = order.get("walletUsed", 0) or 0
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    if wallet:
        c.drawRightString(x1 - 22 * mm, y, "Items total")
        c.drawRightString(x1, y, _rs(gross))
        y -= 5 * mm
        c.drawRightString(x1 - 22 * mm, y, "Wallet credit")
        c.drawRightString(x1, y, f"- {_rs(wallet)}")
        y -= 6 * mm
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(x1 - 22 * mm, y, "TO COLLECT")
    c.drawRightString(x1, y, _rs(order.get("total", 0)))

    # payment block
    y -= 9 * mm
    mode = (order.get("paymentMode") or "cod").upper()
    status = (order.get("paymentStatus") or "pending").upper()
    c.setFont("Helvetica-Bold", 9)
    c.setFillColorRGB(*(GREEN if status == "PAID" else INK))
    c.drawString(x0, y, f"PAYMENT: {mode}  ·  {status}")

    if upi_link:
        # scannable UPI QR — customer scans and pays on the spot
        size = 34 * mm
        qr = QrCodeWidget(upi_link)
        b = qr.getBounds()
        d = Drawing(size, size, transform=[size / (b[2] - b[0]), 0, 0, size / (b[3] - b[1]), 0, 0])
        d.add(qr)
        qy = max(y - size - 4 * mm, 20 * mm)
        renderPDF.draw(d, c, x0 - 2 * mm, qy)
        c.setFont("Helvetica-Bold", 9)
        c.setFillColorRGB(*INK)
        c.drawString(x0 + size + 2 * mm, qy + size / 2 + 3 * mm, "SCAN TO PAY VIA UPI")
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(*MUTED)
        c.drawString(x0 + size + 2 * mm, qy + size / 2 - 2 * mm,
                     f"Amount: {_rs(order.get('total', 0))}  ·  Ref: {order.get('code', '')}")

    # footer
    c.setFont("Helvetica", 8)
    c.setFillColorRGB(*MUTED)
    c.drawCentredString(W / 2, 12 * mm, "Thank you for shopping with HSFOODS  ·  scan the barcode to look up this order")

    c.showPage()
    c.save()
    return buf.getvalue()


def _wrap(text: str, width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines or [""]
