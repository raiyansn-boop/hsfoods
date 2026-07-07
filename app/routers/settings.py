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
