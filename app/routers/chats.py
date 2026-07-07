"""Live Messages — admin inbox over all bot conversations."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db
from .whatsapp import _send_whatsapp

router = APIRouter(prefix="/api/chats", tags=["chats"])


class AdminReply(BaseModel):
    message: str


@router.get("")
def list_chats():
    """Conversation list: one row per phone, newest activity first."""
    conn = db.get_conn()
    try:
        names = {c["phone"]: c["name"] for c in conn.execute("SELECT phone, name FROM customers").fetchall()}
        rows = conn.execute(
            """
            SELECT m.phone,
                   COUNT(*)               AS message_count,
                   MAX(m.created_at)      AS last_at
            FROM messages m
            GROUP BY m.phone
            ORDER BY last_at DESC
            """
        ).fetchall()
        out = []
        for r in rows:
            last = conn.execute(
                "SELECT text, source FROM messages WHERE phone = ? ORDER BY created_at DESC LIMIT 1",
                (r["phone"],),
            ).fetchone()
            out.append({
                "phone": r["phone"],
                "name": names.get(r["phone"], "WhatsApp Customer"),
                "messageCount": r["message_count"],
                "lastAt": r["last_at"],
                "lastText": last["text"][:80] if last else "",
                "lastSource": last["source"] if last else None,
            })
        return out
    finally:
        conn.close()


@router.get("/{phone}")
def chat_history(phone: str):
    """Full message history for one phone, oldest first."""
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM messages WHERE phone = ? ORDER BY created_at",
            (phone,),
        ).fetchall()
        cust = conn.execute("SELECT name FROM customers WHERE phone = ?", (phone,)).fetchone()
        return {
            "phone": phone,
            "name": cust["name"] if cust else "WhatsApp Customer",
            "messages": [
                {"id": r["id"], "source": r["source"], "text": r["text"], "createdAt": r["created_at"]}
                for r in rows
            ],
        }
    finally:
        conn.close()


@router.post("/{phone}/send")
async def send_admin_reply(phone: str, body: AdminReply):
    """Manual admin reply — stored, and sent to real WhatsApp when configured."""
    text = body.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="message required")
    conn = db.get_conn()
    try:
        row = db.log_message(conn, phone, "admin", text)
    finally:
        conn.close()
    await _send_whatsapp(phone, {"text": text, "buttons": [], "menu": []})
    return row
