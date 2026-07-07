# Publishing the HSFOODS customer app to Google Play

The customer app (`/shop.html`) goes on the Play Store as a **Trusted Web
Activity (TWA)** — a thin Android wrapper around your live PWA. It looks and
behaves like a normal native app (fullscreen, no browser bars).

> The **manager app** normally stays install-to-home-screen (internal tool). You
> *can* publish it too as a second listing with the same steps if you want.

## Prerequisites
1. **Your app deployed to HTTPS** — do `DEPLOY.md` first (Render). You need the
   `https://…onrender.com` URL. (A custom domain is nicer but not required.)
2. **Google Play Developer account** — one-time **$25** at
   https://play.google.com/console (needs a Google account + ID verification).
3. **A privacy policy URL** — Play requires one. A simple hosted page is fine.

## The app already provides
- A TWA-ready `shop-manifest.json` (standalone, 512px maskable icon, theme color)
- The Digital Asset Links endpoint at `/.well-known/assetlinks.json`
  (returns `[]` until you paste your app's fingerprint — see step 3 below)

---

## Path A — PWABuilder (easiest, no local tools) ✅ recommended
1. Go to **https://www.pwabuilder.com** and enter your `https://…onrender.com/shop.html`.
2. It scores the PWA, then **Package for stores → Android → Google Play → Generate**.
3. Download the zip. It contains:
   - `app-release-bundle.aab`  ← upload this to Play
   - `signing-key-info` / `assetlinks.json`  ← contains your SHA-256 fingerprint
4. **Wire up Asset Links:** copy the `assetlinks.json` contents PWABuilder gives you
   and set it as the **`ANDROID_ASSETLINKS`** environment variable in Render
   (Dashboard → your service → Environment). Redeploy. Verify:
   `https://…onrender.com/.well-known/assetlinks.json` now shows your fingerprint.
5. In **Play Console → Create app**, upload the `.aab`, fill the store listing
   (title, description, icon, ≥2 screenshots, privacy policy URL, content rating),
   and submit for review. First review takes a few days.

## Path B — Bubblewrap CLI (local build, more control)
Needs **Node.js + JDK 17 + Android SDK**. Then:
```bash
npm i -g @bubblewrap/cli
bubblewrap init --manifest https://…onrender.com/shop-manifest.json
bubblewrap build        # produces app-release-bundle.aab + a signing key
```
Take the SHA-256 from `bubblewrap fingerprint` → build the `assetlinks.json` →
set it as `ANDROID_ASSETLINKS` in Render (as in Path A step 4) → upload the
`.aab` to Play Console.

---

## Notes
- **Keep the signing key safe** — losing it means you can't push updates.
- **Updates are automatic**: because it's a TWA, changing your website updates
  the app content instantly. You only re-upload an `.aab` to change the app
  name, icon, or native shell.
- The free Render tier sleeps when idle; consider a paid tier or a lightweight
  host before a public launch so first-open isn't slow.
