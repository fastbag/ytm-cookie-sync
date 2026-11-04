# YTM Cookie Sync

**Keep the YouTube Music provider of [Music Assistant](https://music-assistant.io) signed in – without copying browser cookies by hand.**

A Home Assistant **app** (formerly "add-on") for everyone who uses [Music Assistant](https://github.com/music-assistant/server) with [YouTube Music](https://music-assistant.io/music-providers/youtube-music/) and is tired of the message *"Your YouTube Music cookies have expired"*.

> ⚠️ **Unofficial project.** Not affiliated with Music Assistant, Nabu Casa, Google or YouTube. Beta – use at your own risk.

🇩🇪 [Deutsche Anleitung weiter unten](#deutsch)

---

## Contents
- [The problem](#the-problem)
- [How this app solves it](#how-this-app-solves-it)
- [What it can and cannot do](#what-it-can-and-cannot-do)
- [Requirements](#requirements)
- [Installation](#installation)
- [Setup step by step](#setup-step-by-step)
- [Daily operation](#daily-operation)
- [When Google ends the session (re-login)](#when-google-ends-the-session-re-login)
- [Options](#options)
- [Sensor, notifications and automations](#sensor-notifications-and-automations)
- [Security and privacy](#security-and-privacy)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)
- [Technical background](#technical-background)
- [Credits](#credits)

---

## The problem
Music Assistant's YouTube Music provider authenticates with the **cookies of a logged-in browser session** (see the [official Music Assistant documentation](https://music-assistant.io/music-providers/youtube-music/)). You copy the `Cookie` header from your browser into Music Assistant – and after some time playback stops with `401 Unauthorized` or *"cookies have expired"*, and you have to do it again.

Why this happens:
- **Google rotates account cookies** in open YouTube browser tabs as a security measure (documented by [Music Assistant](https://music-assistant.io/music-providers/youtube-music/) and [yt-dlp](https://github.com/yt-dlp/yt-dlp/wiki/Extractors)). If you copy cookies from your everyday browser and keep using YouTube there, the copy in Music Assistant becomes invalid.
- **Music Assistant stores the cookie string statically.** Rotated cookies returned by YouTube are not saved back, and there is no built-in automatic renewal (checked in the source code of Music Assistant 2.10).

## How this app solves it
The app runs its **own Chromium browser on your Home Assistant host** – a dedicated session that is used *only* for Music Assistant (the "private window" idea from the Music Assistant docs, automated):

```
 You (once)                     YTM Cookie Sync app                          Music Assistant
 ──────────                     ───────────────────                          ───────────────
 sign in via panel ──► Chromium profile (persistent, /data)
                              │
                              ▼ reads cookies directly from the
                                cookie database (no remote control)
                              │
                              ▼ official setup-flow API ──────────────────► premium check,
                                (config/providers/reconfigure …)            rollback on error
                              ▲
 check every 30 min,          │ provider healthy? cookies still signed in?
 after MA restarts, ──────────┘
 deep check every 12 h
```

1. **One-time sign-in** in the panel **YTM Login** (the browser is shown in Home Assistant via noVNC).
2. The app **reads the cookies directly from the browser's cookie database**. The browser is never remote-controlled (see [technical background](#technical-background) for why).
3. The cookies are handed over through Music Assistant's **official setup-flow API**. Music Assistant validates them with its own premium check and restores the previous values if they do not work. The app never edits Music Assistant files or databases.
4. The app **monitors** Music Assistant: every 30 minutes (local only), about 60 s after every Music Assistant restart, and every 12 hours with one page request to YouTube.
5. If the provider fails, the app re-reads the cookies and sends them again – with limited retries, no loops.
6. If Google has ended the session, the app **tells you** (sensor, notification, optionally on your phone). You open the panel, the browser starts by itself with your e-mail pre-filled, you sign in and confirm on your phone – the app does the rest.

## What it can and cannot do
| ✅ Can | ❌ Cannot |
|---|---|
| Hand valid cookies to Music Assistant automatically | Sign in to Google **without you** after Google ended the session |
| Detect failures and Music Assistant restarts | Bypass 2FA, CAPTCHA or Google security checks (and never will) |
| Tell you clearly when a new sign-in is needed | Predict how long Google keeps a session alive |
| Work without a PC – everything runs on the HA host | Make YouTube Music work without a Premium subscription |

## Requirements
- Home Assistant OS or Supervised (apps are required), architecture **amd64** or **aarch64**.
- The **Music Assistant** app (2.10 or newer, with the setup-flow API) and the **YT Music PO Token Generator** app – both from the [Music Assistant app repository](https://github.com/music-assistant/home-assistant-addon).
- A Google account with **YouTube Premium / YouTube Music Premium**.
- About 600 MB of disk space (Chromium).

## Installation
1. **Settings → Apps → App store → ⋮ → Repositories** and add:
   `https://github.com/fastbag/ytm-cookie-sync`
2. Install **YTM Cookie Sync** (the first build takes a few minutes).
3. Do **not** start it yet – configure it first.

## Setup step by step
1. **Create a Music Assistant token.** In Music Assistant (as an **admin** user): **Settings → Profile → Long-lived access tokens → Create token**, name it e.g. `ytm_cookie_sync`, copy it. *(The token used by the Home Assistant integration is not sufficient – it has no permission to configure providers.)*
2. **Configure the app** (tab *Configuration*):
   - `ma_token`: the token from step 1
   - `yt_username`: the e-mail address of your Google account
   - `language`: `en` or `de`
   - `notify_service` (optional): e.g. `notify.mobile_app_my_phone`
   - keep `dry_run: true` for now
3. **Start the app** and open the panel **YTM Login** in the sidebar.
4. Press **Start sign-in**. Accept the YouTube consent page, click *Sign in*, sign in with your Premium account and confirm on your phone if asked. Wait until your avatar is shown at the top right.
5. Wait **one minute**, then press **Sign-in finished**. The app log should show
   `Cookie database: … complete=True, YouTube check signed_in=True`.
6. Set `dry_run: false` and restart the app.
7. **No YouTube Music provider yet?** Press **Renew now** once in the panel – the app creates it in Music Assistant (or set `auto_create_provider: true`). If a provider exists, the app takes it over.
8. Check in Music Assistant that YouTube Music works. Done.

> 💡 Do **not** browse YouTube in the app browser afterwards and do **not** sign out there – that would rotate or end the session Music Assistant uses.

## Daily operation
Nothing to do. The sensor `sensor.ytm_cookie_sync` shows `ok`. Your phone, TV and other devices keep their own Google sessions and are not affected.

## When Google ends the session (re-login)
Sooner or later Google may end the session (password change, security review, inactivity, …). Then:
1. You get a notification *"YouTube Music: sign-in required"* (Home Assistant and, if configured, your phone).
2. Open the Home Assistant app → sidebar **YTM Login**. The browser starts automatically with the Google sign-in page; your e-mail is pre-filled.
3. Enter your password, confirm on your phone.
4. The app detects the **new** cookies, finishes the sign-in by itself after ~45 s and hands them to Music Assistant. The notification disappears.

Phone notifications contain **no link** on purpose: the iOS companion app did not reliably open app pages from notifications.

## Options
| Option | Default | Meaning |
|---|---|---|
| `ma_url` | `http://d5369777-music-assistant:8095` | Internal Music Assistant address (works with the official MA app) |
| `ma_token` | – | Long-lived token of a Music Assistant **admin** user |
| `yt_username` | – | Google e-mail (pre-filled at sign-in, sent to MA as username) |
| `language` | `en` | `en` / `de` for messages and panel |
| `notify_service` | – | Optional notify service for phone notifications |
| `check_interval_minutes` | 30 | Provider status check (local, no Google requests) |
| `deep_check_hours` | 12 | One YouTube page request to verify the cookies; `0` = off |
| `max_retries` | 3 | Failed renewals before a 6 h pause + notification |
| `auto_create_provider` | false | Create the YouTube Music provider if missing |
| `dry_run` | true | Check everything, but send nothing to Music Assistant |
| `ma_instance_id` | – | Only with several YouTube Music providers |
| `log_level` | info | Logs never contain cookie values or tokens |

## Sensor, notifications and automations
`sensor.ytm_cookie_sync` states:

| State | Meaning |
|---|---|
| `ok` | YouTube Music works in Music Assistant |
| `refreshing` | Renewal in progress |
| `login_required` | Google ended the session – sign in again in the panel |
| `login_mode` | Sign-in browser is open |
| `error` | Renewal failed, retry scheduled (see `message`) |
| `ma_error` | Music Assistant unreachable or token rejected |
| `no_provider` / `provider_disabled` | No (enabled) YouTube Music provider in MA |
| `dry_run` | Test mode: valid cookies found, nothing sent |

Attributes: `message`, `last_check`, `last_ok`, `last_refresh`, `last_refresh_result`, `browser_session`, `provider_state`, `pushed_fingerprint` (short hash, never the cookie) and more.

Commands (panel buttons or the action `hassio.addon_stdin`): `login`, `login_done`, `check`, `refresh`.

Example – custom notification:
```yaml
automation:
  - alias: "YouTube Music needs a new sign-in"
    triggers:
      - trigger: state
        entity_id: sensor.ytm_cookie_sync
        to: login_required
    actions:
      - action: notify.mobile_app_my_phone
        data:
          title: "YouTube Music"
          message: "Please sign in again: sidebar → YTM Login"
```

## Security and privacy
- **No Google password** is stored by the app; there is no automated Google sign-in and no 2FA/CAPTCHA circumvention.
- If you let **Chromium's password manager** save your password in the app browser: Chromium on Linux without a keyring stores it only weakly encrypted in the app's data folder (and therefore in Home Assistant backups). Your decision.
- The browser profile contains a **valid Google session** – treat Home Assistant backups as sensitive and keep them encrypted (default in current HA versions).
- **Logs** never contain cookie values, tokens or authorization headers (only cookie names and a short fingerprint); an additional redaction filter masks anything cookie-like.
- The browser runs as a dedicated non-root user. VNC listens on localhost only and runs only during sign-in; the web server only accepts the Home Assistant ingress proxy; the panel is admin-only.
- All communication with Music Assistant stays inside the Home Assistant host network.

## Troubleshooting
| Symptom | Cause / fix |
|---|---|
| `ma_error: … token is invalid` | Wrong token, or a token of the HA integration. Create a token as MA **admin**. |
| `ma_error: … Home Assistant system user not allowed` | You used the HA integration token. Use your own MA token. |
| `no_provider` | No YouTube Music provider yet → press **Renew now** once, or `auto_create_provider: true`. |
| `login_required` right after signing in | Wait a minute before pressing *Sign-in finished*; make sure the avatar was visible. Did you sign out in the app browser? |
| Log: `consent page … inconclusive` | Accept the YouTube consent page in the sign-in browser once. |
| Panel shows nothing during sign-in | Reload the panel; the browser view only appears while sign-in mode is active. |
| MA: `PO Token server not reachable` | Install/start the **YT Music PO Token Generator** app; keep the default URL in MA. |
| "Update available" for a moment after updating | Home Assistant refreshes the update entity only every few minutes. |

## FAQ
**Does this affect YouTube on my phone/TV?** No. Every device has its own Google session; the app only manages its own.

**Is Google's session bound to the IP address?** There is no evidence for that, and it does not matter here: the app browser and Music Assistant run on the same host.

**Why not store the password/2FA secret/passkey for a fully automatic login?** Storing all sign-in factors on the server effectively disables 2FA for your whole Google account (mail, photos, payments), automated logins trigger Google security checks and may lock the account, and passkeys from a phone need Bluetooth proximity to the server. The re-login takes about 30 seconds and is rarely needed.

**How often do I have to sign in again?** Depends on Google. Typically weeks to months – not predictable.

**Can I use a separate Google account?** Yes – e.g. a YouTube Premium Family member account. The Music Assistant docs recommend a dedicated account.

## Technical background
- **No remote control:** During development, loading music.youtube.com in a browser controlled via the Chrome DevTools Protocol caused YouTube to **delete** the session cookies (`SID`, `SAPISID`, `__Secure-1PSID`, `LOGIN_INFO`, …). The app therefore never automates the browser; it reads the Chromium cookie database (AES-128-CBC, `--password-store=basic`) directly.
- **Clean shutdown:** Chromium only flushes unsaved cookies on `SIGINT`, not on `SIGTERM` – the app stops the sign-in browser with `SIGINT`.
- **Official API only:** `config/providers/reconfigure` / `config/providers/setup` + `config/flows/submit` (Music Assistant 2.10). Music Assistant performs its premium check (yt-dlp, format 141) and restores the previous setup data on failure.
- **Deep check:** one `GET https://music.youtube.com/` with the cookies, evaluating `LOGGED_IN` in the page config; response cookies are discarded.
- **Restart detection:** `GET /info` on Music Assistant every 15 s (no authentication).

## Credits
- [Music Assistant](https://music-assistant.io) – the music server this app supports ([server](https://github.com/music-assistant/server), [apps](https://github.com/music-assistant/home-assistant-addon), [YouTube Music provider docs](https://music-assistant.io/music-providers/youtube-music/))
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) and [ytmusicapi](https://github.com/sigma67/ytmusicapi) – used by Music Assistant
- [noVNC](https://github.com/novnc/noVNC), [x11vnc](https://github.com/LibVNC/x11vnc), [Chromium](https://www.chromium.org)

License: [MIT](LICENSE)

---

<a id="deutsch"></a>
# 🇩🇪 Deutsch

**Hält den YouTube-Music-Provider von [Music Assistant](https://music-assistant.io) angemeldet – ohne Browser-Cookies von Hand zu kopieren.**

> ⚠️ **Inoffizielles Projekt**, nicht verbunden mit Music Assistant, Nabu Casa, Google oder YouTube. Beta – Nutzung auf eigenes Risiko.

## Das Problem
Der YouTube-Music-Provider von Music Assistant meldet sich mit den **Cookies einer angemeldeten Browsersitzung** an ([Music-Assistant-Doku](https://music-assistant.io/music-providers/youtube-music/)). Nach einiger Zeit kommt `401 Unauthorized` bzw. *„cookies have expired“*, und man muss die Cookies erneut kopieren.
- **Google rotiert die Konto-Cookies** in offenen YouTube-Tabs. Wer Cookies aus dem Alltagsbrowser kopiert und dort weiter YouTube nutzt, macht die Kopie in Music Assistant ungültig.
- **Music Assistant speichert die Cookies statisch** und erneuert sie nicht selbst (im Quellcode von MA 2.10 geprüft).

## Die Lösung
Die App betreibt einen **eigenen Chromium-Browser auf dem Home-Assistant-Rechner** – eine eigene Sitzung nur für Music Assistant:
1. **Einmalige Anmeldung** im Panel **YTM Login** (Browser wird per noVNC in Home Assistant angezeigt).
2. Die App liest die Cookies **direkt aus der Cookie-Datenbank** des Browsers; der Browser wird nie ferngesteuert.
3. Übergabe über die **offizielle Setup-Flow-Schnittstelle** von Music Assistant. MA prüft selbst (Premium) und stellt bei Fehlern den alten Stand wieder her.
4. **Überwachung:** alle 30 min (nur lokal), ca. 60 s nach jedem Music-Assistant-Neustart, alle 12 h ein einzelner Seitenabruf bei YouTube.
5. Bei Ausfall: Cookies neu lesen und übertragen, begrenzte Wiederholungen, keine Endlosschleifen.
6. Hat Google die Sitzung beendet: **Meldung** (Sensor, Hinweis, optional Handy). Panel öffnen, Browser startet automatisch mit vorausgefüllter E-Mail, Passwort eingeben, auf dem Handy bestätigen – den Rest macht die App.

## Voraussetzungen
Home Assistant OS/Supervised (amd64 oder aarch64), die Apps **Music Assistant** (ab 2.10) und **YT Music PO Token Generator** aus dem [Music-Assistant-Repository](https://github.com/music-assistant/home-assistant-addon), ein Google-Konto mit **YouTube Premium**, ca. 600 MB Speicher.

## Installation
1. **Einstellungen → Apps → App-Store → ⋮ → Repositorys** → `https://github.com/fastbag/ytm-cookie-sync` hinzufügen.
2. **YTM Cookie Sync** installieren (erster Build dauert einige Minuten), noch nicht starten.

## Einrichtung Schritt für Schritt
1. **Token in Music Assistant** (als **Admin**): **Einstellungen → Profil → Langzeit-Zugriffstoken → Erstellen**, Name z. B. `ytm_cookie_sync`, kopieren. *(Das Token der Home-Assistant-Integration reicht nicht.)*
2. **Konfiguration der App:** `ma_token`, `yt_username` (Google-E-Mail), `language: de`, optional `notify_service` (z. B. `notify.mobile_app_mein_handy`), `dry_run: true` vorerst lassen.
3. App starten, in der Seitenleiste **YTM Login** öffnen.
4. **Anmeldung starten** → Einwilligung bestätigen → *Anmelden* → mit dem Premium-Konto anmelden, ggf. auf dem Handy bestätigen, bis oben rechts der Avatar erscheint.
5. **Eine Minute warten**, dann **Anmeldung abgeschlossen**. Im Protokoll: `complete=True, YouTube check signed_in=True`.
6. `dry_run: false` setzen, App neu starten.
7. **Noch kein YouTube-Music-Provider?** Einmal **Jetzt erneuern** im Panel drücken (oder `auto_create_provider: true`). Ein vorhandener Provider wird übernommen.
8. In Music Assistant prüfen, dass YouTube Music spielt. Fertig.

> 💡 Im App-Browser danach **nicht** YouTube nutzen und **nicht** abmelden.

## Neuanmeldung, wenn Google die Sitzung beendet
1. Meldung *„YouTube Music: neue Anmeldung nötig“* (Home Assistant, optional Handy).
2. Home-Assistant-App → Seitenleiste **YTM Login** – der Browser startet automatisch, E-Mail ist vorausgefüllt.
3. Passwort eingeben, auf dem Handy bestätigen.
4. Die App erkennt die **neuen** Cookies, schließt nach ca. 45 s selbst ab und überträgt sie. Die Meldung verschwindet.

## Sicherheit
Kein Google-Passwort in der App, keine automatische Google-Anmeldung, keine Umgehung von 2FA/CAPTCHA. Wer das Passwort im Passwortmanager des App-Browsers speichert: Es liegt dann nur schwach verschlüsselt im Datenordner der App (und in HA-Sicherungen). Das Browserprofil enthält eine gültige Google-Sitzung – Sicherungen verschlüsselt halten. Protokolle enthalten nie Cookie-Werte oder Tokens. Panel nur für Admins, nur über Ingress erreichbar.

## Häufige Fragen
- **Betrifft das YouTube auf Handy/TV?** Nein, jedes Gerät hat eine eigene Sitzung.
- **IP-Bindung?** Nicht belegt und hier unerheblich (Browser und MA laufen auf demselben Rechner).
- **Warum kein gespeichertes Passwort/2FA/Passkey für vollautomatische Anmeldung?** Das würde den Schutz des gesamten Google-Kontos aushebeln, automatisierte Anmeldungen lösen Google-Sicherheitsprüfungen aus, und Passkeys vom Handy brauchen Bluetooth-Nähe zum Server.
- **Wie oft neu anmelden?** Hängt von Google ab, typischerweise Wochen bis Monate.

Optionen, Sensorzustände, Fehlerbehebung und technische Hintergründe: siehe englische Abschnitte oben bzw. Reiter **Dokumentation** der App.
