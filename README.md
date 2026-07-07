# 🍃 HSFOODS — WhatsApp Fruits Sales Management System

A self-contained sales management system for a fresh-fruits business, driven by a
WhatsApp ordering bot. Built fresh — independent of the Freshly project.

**Stack:** Python + FastAPI + SQLite (stdlib `sqlite3`) + a vanilla JS dashboard.
No external DB server, no build step.

## Features
- 📱 **WhatsApp ordering bot** — customers order in plain text (`"2 mango, 1 apple"`); the bot builds a cart, double-confirms, and places the order ([app/bot_engine.py](app/bot_engine.py)).
- 🧪 **Live bot simulator** in the dashboard — test the whole flow in the browser, no WhatsApp credentials needed.
- 📊 **Sales dashboard** — revenue (today + 7-day trend), top sellers, low-stock alerts, channel split.
- 📦 **Product/inventory management** — add/edit/delete, live stock editing, auto stock decrement on each sale.
- 🧾 **Orders** — status pipeline (placed → packed → out for delivery → delivered).
- 👥 **Customers** — auto-created from WhatsApp orders, with spend + order history.
- 🔌 **Meta WhatsApp Cloud API webhook** ready (verification + inbound handling) for going live.
- 📚 **Auto API docs** at `/docs` (FastAPI Swagger UI).

## Quick start (Windows / PowerShell)
```powershell
cd hsfoods
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m app.seed                       # load 10 starter fruits
.\.venv\Scripts\python.exe -X utf8 -m uvicorn app.main:app --port 4000
```
macOS / Linux:
```bash
cd hsfoods
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m app.seed
.venv/bin/python -m uvicorn app.main:app --port 4000
```

Open **http://localhost:4000**, go to the **WhatsApp Bot** tab, and try:
```
menu
2 mango, 1 strawberries
confirm
confirm
```
Then check the **Dashboard** / **Orders** tabs — your order is live.

> **Note (Windows):** the `-X utf8` flag forces UTF-8 mode so emoji in console/log
> output don't crash on the default cp1252 codepage. Not needed on macOS/Linux.

## Going live with real WhatsApp
1. Copy `.env.example` → `.env` and fill in `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`, `WHATSAPP_VERIFY_TOKEN`.
2. Point your Meta app's webhook to `https://<your-host>/api/whatsapp/webhook`.
3. The same bot engine handles real inbound messages and replies via the Graph API (`httpx`).

## Android apps (PWA)
HSFOODS ships as two installable Progressive Web Apps (no Play Store / Android Studio needed):

- **Customer app** — open **`/shop.html`** on an Android phone in Chrome → menu ⋮ → *Add to Home screen*. Mobile ordering: browse categories, cart, checkout with address + COD/UPI + wallet, order tracking, loyalty. Green 🍃 icon.
- **Manager app** — open **`/`** → *Add to Home screen* for the full dashboard as a standalone app. Navy icon.

Both work offline (service worker app-shell cache) and launch fullscreen. Icons live in `public/icons/`, manifests are `public/manifest.json` (manager) and `public/shop-manifest.json` (customer).

## Lifetime Referral & Wallet
A full referral engine, configurable via env (`REFERRAL_DEFAULT_PCT`,
`REFERRAL_RETURN_WINDOW_DAYS`, `REFERRAL_MARGIN_GUARD`):

- **Lifetime link** — a referred customer is bound to their referrer permanently; the
  referrer earns on *every* future order, not just the first.
- **Item-wise rules** — each product has a referral bonus (`percent` or `flat`), an
  optional **cap**, and a **margin guard** (a bonus exceeding a share of the line's
  gross margin is held for review).
- **Ledger states** — `provisional → approved → reversed`, plus `review` for anomalies.
- **Wallet credit only after delivery + return window** — provisional rewards are
  approved once the order is `delivered` and the return window has elapsed
  (`POST /api/referrals/process`, also auto-run on delivery).
- **Manual review reasons** — `self_referral`, `cap_breach`, `return_window`, `low_margin`.
- **Liability reporting** — `GET /api/referrals/liability` for accounting / MIS
  (outstanding liability vs. paid-out), also surfaced on the dashboard.
- **Customer-facing** — bot commands `mycode` (code + wallet preview) and
  `ref <CODE>` (apply a referrer).
- **AI assistant (MIS)** — the Referrals tab has a Claude-powered assistant
  (`POST /api/assistant`) for natural-language questions about liability, wallets,
  and sales. Set `ANTHROPIC_API_KEY` to enable; without it, it returns a
  deterministic liability snapshot.

## API
| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/reports/summary` | dashboard metrics |
| GET/POST/PATCH/DELETE | `/api/products` | catalogue + item-wise referral rules |
| GET/POST/PATCH | `/api/orders` | orders (status drives referral approval/reversal) |
| GET | `/api/customers` | customers + referral code + wallet |
| GET | `/api/referrals` | per-referrer summary & wallets |
| GET | `/api/referrals/ledger` | referral ledger (`?status=`) |
| GET | `/api/referrals/liability` | liability report (accounting / MIS) |
| POST | `/api/referrals/process` | approve rewards past delivery + return window |
| PATCH | `/api/referrals/ledger/{id}` | manually approve / reverse an entry |
| POST | `/api/assistant` | `{ question }` → Claude answer over live MIS data |
| POST | `/api/whatsapp/simulate` | `{ phone, message }` → bot reply |
| GET/POST | `/api/whatsapp/webhook` | Meta Cloud API webhook |
| GET | `/docs` | interactive API docs |

## Project layout
```
hsfoods/
├── requirements.txt
├── app/
│   ├── main.py               FastAPI app + static dashboard mount
│   ├── db.py                 SQLite layer (stdlib sqlite3)
│   ├── models.py             Pydantic request models
│   ├── bot_engine.py         WhatsApp conversation logic
│   ├── seed.py               starter catalogue  (python -m app.seed)
│   └── routers/              products, orders, customers, reports, whatsapp
├── public/                   dashboard (index.html, app.js, styles.css)
└── data/                     SQLite db (auto-created, git-ignored)
```
