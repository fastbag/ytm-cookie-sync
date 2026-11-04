# YTM Cookie Sync – Home Assistant app

Keeps the **YouTube Music** provider of [Music Assistant](https://music-assistant.io) signed in without copying browser cookies by hand.

> **Unofficial.** Not affiliated with Music Assistant, Google or YouTube. Use at your own risk.

## What it does
- Runs its own Chromium browser inside a Home Assistant app. You sign in **once**, interactively, through the panel **"YTM Login"** (no password is stored by the app, no 2FA/CAPTCHA circumvention).
- Checks Music Assistant regularly and right after a Music Assistant restart.
- If the provider fails, reads fresh cookies from the browser profile and hands them to Music Assistant through its **official setup-flow API**. Music Assistant validates them (premium check) and rolls back on failure.
- If Google has ended the session, it does **not** pretend success: you get a Home Assistant notification (optionally on your phone) and sign in again in the panel – the browser opens automatically, the e-mail address is pre-filled, everything else happens automatically.

## Installation
1. Home Assistant → **Settings → Apps → App store → ⋮ → Repositories** → add `https://github.com/fastbag/ytm-cookie-sync`.
2. Install **YTM Cookie Sync**. Also needed: the **Music Assistant** app and the **YT Music PO Token Generator** app (both from the Music Assistant repository).
3. See the **Documentation** tab of the app for configuration.

## Supported
Music Assistant 2.10 (setup-flow API), architectures amd64 and aarch64.

---

## Deutsch (Kurzfassung)
Hält den **YouTube-Music**-Provider von Music Assistant angemeldet, ohne Cookies von Hand zu kopieren. Einmalige Anmeldung im Panel „YTM Login“, danach übernimmt die App die Cookies automatisch über die offizielle Music-Assistant-Schnittstelle. Läuft die Google-Sitzung ab, kommt eine Meldung, und du meldest dich mit wenigen Tipps neu an. Details im Reiter **Dokumentation** der App.

## License
MIT
