import os, time, requests, logging
from dotenv import load_dotenv
from pathlib import Path

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

PANEL_BASE = os.getenv("PANEL_BASE", "").rstrip("/")
WEBBASEPATH = os.getenv("WEBBASEPATH", "")

if WEBBASEPATH and not WEBBASEPATH.startswith("/"):
    WEBBASEPATH = "/" + WEBBASEPATH

LOGIN_URL = f"{PANEL_BASE}{WEBBASEPATH}/login"
INB_LIST = f"{PANEL_BASE}{WEBBASEPATH}panel/api/inbounds/list"
ONLINE = f"{PANEL_BASE}{WEBBASEPATH}panel/api/inbounds/onlines"

class PanelAPI:
    def __init__(self, username, password):
        self.u, self.p = username, password
        self.s = requests.Session()
        self.last_login = 0

    def login(self, url: str, force=False) -> bool:
        if not force and time.time() - self.last_login < 600:
            return True
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'application/json, text/plain, */*',
                'Content-Type': 'application/json;charset=UTF-8'
            }

            r = self.s.post(url, json={"username": self.u, "password": self.p}, headers=headers, timeout=20, verify=False)
            
            r.raise_for_status()
            
            if "3x-ui" not in self.s.cookies:
                logging.error(f"Login failed: 'X-UI' Cookie not Received. Status: {r.status_code}. Response: {r.text[:200]}")
                return False
                
            self.last_login = time.time()
            return True
        except requests.exceptions.RequestException as e:
            logging.error(f"Login Request failed: {e}")
            return False

    def _safe_json(self, response):
        try:
            return response.json()
        except requests.exceptions.JSONDecodeError:
            txt = response.text
            if len(txt) > 200:
                txt = txt[:200] + "... [truncated]"
            return {"error": f"❌ Non-JSON response from panel."}

    def _extract_obj(self, data):
        if isinstance(data, dict):
            if data.get("success") and "obj" in data:
                return data["obj"]
            if not data.get("success", True):
                return {"error": data.get("msg", "Unknown panel error")}
        return data

    def inbounds(self):
        if not self.login(LOGIN_URL):
             return []
        try:
            r = self.s.get(INB_LIST, timeout=20, verify=False)
            if r.status_code == 401:
                if not self.login(LOGIN_URL, force=True):
                    return []
                r = self.s.get(INB_LIST, timeout=20, verify=False)
            r.raise_for_status()
            data = self._safe_json(r)
            return self._extract_obj(data)
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to get Inbounds: {e}")
            return []

    def online_clients(self):
        if not self.login(LOGIN_URL):
            return []
        try:
            r = self.s.post(ONLINE, timeout=20, verify=False)
            if r.status_code == 401:
                if not self.login(LOGIN_URL, force=True):
                    return []
                r = self.s.post(ONLINE, timeout=20, verify=False)
            r.raise_for_status()
            data = self._safe_json(r)
            return self._extract_obj(data)
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to get Online Clients: {e}")
            return []
