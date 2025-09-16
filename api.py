import os, requests

class PanelAPI:
    def __init__(self, username, password):
        self.base = os.getenv("PANEL_BASE")
        self.path = os.getenv("WEBBASEPATH")
        self.session = requests.Session()
        self.login(username, password)

    def login(self, username, password):
        url = f"{self.base}{self.path}/login"
        r = self.session.post(url, json={"username": username, "password": password}, verify=False)
        if r.status_code != 200:
            raise Exception(f"Login failed: {r.text}")

    def inbounds(self):
        url = f"{self.base}{self.path}/panel/api/inbounds/list"
        r = self.session.get(url, verify=False)
        return r.json().get("obj", [])

    def online_clients(self):
        url = f"{self.base}{self.path}/panel/api/inbounds/onlines"
        r = self.session.get(url, verify=False)
        return r.json().get("obj", [])

    # --- متد امن برای گرفتن مصرف کاربران ---
    def client_traffics(self, inbound_id: int):
        url = f"{self.base}{self.path}/panel/api/inbounds/getClientTraffics/{inbound_id}"
        try:
            r = self.session.get(url, verify=False, timeout=10)
            if r.status_code != 200:
                print(f"DEBUG: client_traffics failed with status {r.status_code}")
                return {}
            data = r.json().get("obj", [])
            traffics = {}
            for c in data:
                email = c.get("email", "unknown")
                traffics[email] = {
                    "up": int(c.get("up", 0)),
                    "down": int(c.get("down", 0))
                }
            return traffics
        except Exception as e:
            print(f"DEBUG: client_traffics exception for inbound {inbound_id}: {e}")
            return {}