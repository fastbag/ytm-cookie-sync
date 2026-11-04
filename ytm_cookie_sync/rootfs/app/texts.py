"""User-facing texts (status messages, notifications). Logs stay in English."""
from __future__ import annotations

TEXTS: dict[str, dict[str, str]] = {
    "en": {
        "ok": "YouTube Music in Music Assistant is working",
        "ok_refreshed": "Cookies renewed and confirmed by Music Assistant",
        "no_provider": "No YouTube Music provider is configured in Music Assistant "
                       "(automatic creation is disabled: auto_create_provider)",
        "provider_disabled": "The YouTube Music provider is disabled in Music Assistant – no action",
        "refreshing": "Renewal in progress ({reason})",
        "next_attempt": "{reason} – next renewal attempt in {wait} min",
        "login_required": "The Google session in the app browser is no longer signed in{hint}. "
                          "Open the panel \"YTM Login\" in Home Assistant – the browser starts automatically. "
                          "Sign in and confirm on your phone; everything else happens automatically.",
        "login_required_title": "YouTube Music: sign-in required",
        "consent_hint": " (consent page)",
        "dry_run": "Test mode (dry_run): valid browser cookies found but NOT sent to Music Assistant "
                   "(fingerprint {fp}).",
        "login_mode": "Sign-in mode active – sign in to YouTube Music in the app browser",
        "login_failed_start": "Sign-in mode could not be started: {err}",
        "login_not_detected_title": "YouTube Music: sign-in not detected",
        "login_not_detected": "No valid YouTube Music sign-in found in the app browser{hint}. Please sign in again.",
        "fail_retry": "Renewal failed (attempt {n}/{max}): {msg}. Next attempt in {wait} min.",
        "fail_final": "Renewal failed {n} times: {msg}. Next attempt in 6 h.",
        "fail_final_title": "YouTube Music: automatic renewal failed",
        "internal_error": "Internal error: {err}",
        "check_unclear": "YouTube sign-in check inconclusive (unreachable or consent page)",
        "push_verify_failed": "Cookies sent, but the follow-up check in Music Assistant failed",
        "notify_suffix": " Open the Home Assistant app → sidebar \"YTM Login\".",
        "stamp": "%Y-%m-%d %H:%M",
    },
    "de": {
        "ok": "YouTube Music in Music Assistant funktioniert",
        "ok_refreshed": "Cookies erneuert und von Music Assistant bestätigt",
        "no_provider": "In Music Assistant ist kein YouTube-Music-Provider eingerichtet "
                       "(automatisches Anlegen ist deaktiviert: auto_create_provider)",
        "provider_disabled": "Der YouTube-Music-Provider ist in Music Assistant deaktiviert – keine Aktion",
        "refreshing": "Erneuerung läuft ({reason})",
        "next_attempt": "{reason} – nächster Erneuerungsversuch in {wait} min",
        "login_required": "Die Google-Sitzung im App-Browser ist nicht mehr angemeldet{hint}. "
                          "Bitte in Home Assistant das Panel „YTM Login“ öffnen – der Browser startet "
                          "automatisch. Anmelden und auf dem Handy bestätigen; der Rest läuft von selbst.",
        "login_required_title": "YouTube Music: neue Anmeldung nötig",
        "consent_hint": " (Einwilligungsseite)",
        "dry_run": "Testmodus (dry_run): gültige Browser-Cookies gefunden, aber NICHT an Music Assistant "
                   "übertragen (Fingerabdruck {fp}).",
        "login_mode": "Anmeldemodus aktiv – YouTube Music im App-Browser anmelden",
        "login_failed_start": "Anmeldemodus nicht startbar: {err}",
        "login_not_detected_title": "YouTube Music: Anmeldung nicht erkannt",
        "login_not_detected": "Im App-Browser ist keine gültige YouTube-Music-Anmeldung erkennbar{hint}. "
                              "Bitte erneut anmelden.",
        "fail_retry": "Erneuerung fehlgeschlagen (Versuch {n}/{max}): {msg}. Neuer Versuch in {wait} min.",
        "fail_final": "Erneuerung {n}x fehlgeschlagen: {msg}. Nächster Versuch in 6 h.",
        "fail_final_title": "YouTube Music: automatische Erneuerung fehlgeschlagen",
        "internal_error": "Interner Fehler: {err}",
        "check_unclear": "YouTube-Anmeldeprüfung ohne eindeutiges Ergebnis (nicht erreichbar oder Einwilligungsseite)",
        "push_verify_failed": "Cookies übertragen, Nachkontrolle in Music Assistant aber nicht erfolgreich",
        "notify_suffix": " Home-Assistant-App öffnen → Seitenleiste „YTM Login“.",
        "stamp": "%d.%m.%Y · %H:%M Uhr",
    },
}


class Translator:
    def __init__(self, language: str) -> None:
        self.lang = language if language in TEXTS else "en"

    def __call__(self, key: str, **kw) -> str:
        text = TEXTS[self.lang].get(key) or TEXTS["en"][key]
        return text.format(**kw) if kw else text
