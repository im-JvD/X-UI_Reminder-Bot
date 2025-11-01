import os, time, requests, logging
from dotenv import load_dotenv
from pathlib import Path

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")


class PanelAPI:
    def __init__(self, username, password, base_url, web_base_path=""):
        self.u, self.p = username, password
        self.s = requests.Session()
        self.last_login = 0
        
        # --- NEW: Dynamically construct all necessary URLs ---
        self.base_url = base_url.rstrip('/')
        
        if web_base_path and not web_base_path.startswith('/'):
            web_base_path = '/' + web_base_path
        self.web_base_path = web_base_path.rstrip('/')

        self.login_url = f"{self.base_url}{self.web_base_path}/login"
        self.inbounds_url = f"{self.base_url}{self.web_base_path}/panel/api/inbounds/list"
        self.online_clients_url = f"{self.base_url}{self.web_base_path}/panel/api/inbounds/onlines"

    def login(self, force=False) -> bool:
        if not force and time.time() - self.last_login < 600:
            return True
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'application/json, text/plain, */*',
                'Content-Type': 'application/json;charset=UTF-8'
            }
            # Use the dynamically constructed login_url
            r = self.s.post(self.login_url, json={"username": self.u, "password": self.p}, headers=headers, timeout=20, verify=False)
            r.raise_for_status()

            if "3x-ui" not in self.s.cookies:
                logging.error(f"Login failed: '3x-ui' Cookie not Received. Status: {r.status_code}. Response: {r.text[:200]}")
                return False

            self.last_login = time.time()
            return True
        except requests.exceptions.RequestException as e:
            logging.error(f"Login Request to {self.login_url} failed: {e}")
            return False

    def _safe_json(self, response):
        try:
            return response.json()
        except requests.exceptions.JSONDecodeError:
            txt = response.text
            if len(txt) > 200:
                txt = txt[:200] + "... [truncated]"
            return {"error": f"❌ Non-JSON response from panel: {txt}"}

    def _extract_obj(self, data):
        if isinstance(data, dict):
            if data.get("success") and "obj" in data:
                return data["obj"]
            if not data.get("success", True):
                return {"error": data.get("msg", "Unknown panel error")}
        return data

    def inbounds(self):
        if not self.login():
             return []
        try:
            # Use the dynamically constructed inbounds_url
            r = self.s.get(self.inbounds_url, timeout=20, verify=False)
            if r.status_code == 401:
                if not self.login(force=True):
                    return []
                r = self.s.get(self.inbounds_url, timeout=20, verify=False)
            r.raise_for_status()
            data = self._safe_json(r)
            return self._extract_obj(data)
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to get Inbounds from {self.inbounds_url}: {e}")
            return []

    def online_clients(self):
        if not self.login():
            return []
        try:
            # Use the dynamically constructed online_clients_url
            r = self.s.post(self.online_clients_url, timeout=20, verify=False)
            if r.status_code == 401:
                if not self.login(force=True):
                    return []
                r = self.s.post(self.online_clients_url, timeout=20, verify=False)
            r.raise_for_status()
            data = self._safe_json(r)
            return self._extract_obj(data)
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to get Online Clients from {self.online_clients_url}: {e}")
            return []
