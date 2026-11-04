"""Liest Cookies direkt aus der Chromium-Cookie-Datenbank (Profil mit --password-store=basic).

Kein Browserstart, keine Fernsteuerung, kein Seitenaufruf. Die Werte werden nur im
Speicher entschlüsselt und nie protokolliert.
Format (Chromium/Linux): Präfix „v10“, AES-128-CBC, IV = 16 Leerzeichen, Schlüssel =
PBKDF2-HMAC-SHA1("peanuts", "saltysalt", 1 Iteration, 16 Byte). Ab DB-Version 24 stehen
vor dem Klartext 32 Byte SHA-256 des Hostnamens.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import tempfile
import time

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_KEY = hashlib.pbkdf2_hmac("sha1", b"peanuts", b"saltysalt", 1, 16)
_IV = b" " * 16
# Chromium speichert Zeiten in Mikrosekunden seit 1601-01-01
_EPOCH_DELTA = 11644473600


class CookieDBError(Exception):
    pass


def _decrypt(blob: bytes, host: str, strip_hash: bool) -> str:
    if not blob:
        return ""
    if blob[:3] not in (b"v10", b"v11"):
        raise CookieDBError("unbekanntes Verschlüsselungsformat")
    dec = Cipher(algorithms.AES(_KEY), modes.CBC(_IV)).decryptor()
    data = dec.update(blob[3:]) + dec.finalize()
    pad = data[-1]
    if not 1 <= pad <= 16:
        raise CookieDBError("Entschlüsselung fehlgeschlagen (falscher Schlüssel?)")
    data = data[:-pad]
    if strip_hash:
        if data[:32] != hashlib.sha256(host.encode()).digest():
            raise CookieDBError("Host-Prüfsumme passt nicht")
        data = data[32:]
    return data.decode("utf-8")


def find_db(profile_dir: str) -> str:
    for rel in (("Default", "Network", "Cookies"), ("Default", "Cookies")):
        path = os.path.join(profile_dir, *rel)
        if os.path.exists(path):
            return path
    raise CookieDBError("Cookie-Datenbank nicht gefunden")


def read_cookies(profile_dir: str, hosts: tuple[str, ...]) -> list[dict]:
    """Liefert gültige (nicht abgelaufene) Cookies der angegebenen host_keys."""
    src = find_db(profile_dir)
    with tempfile.TemporaryDirectory() as tmp:
        # Kopie lesen, damit ein laufender Browser nicht gestört wird
        dst = os.path.join(tmp, "c.db")
        shutil.copy2(src, dst)
        if os.path.exists(src + "-journal"):
            shutil.copy2(src + "-journal", dst + "-journal")
        con = sqlite3.connect(dst)
        try:
            meta = dict(con.execute("select key, value from meta").fetchall())
            strip_hash = int(meta.get("version", 0)) >= 24
            cols = {r[1] for r in con.execute("pragma table_info(cookies)")}
            partition = "top_frame_site_key" if "top_frame_site_key" in cols else "''"
            q = (f"select host_key, name, encrypted_value, value, path, expires_utc, has_expires, {partition} "
                 f"from cookies where host_key in ({','.join('?' * len(hosts))})")
            rows = con.execute(q, hosts).fetchall()
        finally:
            con.close()
    now_us = (time.time() + _EPOCH_DELTA) * 1_000_000
    out = []
    for host, name, enc, plain, path, expires, has_exp, part in rows:
        if has_exp and expires and expires < now_us:
            continue
        value = plain if plain else _decrypt(enc, host, strip_hash)
        out.append({"host": host, "name": name, "value": value, "path": path, "partitioned": bool(part)})
    return out


def cookie_header(cookies: list[dict]) -> str:
    """Cookie-Header wie ihn der Browser an music.youtube.com senden würde (ohne partitionierte)."""
    seen: dict[str, str] = {}
    # spezifischere Hosts zuletzt, damit sie gewinnen
    for c in sorted(cookies, key=lambda c: len(c["host"])):
        if c["partitioned"] or c["path"] not in ("/", ""):
            continue
        seen[c["name"]] = c["value"]
    return "; ".join(f"{k}={v}" for k, v in seen.items())
