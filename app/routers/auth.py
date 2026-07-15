"""Customer OTP login for the HSFOODS storefront.

Passwordless phone verification: request a 6-digit code, then verify it. The
code is delivered over the WhatsApp Cloud API when credentials are configured;
otherwise the endpoint runs in dev mode and returns the code in the response so
the flow still works end-to-end for testing.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db

router = APIRouter(prefix="/api/shop/auth", tags=["auth"])


class PhoneIn(BaseModel):
    phone: str


class VerifyIn(BaseModel):
    phone: str
    code: str


def _clean_phone(raw: str) -> str:
    return "".join(ch for ch in (raw or "") if ch.isdigit())


async def _send_code(phone: str, code: str) -> bool:
    """Deliver the code over WhatsApp. Returns True if sent, False when no
    credentials are configured (caller then falls back to dev mode)."""
    conn = db.get_conn()
    try:
        cfg = db.whatsapp_config(conn)
        db.log_message(conn, phone, "bot", "🔐 Login code sent")
    finally:
        conn.close()
    token, phone_id = cfg["token"], cfg["phoneId"]
    if not token or not phone_id:
        print(f"[otp:dev] {phone} -> {code}")
        return False
    body = (f"🔐 Your HSFOODS login code is *{code}*.\n"
            "It expires in 5 minutes. Do not share it with anyone.")
    import httpx  # lazy import — only needed for live sending
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://graph.facebook.com/v20.0/{phone_id}/messages",
                headers={"Authorization": f"Bearer {token}"},
                json={"messaging_product": "whatsapp", "to": phone,
                      "type": "text", "text": {"body": body}},
            )
        return True
    except Exception as exc:  # never fail login just because the send errored
        print(f"[otp:send-failed] {phone}: {exc}")
        return False


@router.post("/send-otp")
async def send_otp(body: PhoneIn):
    phone = _clean_phone(body.phone)
    if len(phone) < 8:
        raise HTTPException(status_code=400, detail="Enter a valid phone number")
    conn = db.get_conn()
    try:
        code, cooldown = db.create_otp(conn, phone)
    finally:
        conn.close()
    if code is None:
        raise HTTPException(status_code=429, detail=f"Please wait {cooldown}s before requesting a new code")
    sent = await _send_code(phone, code)
    resp = {"sent": True, "channel": "whatsapp" if sent else "dev", "devMode": not sent}
    if not sent:
        resp["devCode"] = code   # dev/testing only — surfaced when messaging isn't configured
    return resp


@router.post("/verify-otp")
def verify_otp(body: VerifyIn):
    phone = _clean_phone(body.phone)
    conn = db.get_conn()
    try:
        ok, reason = db.verify_otp(conn, phone, body.code)
    finally:
        conn.close()
    if not ok:
        msg = {
            "expired": "Code expired — request a new one",
            "too_many": "Too many attempts — request a new code",
            "no_code": "No active code — request one first",
            "mismatch": "Incorrect code — try again",
        }.get(reason, "Verification failed")
        raise HTTPException(status_code=400, detail=msg)
    return {"verified": True}
