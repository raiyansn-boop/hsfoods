"""HSFOODS — WhatsApp fruits sales management system (FastAPI).

Loads ``hsfoods/.env`` into the process environment on import, before any
submodule reads config (db.py reads REFERRAL_* constants at import time).
Real environment variables always win over .env values.
"""
import os
from pathlib import Path

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def _load_env() -> None:
    if not _ENV_FILE.exists():
        return
    for raw in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


_load_env()
