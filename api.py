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

class PanelAPI:
    def __init__(self):
        self.session = requests.Session()
        self.token = None

    def login(self, username, password):
        try:
            r = self.session.post(LOGIN_URL, data={"username": username, "password": password})
            if r.status_code == 200 and "access_token" in r.json():
                self.token = r.json()["access_token"]
                self.session.headers.update({"Authorization": f"Bearer {self.token}"})
                return True
        except Exception as e:
            print("Login error:", e)
        return False

    def get_inbounds(self):
        try:
            r = self.session.get(INB_LIST)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            print("Inbound error:", e)
        return []

    def get_online_users(self):
        try:
            r = self.session.get(ONLINE)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            print("Online users error:", e)
        return []
