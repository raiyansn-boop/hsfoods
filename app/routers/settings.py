"""Store settings — currently the payment setup (COD / UPI)."""
from fastapi import APIRouter
from pydantic import BaseModel

from .. import db

router = APIRouter(prefix="/api/settings", tags=["settings"])


class PaymentSettings(BaseModel):
    codEnabled: bool | None = None
    upiEnabled: bool | None = None
    upiVpa: str | None = None
    upiName: str | None = None


class WhatsAppSettings(BaseModel):
    token: str | None = None
    phoneId: str | None = None
    wabaId: str | None = None
    verifyToken: str | None = None


@router.get("/payment")
def get_payment():
    conn = db.get_conn()
    try:
        cfg = db.payment_config(conn)
        # expose the raw toggle too, so the UI can show "UPI on but no VPA yet"
        cfg["upiToggle"] = db.get_setting(conn, "upi_enabled", "0") == "1"
        return cfg
    finally:
        conn.close()


@router.patch("/payment")
def update_payment(body: PaymentSettings):
    conn = db.get_conn()
    try:
        if body.codEnabled is not None:
            db.set_setting(conn, "cod_enabled", "1" if body.codEnabled else "0")
        if body.upiEnabled is not None:
            db.set_setting(conn, "upi_enabled", "1" if body.upiEnabled else "0")
        if body.upiVpa is not None:
            db.set_setting(conn, "upi_vpa", body.upiVpa.strip())
        if body.upiName is not None:
            db.set_setting(conn, "upi_name", body.upiName.strip() or "HSFOODS")
        conn.commit()
        cfg = db.payment_config(conn)
        cfg["upiToggle"] = db.get_setting(conn, "upi_enabled", "0") == "1"
        return cfg
    finally:
        conn.close()


def _wa_view(conn) -> dict:
    cfg = db.whatsapp_config(conn)
    tok = cfg["token"]
    return {
        "tokenSet": bool(tok),
        "tokenHint": ("…" + tok[-4:]) if tok else "",
        "phoneId": cfg["phoneId"],
        "wabaId": cfg["wabaId"],
        "verifyToken": cfg["verifyToken"],
        "connected": bool(tok and cfg["phoneId"]),
    }


@router.get("/whatsapp")
def get_whatsapp():
    conn = db.get_conn()
    try:
        return _wa_view(conn)
    finally:
        conn.close()


@router.patch("/whatsapp")
def update_whatsapp(body: WhatsAppSettings):
    conn = db.get_conn()
    try:
        # only overwrite the token when a new one is actually provided
        if body.token is not None and body.token.strip():
            db.set_setting(conn, "wa_token", body.token.strip())
        if body.phoneId is not None:
            db.set_setting(conn, "wa_phone_id", body.phoneId.strip())
        if body.wabaId is not None:
            db.set_setting(conn, "wa_waba_id", body.wabaId.strip())
        if body.verifyToken is not None:
            db.set_setting(conn, "wa_verify_token", body.verifyToken.strip() or "hsfoods-verify")
        conn.commit()
        return _wa_view(conn)
    finally:
        conn.close()
