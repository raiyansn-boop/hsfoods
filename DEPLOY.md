# Deploying HSFOODS to Render (free, permanent HTTPS)

This gets you a permanent `https://…onrender.com` link — install the customer &
manager apps on any phone, no PC required.

## What's already prepared
- `render.yaml` — Render blueprint (build + start commands, health check)
- `runtime.txt` — Python 3.12
- App **auto-seeds** the catalogue on first boot, so a fresh cloud DB isn't empty
- A local git repo with your first commit is ready to push

## Steps (~5 minutes)

### 1. Put the code on GitHub
1. Create a new **empty** repo at https://github.com/new (e.g. `hsfoods`) — no README.
2. In this folder (`hsfoods/`), run:
   ```powershell
   git remote add origin https://github.com/<your-username>/hsfoods.git
   git branch -M main
   git push -u origin main
   ```

### 2. Deploy on Render
1. Sign up / log in at https://render.com (free, GitHub login works).
2. **New +** → **Blueprint** → connect your `hsfoods` repo.
3. Render reads `render.yaml` and creates the service. Click **Apply**.
4. (Optional) In the service's **Environment** tab, add secrets:
   - `ANTHROPIC_API_KEY` — turns on the AI assistant
   - `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID` — real WhatsApp
5. Wait for the build → you get `https://hsfoods-xxxx.onrender.com`.

### 3. Install on your phone
- **Customer app:** open `https://…onrender.com/shop.html` in Chrome → **⋮** → **Add to Home screen**
- **Manager app:** open `https://…onrender.com/` → **Add to Home screen**

## Good to know
- **Free tier sleeps** after ~15 min idle; the first request then takes ~30s to wake. Fine for demos.
- **Data resets on redeploy/restart** (free tier has an ephemeral disk + SQLite). The catalogue re-seeds automatically; test orders/customers won't persist across restarts. For permanent data, add a Render **persistent disk** (paid) or migrate to Postgres — ask and I'll wire it up.
