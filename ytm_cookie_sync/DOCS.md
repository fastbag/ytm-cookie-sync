# YTM Cookie Sync

*(Deutsch weiter unten)*

## How it works
Music Assistant's YouTube Music provider authenticates with browser cookies. Google rotates cookies in open YouTube tabs, so a cookie copied from your everyday browser stops working once you keep using YouTube there. Music Assistant does not store rotated cookies itself.

This app keeps a **dedicated** browser session on your Home Assistant host that is used only for Music Assistant (the same idea as the "private window" method in the Music Assistant docs):

1. You sign in once in the panel **YTM Login** (Chromium shown through noVNC, only reachable through Home Assistant ingress, admins only).
2. The app reads the cookies **directly from the browser's cookie database**. The browser is never remote-controlled: in testing, YouTube deleted the session cookies when music.youtube.com was loaded in a DevTools-controlled browser.
3. The cookies are handed to Music Assistant through the official setup-flow API (`config/providers/reconfigure` / `config/providers/setup` + `config/flows/submit`). Music Assistant runs its own premium check and restores the previous values on failure.
4. Every `check_interval_minutes` the app asks Music Assistant whether the provider is healthy (local only). Every `deep_check_hours` one plain page request checks whether the cookies are still signed in at YouTube. After a Music Assistant restart a check runs after about 60 s.
5. If the provider fails, the app re-reads the cookies and sends them again (limited retries: 5/15/45 min, then a 6 h pause and a notification).
6. If Google has ended the session, the app reports **login_required** (sensor, persistent notification, optional phone notification). Open the **YTM Login** panel: the browser starts automatically with the Google sign-in page and your e-mail pre-filled. Sign in and confirm on your phone – the app detects the new cookies, finishes the sign-in by itself and sends them to Music Assistant.

A fully unattended re-login after Google has ended the session is **not** possible and not attempted (no stored password, no 2FA/CAPTCHA circumvention).

## Setup
1. Install and start the **Music Assistant** and **YT Music PO Token Generator** apps.
2. In Music Assistant: **Settings → Profile → Long-lived access tokens → Create** (as an **admin** user). The token of the Home Assistant integration is *not* sufficient.
3. App configuration: `ma_token` = that token, `yt_username` = your Google e-mail address, `language`, optionally `notify_service` (e.g. `notify.mobile_app_my_phone`). Leave `dry_run: true` for the first run.
4. Start the app, open **YTM Login**, press **Start sign-in**, accept the consent page, sign in until your avatar is shown, wait one minute, press **Sign-in finished**. The log shows `complete=True, YouTube check signed_in=True` if everything is fine.
5. Set `dry_run: false` and restart. If no YouTube Music provider exists yet, press **Renew now** in the panel once (or set `auto_create_provider: true`).

**Tip:** Do not use YouTube in the app browser afterwards and do not sign out there – that would rotate or end the session used by Music Assistant.

## Entities
`sensor.ytm_cookie_sync` – state `ok`, `login_required`, `refreshing`, `error`, `ma_error`, `no_provider`, `provider_disabled`, `dry_run`, `login_mode`; attributes with timestamps and a short cookie fingerprint (never cookie values).

## Commands
Panel buttons or the action `hassio.addon_stdin` with `input`: `login`, `login_done`, `check`, `refresh`.

## Security
- No Google password is stored by the app. If you let Chromium's password manager save your password in the app browser, note that Chromium on Linux without a keyring stores it only weakly encrypted in the app's data folder (and thus in Home Assistant backups).
- Cookie values, tokens and authorization headers are never written to the log.
- The browser runs as a dedicated non-root user with `--no-sandbox` (the container has no user namespaces). VNC listens on localhost only; the web server only accepts the Home Assistant ingress proxy.
- `/data` (profile, state) is part of Home Assistant backups – keep backups encrypted.

## Known limitations
- How long a session lasts depends on Google and is not predictable.
- Phone notifications contain no deep link: the iOS companion app did not reliably open app/ingress pages from notifications.

---

# YTM Cookie Sync (Deutsch)

## Funktionsweise
Der YouTube-Music-Provider von Music Assistant meldet sich mit Browser-Cookies an. Google rotiert Cookies in offenen YouTube-Tabs; ein aus dem Alltagsbrowser kopiertes Cookie wird ungültig, sobald man dort weiter YouTube nutzt. Music Assistant speichert rotierte Cookies nicht selbst.

Die App hält eine **eigene** Browsersitzung auf dem Home-Assistant-Rechner, die nur Music Assistant nutzt (Prinzip „privates Fenster“ aus der Music-Assistant-Doku):

1. Einmalige Anmeldung im Panel **YTM Login** (Chromium über noVNC, nur über Home-Assistant-Ingress, nur Admins).
2. Die Cookies werden **direkt aus der Cookie-Datenbank** des Browsers gelesen, der Browser wird nie ferngesteuert.
3. Übergabe an Music Assistant über die offizielle Setup-Flow-Schnittstelle; Music Assistant prüft selbst (Premium) und stellt bei Fehlern den alten Stand wieder her.
4. Alle `check_interval_minutes` Prüfung des Provider-Status (nur lokal), alle `deep_check_hours` ein einzelner Seitenabruf bei YouTube, nach einem Music-Assistant-Neustart nach ca. 60 s.
5. Fällt der Provider aus, werden die Cookies neu gelesen und übertragen (begrenzte Wiederholungen 5/15/45 min, dann 6 h Pause und Meldung).
6. Hat Google die Sitzung beendet, meldet die App **login_required** (Sensor, Hinweis, optional Handy). Panel **YTM Login** öffnen: Der Browser startet automatisch mit der Google-Anmeldung und vorausgefüllter E-Mail. Anmelden, auf dem Handy bestätigen – die App erkennt die neuen Cookies, schließt selbst ab und überträgt sie.

Eine vollständig unbeaufsichtigte Neuanmeldung ist **nicht** möglich und wird nicht versucht (kein gespeichertes Passwort, keine Umgehung von 2FA/CAPTCHA).

## Einrichtung
1. Apps **Music Assistant** und **YT Music PO Token Generator** installieren und starten.
2. In Music Assistant als **Admin**: **Einstellungen → Profil → Langzeit-Zugriffstoken → Erstellen**. Das Token der Home-Assistant-Integration reicht nicht.
3. App-Konfiguration: `ma_token`, `yt_username` (Google-E-Mail), `language: de`, optional `notify_service`. Beim ersten Start `dry_run: true` lassen.
4. App starten, **YTM Login** öffnen, **Anmeldung starten**, Einwilligung bestätigen, anmelden bis der Avatar erscheint, eine Minute warten, **Anmeldung abgeschlossen**. Im Protokoll sollte `complete=True, YouTube check signed_in=True` stehen.
5. `dry_run: false` setzen und neu starten. Gibt es noch keinen YouTube-Music-Provider, im Panel einmal **Jetzt erneuern** drücken (oder `auto_create_provider: true`).

**Hinweis:** Im App-Browser danach nicht YouTube nutzen und nicht abmelden.

## Sicherheit
Kein Google-Passwort in der App. Speichert man das Passwort im Passwortmanager des App-Browsers, liegt es unter Linux ohne Schlüsselbund nur schwach verschlüsselt im Datenordner der App (und damit in HA-Sicherungen). Protokolle enthalten nie Cookie-Werte oder Tokens. Sicherungen verschlüsselt halten.
