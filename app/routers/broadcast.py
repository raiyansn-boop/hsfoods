"""Broadcast — send one message to a whole customer segment at once."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db
from .whatsapp import _send_whatsapp

router = APIRouter(prefix="/api/broadcast", tags=["broadcast"])

AUDIENCES = ("all", "ordered", "wallet")


class BroadcastIn(BaseModel):
    message: str
    audience: str = "all"


def _resolve_audience(conn, audience: str) -> list[str]:
    """Return the distinct phone numbers for a segment."""
    if audience == "ordered":
        rows = conn.execute("SELECT DISTINCT phone FROM orders").fetchall()
        return [r["phone"] for r in rows]
    if audience == "wallet":
        phones = []
        for c in conn.execute("SELECT id, phone FROM customers").fetchall():
            if db.wallet_summary(conn, c["id"])["balance"] > 0:
                phones.append(c["phone"])
        return phones
    # 'all': everyone we've ever talked to or registered
    rows = conn.execute(
        "SELECT phone FROM customers UNION SELECT DISTINCT phone FROM messages"
    ).fetchall()
    return [r["phone"] for r in rows]


@router.get("/audience/{audience}")
def audience_size(audience: str):
    """Preview how many customers a segment reaches."""
    if audience not in AUDIENCES:
        raise HTTPException(status_code=400, detail=f"audience must be one of {', '.join(AUDIENCES)}")
    conn = db.get_conn()
    try:
        return {"audience": audience, "recipients": len(_resolve_audience(conn, audience))}
    finally:
        conn.close()


@router.get("")
def recent_broadcasts():
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM broadcasts ORDER BY created_at DESC LIMIT 10"
        ).fetchall()
        return [
            {"id": r["id"], "message": r["message"], "audience": r["audience"],
             "recipients": r["recipients"], "createdAt": r["created_at"]}
            for r in rows
        ]
    finally:
        conn.close()


@router.post("")
async def send_broadcast(body: BroadcastIn):
    text = body.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="message required")
    if body.audience not in AUDIENCES:
        raise HTTPException(status_code=400, detail=f"audience must be one of {', '.join(AUDIENCES)}")

    conn = db.get_conn()
    try:
        phones = _resolve_audience(conn, body.audience)
        for phone in phones:
            db.log_message(conn, phone, "admin", text)
        conn.execute(
            "INSERT INTO broadcasts (id, message, audience, recipients, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (db.new_id("bc"), text, body.audience, len(phones), db._now()),
        )
        conn.commit()
    finally:
        conn.close()

    # deliver via WhatsApp (dry-run prints when no credentials are configured)
    for phone in phones:
        await _send_whatsapp(phone, {"text": text, "buttons": [], "menu": []})

    return {"sent": len(phones), "audience": body.audience}
