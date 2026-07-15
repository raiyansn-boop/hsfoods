"""HSFOODS — FastAPI application entry point."""
import json
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import db
from .routers import (assistant, auth, broadcast, categories, chats, customers, orders,
                      products, referrals, reports, settings, shop, templates, whatsapp)

PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"

app = FastAPI(title="HSFOODS", description="WhatsApp fruits sales management system")


@app.middleware("http")
async def no_cache_static(request, call_next):
    """Dev QoL: stop browsers from caching the dashboard assets."""
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith((".js", ".css", ".html")):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    # auto-seed the catalogue on a fresh (e.g. freshly-deployed) database
    conn = db.get_conn()
    try:
        empty = conn.execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"] == 0
    finally:
        conn.close()
    if empty:
        from .seed import run as seed_run
        seed_run()


@app.get("/api/health")
def health():
    return {"ok": True, "service": "hsfoods"}


app.include_router(products.router)
app.include_router(categories.router)
app.include_router(orders.router)
app.include_router(customers.router)
app.include_router(reports.router)
app.include_router(settings.router)
app.include_router(templates.router)
app.include_router(shop.router)
app.include_router(auth.router)
app.include_router(referrals.router)
app.include_router(assistant.router)
app.include_router(broadcast.router)
app.include_router(chats.router)
app.include_router(whatsapp.router)


@app.get("/.well-known/assetlinks.json")
def assetlinks():
    """Digital Asset Links — proves the Play Store TWA owns this domain so it
    runs fullscreen. Paste the JSON from PWABuilder/Bubblewrap into the
    ANDROID_ASSETLINKS env var (or public/.well-known/assetlinks.json)."""
    raw = os.getenv("ANDROID_ASSETLINKS", "").strip()
    if raw:
        return Response(content=raw, media_type="application/json")
    f = PUBLIC_DIR / ".well-known" / "assetlinks.json"
    if f.exists():
        return Response(content=f.read_text(encoding="utf-8"), media_type="application/json")
    return Response(content=json.dumps([]), media_type="application/json")


@app.get("/")
def index():
    return FileResponse(PUBLIC_DIR / "index.html")


# Serve the dashboard static assets (styles.css, app.js, etc.)
app.mount("/", StaticFiles(directory=PUBLIC_DIR), name="static")
