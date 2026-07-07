import os

from fastapi import APIRouter, Request, Response

from ..bot_engine import handle_message
from ..models import SimulateIn

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])


@router.post("/simulate")
def simulate(body: SimulateIn):
    """In-browser / API simulator: {phone, message} -> structured bot reply."""
    result = handle_message(body.phone, body.message)
    return {"reply": result["text"], "buttons": result["buttons"], "menu": result["menu"]}


@router.get("/webhook")
def verify_webhook(request: Request):
    """Meta WhatsApp Cloud API verification handshake."""
    verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "hsfoods-verify")
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == verify_token:
        return Response(content=params.get("hub.challenge", ""), media_type="text/plain")
    return Response(status_code=403)


@router.post("/webhook")
async def inbound_webhook(request: Request):
    """Inbound messages from the Meta Cloud API."""
    payload = await request.json()
    try:
        value = payload["entry"][0]["changes"][0]["value"]
        msg = value["messages"][0]
        sender = msg["from"]
        text = _extract_text(msg)
        if text is not None:
            result = handle_message(sender, text)
            await _send_whatsapp(sender, result)
    except (KeyError, IndexError, TypeError):
        pass  # not a user message (status update, etc.)
    return {"status": "ok"}


def _extract_text(msg: dict) -> str | None:
    """Pull the user's input from a text message or an interactive tap."""
    if msg.get("type") == "text":
        return msg["text"]["body"]
    if msg.get("type") == "interactive":
        interactive = msg["interactive"]
        if interactive.get("type") == "button_reply":
            return interactive["button_reply"]["id"]
        if interactive.get("type") == "list_reply":
            return interactive["list_reply"]["id"]
    return None


def _payload_for(to: str, result: dict) -> dict:
    """Build the Cloud API message payload — interactive list, reply buttons,
    or plain text depending on what the bot returned."""
    base = {"messaging_product": "whatsapp", "to": to}
    text = result["text"]
    menu = result.get("menu") or []
    buttons = result.get("buttons") or []

    if menu:
        # Interactive list message: one section per category,
        # max 10 rows total, title <= 24 chars, section title <= 24 chars.
        # WhatsApp can't mix a list with reply buttons, so any quick replies
        # become an "Actions" section at the end of the same list.
        max_item_rows = 10 - min(len(buttons), 3) if buttons else 10
        sections: list[dict] = []
        for row in menu[:max_item_rows]:
            section_name = (row.get("section") or "Menu")[:24]
            if not sections or sections[-1]["title"] != section_name:
                sections.append({"title": section_name, "rows": []})
            sections[-1]["rows"].append({
                "id": row["id"],
                "title": row["title"][:24],
                "description": row.get("description", "")[:72],
            })
        if buttons:
            sections.append({
                "title": "Actions",
                "rows": [{"id": b, "title": b[:24].capitalize()} for b in buttons[:3]],
            })
        return {
            **base,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": text[:1024]},
                "action": {"button": "🍃 View menu", "sections": sections[:10]},
            },
        }

    if buttons:
        # Reply buttons: max 3, title <= 20 chars
        return {
            **base,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": text[:1024]},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": b, "title": b[:20]}}
                        for b in buttons[:3]
                    ]
                },
            },
        }

    return {**base, "type": "text", "text": {"body": text}}


async def _send_whatsapp(to: str, result: dict) -> None:
    token = os.getenv("WHATSAPP_TOKEN")
    phone_id = os.getenv("WHATSAPP_PHONE_ID")
    if not token or not phone_id:
        print(f"[whatsapp:dry-run] -> {to}:\n{result['text']}\n")
        return
    import httpx  # imported lazily — only needed for live WhatsApp sending
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://graph.facebook.com/v20.0/{phone_id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json=_payload_for(to, result),
        )
