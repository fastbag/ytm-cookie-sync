"""YTM Cookie Sync – keeps a dedicated YouTube browser session and renews the cookies of
the Music Assistant "YouTube Music" provider when needed.

Principles:
- No passwords, no automated Google sign-in, no CAPTCHA/2FA circumvention. The user
  signs in interactively (noVNC via Home Assistant ingress).
- Cookies, tokens and authorization headers are never logged (only names, count and a
  short SHA-256 fingerprint).
- Cookies are read directly from the Chromium profile database. The browser is NOT
  remote-controlled: in testing, loading music.youtube.com in a DevTools-controlled
  browser caused YouTube to delete the session cookies.
- Cookies are handed to Music Assistant only through its official setup-flow API
  (config/providers/reconfigure or config/providers/setup + config/flows/submit).
  Music Assistant validates them itself (premium check) and restores the previous values
  on failure.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import logging
import os
import queue
import re
import shutil
import signal
import socket
import socketserver
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cookiedb  # noqa: E402
from texts import Translator  # noqa: E402
from wsclient import WSClient, WSClosed, recv_frame, send_frame  # noqa: E402

try:
    TZ = ZoneInfo(os.environ.get("TZ") or "UTC")
except ZoneInfoNotFoundError:
    TZ = ZoneInfo("UTC")

OPTIONS_FILE = "/data/options.json"
STATE_FILE = "/data/state.json"
PROFILE_DIR = "/data/chromium"
VNC_PORT = 5900
HTTP_PORT = 8099
LOGIN_DISPLAY = ":99"
INGRESS_PROXY_IP = "172.30.32.2"
NOVNC_DIR = "/usr/share/novnc"
MA_POLL = 15                        # seconds: Music Assistant restart detection
AUTO_FINISH_DELAY = 45              # seconds of stable new sign-in before auto-finish
YTM_URL = "https://music.youtube.com/"
YT_HOSTS = (".youtube.com", "music.youtube.com", ".music.youtube.com")
NEEDED_COOKIES = ("__Secure-3PAPISID", "SAPISID", "LOGIN_INFO")
MIN_BROWSER_INTERVAL = 30 * 60      # at most one cookie check every 30 min
LOGIN_TIMEOUT = 30 * 60             # sign-in mode ends after 30 min at the latest
LOGIN_REQUIRED_RECHECK = 24 * 3600  # signed-out session: check only once a day
BACKOFF = (5 * 60, 15 * 60, 45 * 60, 90 * 60)


def iso_now() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- logging
class RedactFilter(logging.Filter):
    """Last line of defence: strip cookie/token-like content from log lines."""

    PATTERNS = [
        (re.compile(r"((?:__Secure-[\w-]+|SAPISID|APISID|HSID|SSID|SID|LOGIN_INFO|SIDCC|PREF|VISITOR_\w+)=)[^;\s\"']+"),
         r"\1***"),
        (re.compile(r"(?i)(bearer\s+)[\w\-.]+"), r"\1***"),
        (re.compile(r"(?i)(\"?(?:token|cookie|authorization)\"?\s*[:=]\s*\"?)[^\"',}\s]+"), r"\1***"),
        (re.compile(r"eyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]+"), "***JWT***"),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for pat, rep in self.PATTERNS:
            msg = pat.sub(rep, msg)
        record.msg, record.args = msg, ()
        return True


log = logging.getLogger("ytm_sync")


def setup_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    fmt.converter = lambda ts: datetime.fromtimestamp(ts, TZ).timetuple()
    handler.setFormatter(fmt)
    handler.addFilter(RedactFilter())
    log.handlers[:] = [handler]
    log.setLevel(getattr(logging, level.upper(), logging.INFO))


def fingerprint(cookie: str) -> str:
    return hashlib.sha256(cookie.encode()).hexdigest()[:10] if cookie else "-"


# --------------------------------------------------------------------------- state
class State:
    def __init__(self) -> None:
        self.data: dict = {
            "status": "start",
            "message": "",
            "last_check": None,
            "last_ok": None,
            "last_refresh": None,
            "last_refresh_result": None,
            "browser_session": "unknown",
            "browser_checked": None,
            "provider_instance": None,
            "provider_state": None,
            "pushed_cookie": "",
            "pushed_fingerprint": "-",
            "last_deep_check": None,
            "retries": 0,
            "next_attempt_ts": 0,
            "last_browser_ts": 0,
        }
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, encoding="utf-8") as fh:
                    self.data.update(json.load(fh))
            except (OSError, ValueError) as err:
                log.warning("State file unreadable (%s) – starting with empty state", err)

    def save(self) -> None:
        tmp = STATE_FILE + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, STATE_FILE)

    def __getitem__(self, k):
        return self.data.get(k)

    def __setitem__(self, k, v):
        self.data[k] = v

    def public(self) -> dict:
        return {k: v for k, v in self.data.items() if k != "pushed_cookie"}


# --------------------------------------------------------------------------- Home Assistant
class HomeAssistant:
    def __init__(self, notify_service: str, t: Translator) -> None:
        self.t = t
        self.token = os.environ.get("SUPERVISOR_TOKEN", "")
        if not self.token:
            try:
                with open("/run/s6/container_environment/SUPERVISOR_TOKEN", encoding="utf-8") as fh:
                    self.token = fh.read().strip()
            except OSError:
                pass
        if not self.token:
            log.warning("No SUPERVISOR_TOKEN – sensor and notifications in Home Assistant unavailable")
        self.notify_service = (notify_service or "").strip()

    def _call(self, method: str, path: str, body: dict | None = None) -> None:
        if not self.token:
            return
        req = urllib.request.Request(
            f"http://supervisor/core/api/{path}",
            data=json.dumps(body or {}).encode(),
            method=method,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp.read()
        except (urllib.error.URLError, OSError) as err:
            log.warning("Home Assistant call %s failed: %s", path, err)

    def set_sensor(self, state: State) -> None:
        d = state.public()
        icon = {"ok": "mdi:check-circle", "login_required": "mdi:account-alert",
                "dry_run": "mdi:test-tube", "refreshing": "mdi:refresh", "login_mode": "mdi:monitor-account"}
        attrs = {
            "friendly_name": "YTM Cookie Sync",
            "icon": icon.get(d["status"], "mdi:alert-circle"),
            **{k: d.get(k) for k in ("message", "last_check", "last_ok", "last_refresh", "last_refresh_result",
                                     "browser_session", "browser_checked", "provider_instance", "provider_state",
                                     "pushed_fingerprint", "last_deep_check", "retries")},
        }
        self._call("POST", "states/sensor.ytm_cookie_sync", {"state": d["status"], "attributes": attrs})

    def notify(self, title: str, message: str) -> None:
        stamp = datetime.now(TZ).strftime(self.t("stamp"))
        self._call("POST", "services/persistent_notification/create",
                   {"notification_id": "ytm_cookie_sync", "title": title, "message": f"**{stamp}**\n\n{message}"})
        if self.notify_service:
            svc = self.notify_service.replace("notify.", "", 1)
            # No deep link on purpose: the iOS companion app does not reliably open app/ingress
            # pages from notifications. The message points to the sidebar instead.
            self._call("POST", f"services/notify/{svc}", {
                "title": title, "message": f"{stamp}: {message}{self.t('notify_suffix')}",
                "data": {"tag": "ytm_cookie_sync"}})

    def dismiss(self) -> None:
        self._call("POST", "services/persistent_notification/dismiss", {"notification_id": "ytm_cookie_sync"})


# --------------------------------------------------------------------------- Music Assistant
class MAError(Exception):
    pass


class MusicAssistant:
    def __init__(self, url: str, token: str) -> None:
        u = urllib.parse.urlparse(url)
        self.host = u.hostname or "d5369777-music-assistant"
        self.port = u.port or 8095
        self.token = token

    def call(self, commands: list[tuple[str, dict]], timeout: float = 180) -> list:
        """Run commands sequentially within one authenticated websocket session."""
        if not self.token:
            raise MAError("No Music Assistant token configured (option ma_token)")
        try:
            ws = WSClient(self.host, self.port, "/ws", timeout=timeout)
        except OSError as err:
            raise MAError(f"Music Assistant unreachable ({self.host}:{self.port}): {err}") from err
        try:
            ws.recv_json()  # server info
            results = []
            for idx, (cmd, args) in enumerate([("auth", {"token": self.token})] + commands, 1):
                ws.send_json({"message_id": str(idx), "command": cmd, "args": args})
                while True:
                    msg = ws.recv_json()
                    if msg.get("message_id") != str(idx) or msg.get("partial"):
                        continue
                    if "error_code" in msg:
                        if idx == 1:
                            raise MAError(f"Music Assistant rejected the token: {msg.get('details')}")
                        raise MAError(f"{cmd}: {msg.get('details')} (code {msg.get('error_code')})")
                    if idx > 1:
                        results.append(msg.get("result"))
                    break
            return results
        except (WSClosed, OSError, ValueError) as err:
            raise MAError(f"Connection to Music Assistant lost: {err}") from err
        finally:
            ws.close()

    def reachable(self) -> bool:
        try:
            with urllib.request.urlopen(f"http://{self.host}:{self.port}/info", timeout=5) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError):
            return False

    def ytmusic_status(self, wanted_instance: str = "") -> dict:
        configs, loaded = self.call([("config/providers", {"provider_domain": "ytmusic"}), ("providers", {})])
        configs = configs or []
        if wanted_instance:
            configs = [c for c in configs if c.get("instance_id") == wanted_instance]
        if not configs:
            return {"exists": False}
        conf = configs[0]
        inst = conf.get("instance_id")
        loaded_inst = next((p for p in (loaded or []) if p.get("instance_id") == inst), None)
        return {
            "exists": True,
            "instance_id": inst,
            "enabled": conf.get("enabled"),
            "last_error": conf.get("last_error"),
            "loaded": loaded_inst is not None,
            "available": bool(loaded_inst and loaded_inst.get("available", True)),
            "count": len(configs),
        }

    @staticmethod
    def _form_values(step: dict) -> dict:
        vals = {}
        for entry in step.get("config_entries") or step.get("entries") or []:
            if entry.get("type") in ("secure_string", "label", "divider", "alert"):
                continue
            val = entry.get("value")
            if val is None:
                val = entry.get("default_value")
            if val is not None:
                vals[entry["key"]] = val
        return vals

    def push_cookie(self, cookie: str, username: str, instance_id: str | None) -> tuple[bool, str]:
        """Send the cookies through the official setup flow. Returns (success, message)."""
        if instance_id:
            (step,) = self.call([("config/providers/reconfigure", {"instance_id": instance_id})])
        else:
            (step,) = self.call([("config/providers/setup", {"provider_domain": "ytmusic"})])
        if step.get("type") != "form":
            return False, f"Unexpected flow step {step.get('type')}: {step.get('reason') or step.get('errors')}"
        values = self._form_values(step)
        values["cookie"] = cookie
        if username:
            values["username"] = username
        if not values.get("username"):
            self._abort(step)
            return False, "No YouTube username known (set option yt_username)"
        (res,) = self.call([("config/flows/submit", {"flow_id": step["flow_id"], "values": values})], timeout=300)
        deadline = time.time() + 240  # Music Assistant may answer with a progress step first
        while res.get("type") == "progress" and time.time() < deadline:
            time.sleep(5)
            (res,) = self.call([("config/flows/get", {"flow_id": step["flow_id"]})])
        rtype = res.get("type")
        if rtype == "finish":
            return True, "Music Assistant accepted the cookies (premium check passed)"
        if rtype == "form":
            self._abort(res)
            return False, f"Music Assistant rejected the cookies: {res.get('errors')}"
        return False, f"Flow ended with {rtype}: {res.get('reason') or res.get('errors')}"

    def _abort(self, step: dict) -> None:
        try:
            self.call([("config/flows/abort", {"flow_id": step["flow_id"]})])
        except MAError:
            pass


# --------------------------------------------------------------------------- browser
class BrowserError(Exception):
    pass


def chromium_bin() -> str:
    for name in ("chromium-browser", "chromium"):
        if path := shutil.which(name):
            return path
    raise BrowserError("Chromium not found")


def user_agent() -> str:
    try:
        out = subprocess.run([chromium_bin(), "--version"], capture_output=True, text=True, timeout=20).stdout
        major = re.search(r"(\d+)\.", out).group(1)
    except (BrowserError, AttributeError, OSError, subprocess.SubprocessError):
        major = "156"
    arch = "aarch64" if os.uname().machine in ("aarch64", "arm64") else "x86_64"
    return f"Mozilla/5.0 (X11; Linux {arch}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"


def _as_chrome_user(cmd: list[str]) -> list[str]:
    return ["su-exec", "chrome"] + cmd if os.geteuid() == 0 and shutil.which("su-exec") else cmd


def _remove_stale_locks() -> None:
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        try:
            os.unlink(os.path.join(PROFILE_DIR, name))
        except FileNotFoundError:
            pass
        except OSError as err:
            log.debug("Cannot remove lock file %s: %s", name, err)


def _read_yt_cookies() -> list[dict]:
    try:
        return cookiedb.read_cookies(PROFILE_DIR, YT_HOSTS)
    except (cookiedb.CookieDBError, OSError, sqlite3.Error, UnicodeDecodeError) as err:
        raise BrowserError(f"Cookie database unreadable: {err}") from err


class Browser:
    """Chromium sign-in mode (visible through VNC) and cookie database access."""

    def __init__(self, language: str) -> None:
        self.lock = threading.Lock()
        self.login_procs: list[subprocess.Popen] = []
        self.login_started = 0.0
        self.ua = user_agent()
        self.lang = "de-DE" if language == "de" else "en-US"
        self.flags = [
            f"--user-data-dir={PROFILE_DIR}",
            "--password-store=basic",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-dev-shm-usage",
            "--no-sandbox",  # container without user namespaces; browser runs as dedicated user "chrome"
            "--disable-features=Translate,MediaRouter",
            f"--lang={self.lang}",
        ]

    def login_active(self) -> bool:
        return bool(self.login_procs) and self.login_procs[-1].poll() is None

    def start_login(self, url: str = YTM_URL) -> None:
        if self.login_active():
            return
        if not self.lock.acquire(timeout=120):
            raise BrowserError("Browser busy")
        try:
            _remove_stale_locks()
            env = dict(os.environ, DISPLAY=LOGIN_DISPLAY)
            xvfb = subprocess.Popen(["Xvfb", LOGIN_DISPLAY, "-screen", "0", "1280x900x24", "-nolisten", "tcp"],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1.5)
            vnc = subprocess.Popen(["x11vnc", "-display", LOGIN_DISPLAY, "-localhost", "-rfbport", str(VNC_PORT),
                                    "-forever", "-shared", "-nopw", "-quiet", "-noxdamage"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
            # deliberately WITHOUT remote debugging: a normal browser for the Google sign-in
            chrome = subprocess.Popen(
                _as_chrome_user([chromium_bin(), *self.flags, f"--user-agent={self.ua}",
                                 "--window-position=0,0", "--window-size=1280,900", "--start-maximized", url]),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
            self.login_procs = [xvfb, vnc, chrome]
            self.login_started = time.time()
            log.info("Sign-in mode started")
        except Exception:
            self.lock.release()
            raise

    def stop_login(self) -> None:
        if not self.login_procs:
            return
        xvfb, vnc, chrome = self.login_procs
        for proc in (chrome, vnc, xvfb):
            if proc.poll() is None:
                # Chromium: SIGINT instead of SIGTERM – only then are cookies reliably flushed (tested)
                proc.send_signal(signal.SIGINT if proc is chrome else signal.SIGTERM)
                try:
                    proc.wait(30)
                except subprocess.TimeoutExpired:
                    log.warning("Process did not terminate – killing it")
                    proc.kill()
        self.login_procs = []
        time.sleep(2)
        if self.lock.locked():
            self.lock.release()
        self.log_profile("after sign-in mode")
        log.info("Sign-in mode ended")

    def export_cookies(self) -> dict:
        """Read the YouTube cookies from the profile database and check with ONE plain page
        request whether YouTube considers them signed in. The browser is not started."""
        if self.login_active():
            raise BrowserError("Sign-in mode active – check only after the sign-in is finished")
        if not self.lock.acquire(timeout=120):
            raise BrowserError("Browser busy")
        try:
            cookies = _read_yt_cookies()
        finally:
            self.lock.release()
        header = cookiedb.cookie_header(cookies)
        names = sorted({c["name"] for c in cookies if not c["partitioned"]})
        complete = all(n in names for n in NEEDED_COOKIES)
        logged = deep_check(header, self.ua, self.lang) if complete else False
        log.info("Cookie database: %d YouTube cookies (%s), complete=%s, YouTube check signed_in=%s, fingerprint=%s",
                 len(names), ",".join(names), complete, logged, fingerprint(header))
        return {
            "logged_in": logged is True,
            "check_failed": logged is None,
            "consent": "SOCS" not in names,
            "cookie": header,
            "names": names,
            "complete": complete,
        }

    @staticmethod
    def peek_signin() -> tuple[bool, str]:
        """During sign-in mode: (sign-in cookies complete?, fingerprint of the cookie header)."""
        try:
            cookies = _read_yt_cookies()
        except BrowserError:
            return False, "-"
        names = {c["name"] for c in cookies if not c["partitioned"]}
        return all(n in names for n in NEEDED_COOKIES), fingerprint(cookiedb.cookie_header(cookies))

    @staticmethod
    def log_profile(when: str) -> None:
        """Diagnostics without content: size and age of the cookie database."""
        try:
            st = os.stat(cookiedb.find_db(PROFILE_DIR))
            log.info("Profile %s: cookie DB %d bytes, modified %s", when, st.st_size,
                     datetime.fromtimestamp(st.st_mtime, TZ).strftime("%Y-%m-%d %H:%M:%S"))
        except (cookiedb.CookieDBError, OSError) as err:
            log.info("Profile %s: no cookie DB (%s)", when, err)


def deep_check(cookie: str, ua: str, lang: str = "en-US") -> bool | None:
    """One plain page request with the cookies: still signed in? True/False, None if
    inconclusive. Response cookies are discarded."""
    if not cookie:
        return None
    req = urllib.request.Request(YTM_URL, headers={"Cookie": cookie, "User-Agent": ua,
                                                   "Accept-Language": f"{lang},{lang[:2]};q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read(3_000_000).decode("utf-8", errors="replace")
            final_url = resp.geturl()
    except (urllib.error.URLError, OSError) as err:
        log.warning("Deep check: YouTube unreachable (%s)", err)
        return None
    if "consent.youtube.com" in final_url:
        log.warning("Deep check: redirected to the consent page (SOCS missing) – inconclusive")
        return None
    if '"LOGGED_IN":true' in body:
        return True
    if '"LOGGED_IN":false' in body:
        return False
    return None


# --------------------------------------------------------------------------- ingress web server
class Handler(http.server.SimpleHTTPRequestHandler):
    service = None  # type: Service

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=NOVNC_DIR, **kwargs)

    def log_message(self, fmt, *args):  # no access logs
        return

    def _allowed(self) -> bool:
        if self.client_address[0] in (INGRESS_PROXY_IP, "127.0.0.1"):
            return True
        self.send_error(403, "Only reachable through Home Assistant ingress")
        return False

    def do_GET(self):
        if not self._allowed():
            return
        p = urllib.parse.urlparse(self.path).path
        if p.endswith("/websockify"):
            return self._ws_bridge()
        if p.endswith("/api/status"):
            return self._json(self.service.status_payload())
        return super().do_GET()

    def do_POST(self):
        if not self._allowed():
            return
        action = urllib.parse.urlparse(self.path).path.rsplit("/", 1)[-1]
        if action in ("login", "login_done", "refresh", "check"):
            self.service.commands.put(action)
            return self._json({"ok": True, "queued": action})
        self.send_error(404)

    def _json(self, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _ws_bridge(self):
        """WebSocket (noVNC) <-> TCP (x11vnc), only while sign-in mode is active."""
        if not self.service.browser.login_active():
            self.send_error(409, "Sign-in mode not active")
            return
        key = self.headers.get("Sec-WebSocket-Key", "")
        accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest())
        proto = (self.headers.get("Sec-WebSocket-Protocol") or "").split(",")[0].strip()
        self.send_response(101)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept.decode())
        if proto:
            self.send_header("Sec-WebSocket-Protocol", proto)
        self.end_headers()
        client = self.connection
        try:
            vnc = socket.create_connection(("127.0.0.1", VNC_PORT), timeout=10)
        except OSError:
            return
        vnc.settimeout(None)
        client.settimeout(None)
        stop = threading.Event()

        def vnc_to_ws():
            try:
                while not stop.is_set():
                    data = vnc.recv(65536)
                    if not data:
                        break
                    send_frame(client, data, opcode=0x2, mask=False)
            except OSError:
                pass
            stop.set()

        threading.Thread(target=vnc_to_ws, daemon=True).start()
        try:
            while not stop.is_set():
                _op, data = recv_frame(client)
                vnc.sendall(data)
        except (WSClosed, OSError):
            pass
        stop.set()
        try:
            vnc.close()
        except OSError:
            pass
        self.close_connection = True


class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


# --------------------------------------------------------------------------- service
class Service:
    def __init__(self) -> None:
        with open(OPTIONS_FILE, encoding="utf-8") as fh:
            self.opt = json.load(fh)
        setup_logging(self.opt.get("log_level", "info"))
        self.language = self.opt.get("language", "en")
        self.t = Translator(self.language)
        self.state = State()
        self.ha = HomeAssistant(self.opt.get("notify_service", ""), self.t)
        self.ma = MusicAssistant(self.opt.get("ma_url", ""), self.opt.get("ma_token", ""))
        self.browser = Browser(self.language)
        self.commands: queue.Queue = queue.Queue()
        self.dry_run = bool(self.opt.get("dry_run", True))
        self.interval = int(self.opt.get("check_interval_minutes", 30)) * 60
        self.deep_hours = int(self.opt.get("deep_check_hours", 12))
        self.max_retries = int(self.opt.get("max_retries", 3))
        self.auto_finish = False
        self.login_baseline = "-"
        self.login_ok_since = 0.0
        self.ma_reachable: bool | None = None
        self.next_ma_poll = 0.0

    # ---- helpers
    def set_status(self, status: str, message: str, notify: str | None = None) -> None:
        changed = status != self.state["status"] or message != self.state["message"]
        self.state["status"], self.state["message"] = status, message
        self.state.save()
        self.ha.set_sensor(self.state)
        if changed:
            level = logging.INFO if status in ("ok", "dry_run", "login_mode", "refreshing") else logging.WARNING
            log.log(level, "Status %s: %s", status, message)
        if notify:
            self.ha.notify(notify, message)
        elif status == "ok":
            self.ha.dismiss()

    def status_payload(self) -> dict:
        d = self.state.public()
        d.update(login_active=self.browser.login_active(), dry_run=self.dry_run, language=self.language,
                 now=datetime.now(TZ).strftime(self.t("stamp")))
        return d

    # ---- main logic
    def check(self, force_refresh: bool = False) -> None:
        self.state["last_check"] = iso_now()
        try:
            st = self.ma.ytmusic_status(self.opt.get("ma_instance_id") or "")
        except MAError as err:
            self.state["provider_state"] = "unknown"
            self.set_status("ma_error", str(err))
            return
        if not st["exists"]:
            self.state["provider_instance"] = None
            self.state["provider_state"] = "not configured"
            if force_refresh:
                self.refresh(instance_id=None, reason="manual: create YouTube Music provider", manual=True)
            elif self.opt.get("auto_create_provider"):
                self.refresh(instance_id=None, reason="YouTube Music provider missing – creating it")
            else:
                self.set_status("no_provider", self.t("no_provider"))
            return
        inst = st["instance_id"]
        self.state["provider_instance"] = inst
        healthy = st["enabled"] and st["loaded"] and st["available"] and not st["last_error"]
        self.state["provider_state"] = "ok" if healthy else (
            st["last_error"] or ("disabled" if not st["enabled"] else "not loaded"))
        if not st["enabled"]:
            self.set_status("provider_disabled", self.t("provider_disabled"))
            return
        reason = None
        if force_refresh:
            reason = "manual request"
        elif not healthy:
            reason = f"provider error: {st['last_error'] or 'not loaded/available'}"
        elif self.deep_hours and self._deep_due():
            self.state["last_deep_check"] = iso_now()
            res = deep_check(self.state["pushed_cookie"], self.browser.ua, self.browser.lang)
            if res is False:
                reason = "deep check: the cookies in Music Assistant are no longer signed in"
            elif res is True:
                log.info("Deep check: cookies in Music Assistant are still signed in")
        if reason is None:
            self.state["retries"] = 0
            self.state["last_ok"] = iso_now()
            self.set_status("ok", self.t("ok"))
            return
        self.refresh(instance_id=inst, reason=reason, manual=force_refresh)

    def _deep_due(self) -> bool:
        if not self.state["pushed_cookie"]:
            return False
        last = self.state["last_deep_check"]
        if not last:
            return True
        return (datetime.now(TZ) - datetime.fromisoformat(last)).total_seconds() >= self.deep_hours * 3600

    def refresh(self, instance_id: str | None, reason: str, manual: bool = False) -> None:
        now = time.time()
        if not manual:
            if now < (self.state["next_attempt_ts"] or 0):
                wait = int(((self.state["next_attempt_ts"] or 0) - now) / 60)
                self.set_status(self.state["status"] if self.state["status"] != "ok" else "error",
                                self.t("next_attempt", reason=reason, wait=wait))
                return
            if now - (self.state["last_browser_ts"] or 0) < MIN_BROWSER_INTERVAL:
                return
        log.info("Renewal started: %s", reason)
        self.set_status("refreshing", self.t("refreshing", reason=reason))
        self.state["last_browser_ts"] = now
        self.state["last_refresh"] = iso_now()
        try:
            exp = self.browser.export_cookies()
        except (BrowserError, OSError) as err:
            self._fail(f"cookie read failed: {err}")
            return
        self.state["browser_checked"] = iso_now()
        if exp["complete"] and exp["check_failed"]:
            self._fail(self.t("check_unclear"))
            return
        if not exp["logged_in"] or not exp["complete"]:
            self.state["browser_session"] = "signed out"
            self.state["next_attempt_ts"] = now + LOGIN_REQUIRED_RECHECK
            self.state["last_refresh_result"] = "browser session signed out"
            hint = self.t("consent_hint") if exp["consent"] else ""
            self.set_status("login_required", self.t("login_required", hint=hint),
                            notify=self.t("login_required_title"))
            return
        self.state["browser_session"] = "signed in"
        if self.dry_run:
            self.state["last_refresh_result"] = "dry run – not sent"
            self.set_status("dry_run", self.t("dry_run", fp=fingerprint(exp["cookie"])))
            return
        try:
            ok, msg = self.ma.push_cookie(exp["cookie"], self.opt.get("yt_username") or "", instance_id)
        except MAError as err:
            ok, msg = False, str(err)
        if not ok:
            self._fail(msg)
            return
        log.info("%s", msg)
        self.state["pushed_cookie"] = exp["cookie"]
        self.state["pushed_fingerprint"] = fingerprint(exp["cookie"])
        self.state["last_deep_check"] = iso_now()
        self.state["retries"] = 0
        self.state["next_attempt_ts"] = 0
        self.state["last_refresh_result"] = "success"
        time.sleep(20)  # follow-up check
        try:
            st = self.ma.ytmusic_status(self.opt.get("ma_instance_id") or "")
            good = st.get("exists") and st.get("available") and not st.get("last_error")
        except MAError:
            good = False
        if good:
            self.state["provider_instance"] = st["instance_id"]
            self.state["provider_state"] = "ok"
            self.state["last_ok"] = iso_now()
            self.set_status("ok", self.t("ok_refreshed"))
        else:
            self._fail(self.t("push_verify_failed"))

    def _fail(self, msg: str) -> None:
        self.state["retries"] = (self.state["retries"] or 0) + 1
        n = self.state["retries"]
        self.state["last_refresh_result"] = msg
        if n >= self.max_retries:
            self.state["next_attempt_ts"] = time.time() + 6 * 3600
            self.set_status("error", self.t("fail_final", n=n, msg=msg), notify=self.t("fail_final_title"))
            self.state["retries"] = 0
        else:
            wait = BACKOFF[min(n - 1, len(BACKOFF) - 1)]
            self.state["next_attempt_ts"] = time.time() + wait
            self.state["last_browser_ts"] = 0
            self.set_status("error", self.t("fail_retry", n=n, max=self.max_retries, msg=msg, wait=wait // 60))

    # ---- commands
    def handle(self, cmd: str) -> None:
        cmd = cmd.strip().lower()
        log.info("Command: %s", cmd)
        if cmd == "login":
            try:
                relogin = self.state["status"] == "login_required" or self.state["browser_session"] == "signed out"
                url = YTM_URL
                user = (self.opt.get("yt_username") or "").strip()
                if relogin and "@" in user:
                    url = (f"https://accounts.google.com/ServiceLogin?service=youtube&hl={self.language}&passive=true"
                           "&continue=" + urllib.parse.quote(YTM_URL, safe="") + "&Email=" + urllib.parse.quote(user))
                # auto-finish only once the sign-in cookies CHANGED compared to now
                self.auto_finish = relogin
                self.login_baseline = Browser.peek_signin()[1]
                self.login_ok_since = 0.0
                self.browser.start_login(url)
                self.set_status("login_mode", self.t("login_mode"))
            except BrowserError as err:
                self.set_status("error", self.t("login_failed_start", err=err))
        elif cmd == "login_done":
            self.auto_finish = False
            self.browser.stop_login()
            self.state["next_attempt_ts"] = 0
            self.state["last_browser_ts"] = 0
            # verify the browser first; new cookies (different fingerprint) are always sent if a
            # provider exists, otherwise the normal check runs
            exp = self._verify_browser_only()
            new_session = bool(exp and exp["logged_in"] and exp["complete"]
                               and fingerprint(exp["cookie"]) != self.state["pushed_fingerprint"])
            if new_session and self.state["provider_instance"]:
                log.info("New sign-in detected – sending cookies to Music Assistant")
                self.check(force_refresh=True)
            else:
                self.check(force_refresh=False)
        elif cmd == "refresh":
            self.state["next_attempt_ts"] = 0
            self.check(force_refresh=True)
        elif cmd == "check":
            self.check()
        else:
            log.warning("Unknown command: %s (allowed: login, login_done, refresh, check)", cmd)

    def _verify_browser_only(self) -> dict | None:
        try:
            exp = self.browser.export_cookies()
        except (BrowserError, OSError) as err:
            log.warning("Cookie check failed: %s", err)
            return None
        self.state["browser_checked"] = iso_now()
        self.state["browser_session"] = "signed in" if exp["logged_in"] and exp["complete"] else "signed out"
        self.state["last_browser_ts"] = time.time()
        if self.state["browser_session"] == "signed in":
            self.state["next_attempt_ts"] = 0
            self.ha.dismiss()
        else:
            hint = self.t("consent_hint") if exp["consent"] else ""
            self.ha.notify(self.t("login_not_detected_title"), self.t("login_not_detected", hint=hint))
        self.state.save()
        self.ha.set_sensor(self.state)
        return exp

    def stdin_reader(self) -> None:
        for line in sys.stdin:
            line = line.strip().strip('"')
            if line:
                self.commands.put(line)

    def _tick(self, cmd: str | None, next_check: float) -> tuple[str | None, float]:
        """Background duties: MA restart detection and automatic sign-in completion."""
        if time.time() >= self.next_ma_poll:
            self.next_ma_poll = time.time() + MA_POLL
            up = self.ma.reachable()
            if up and self.ma_reachable is False:
                log.info("Music Assistant reachable again (restart detected) – checking in 60 s")
                next_check = time.time() + 60
                self.state["last_browser_ts"] = 0
            elif not up and self.ma_reachable:
                log.info("Music Assistant unreachable (restarting?)")
            self.ma_reachable = up
        if not cmd and self.auto_finish and self.browser.login_active():
            complete, fp = Browser.peek_signin()
            if complete and fp != self.login_baseline:
                if not self.login_ok_since:
                    self.login_ok_since = time.time()
                    log.info("New sign-in cookies detected – finishing in %d s", AUTO_FINISH_DELAY)
                elif time.time() - self.login_ok_since >= AUTO_FINISH_DELAY:
                    log.info("Sign-in finished automatically")
                    cmd = "login_done"
            else:
                self.login_ok_since = 0.0
        if self.browser.login_active() and time.time() - self.browser.login_started > LOGIN_TIMEOUT:
            log.info("Sign-in mode ended automatically after %d min", LOGIN_TIMEOUT // 60)
            cmd = "login_done"
        return cmd, next_check

    def run(self) -> None:
        self.browser.log_profile("at start")
        log.info("YTM Cookie Sync starting – check interval %d min, deep check %s h, dry_run=%s, language=%s",
                 self.interval // 60, self.deep_hours or "off", self.dry_run, self.language)
        Handler.service = self
        server = ThreadingServer(("0.0.0.0", HTTP_PORT), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        threading.Thread(target=self.stdin_reader, daemon=True).start()
        signal.signal(signal.SIGTERM, lambda *_: self.commands.put("__stop__"))
        next_check = time.time() + 20
        while True:
            try:
                cmd = self.commands.get(timeout=min(max(1, next_check - time.time()), MA_POLL))
            except queue.Empty:
                cmd = None
            if cmd == "__stop__":
                break
            try:
                cmd, next_check = self._tick(cmd, next_check)
                if cmd:
                    self.handle(cmd)
                elif time.time() >= next_check and not self.browser.login_active():
                    self.check()
                    next_check = time.time() + self.interval
            except Exception as err:  # the service must never die from a single error
                log.exception("Unexpected error: %s", err)
                self.set_status("error", self.t("internal_error", err=err.__class__.__name__))
                next_check = time.time() + self.interval
        log.info("Service stopping")
        self.browser.stop_login()
        server.shutdown()


if __name__ == "__main__":
    Service().run()
