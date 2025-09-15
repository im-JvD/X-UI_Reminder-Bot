import os, time, requests
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

PANEL_BASE = os.getenv("PANEL_BASE", "").rstrip("/")
WEBBASEPATH = os.getenv("WEBBASEPATH", "").strip("/")
if WEBBASEPATH and not WEBBASEPATH.startswith("/"):
    WEBBASEPATH = "/" + WEBBASEPATH

LOGIN_URL = f"{PANEL_BASE}{WEBBASEPATH}/login"
INB_LIST = f"{PANEL_BASE}{WEBBASEPATH}/panel/api/inbounds/list"
ONLINE = f"{PANEL_BASE}{WEBBASEPATH}/panel/api/inbounds/onlines"
TRAFF_EMAIL = f"{PANEL_BASE}{WEBBASEPATH}/panel/api/inbounds/getClientTraffics/{{email}}"

print(f"DEBUG: PANEL_BASE={PANEL_BASE}, WEBBASEPATH={WEBBASEPATH}, LOGIN_URL={LOGIN_URL}")

class PanelAPI:
    def __init__(self, username, password):
        self.u, self.p = username, password
        self.s = requests.Session()
        self.last_login = 0

    def _login(self, force=False):
        if not force and time.time() - self.last_login < 600:
            return
        r = self.s.post(LOGIN_URL, json={"username": self.u, "password": self.p}, timeout=20)
        r.raise_for_status()
        if len(self.s.cookies) == 0:
            raise RuntimeError("Login failed (no cookies received).")
        print(f"DEBUG: Login successful, cookies: {list(self.s.cookies.keys())}")
        self.last_login = time.time()

    def inbounds(self):
        self._login()
        r = self.s.get(INB_LIST, timeout=20)
        if r.status_code == 401:
            self._login(force=True); r = self.s.get(INB_LIST, timeout=20)
        r.raise_for_status()
        return r.json()

    def online_clients(self):
        self._login()
        r = self.s.post(ONLINE, timeout=20)
        if r.status_code == 401:
            self._login(force=True); r = self.s.post(ONLINE, timeout=20)
        r.raise_for_status()
        return r.json()

    def client_traffics_by_email(self, email):
        self._login()
        r = self.s.get(TRAFF_EMAIL.format(email=email), timeout=20)
        if r.status_code == 401:
            self._login(force=True); r = self.s.get(TRAFF_EMAIL.format(email=email), timeout=20)
        r.raise_for_status()
        return r.json()
