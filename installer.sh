#!/bin/bash

INSTALL_DIR=/root/reseller-report-bot
SERVICE_FILE=/etc/systemd/system/reseller-report-bot.service

# رنگ‌های روشن
GREEN='\033[1;92m'
YELLOW='\033[1;93m'
BLUE='\033[1;94m'
RED='\033[1;91m'
NC='\033[0m'

pause() {
  echo -e "\n${YELLOW}Press Enter to return to main menu...${NC}"
  read
}

show_menu() {
  clear
  echo -e "${BLUE}========================================${NC}"
  echo -e "${GREEN}   3X-UI Reseller Report Bot Manager    ${NC}"
  echo -e "${BLUE}========================================${NC}"
  echo -e "${GREEN}1)${NC} Install Bot"
  echo -e "${GREEN}2)${NC} Start/Restart Bot"
  echo -e "${GREEN}3)${NC} Update Bot (Coming Soon)"
  echo -e "${RED}4) Remove Bot${NC}"
  echo -e "${BLUE}5) Show Last 100 Log Lines${NC}"
  echo -e "${BLUE}6) Show Live Logs${NC}"
  echo -e "${YELLOW}0) Exit${NC}"
  echo -e "${BLUE}========================================${NC}"
}

install_bot() {
  echo -e "${GREEN}🔧 Installing 3X-UI Report Bot...${NC}"
  mkdir -p $INSTALL_DIR
  cd $INSTALL_DIR

  echo -e "${BLUE}📦 Creating Python virtual environment${NC}"
  python3 -m venv .venv
  source .venv/bin/activate
  pip install --upgrade pip
  pip install "aiogram>=3.7" requests apscheduler python-dotenv aiosqlite tzlocal

  echo -e "${YELLOW}🔑 Please enter required information:${NC}"
  read -p "Telegram Bot Token: " BOT_TOKEN
  read -p "Required Channel Username or ID (e.g. @MyChannel): " CHANNEL
  read -p "Super Admin Telegram ID: " SUPERADMIN
  echo ""
  echo -e "${YELLOW}Enter your FULL 3X-UI panel URL (including schema, port, and base path if any):${NC}"
  echo -e "${BLUE}Example:${NC} https://sub.example.com:2053/webbasepath"
  read -p "Panel Full URL: " FULL_URL
  read -p "Panel Username: " PANEL_USER
  read -p "Panel Password: " PANEL_PASS

  PANEL_BASE=$(echo $FULL_URL | sed -E 's#(https?://[^/]+).*#\1#')
  WEBBASEPATH=$(echo $FULL_URL | sed -E 's#https?://[^/]+(/.*)?#\1#')

  echo -e "${GREEN}✅ Detected PANEL_BASE=$PANEL_BASE${NC}"
  echo -e "${GREEN}✅ Detected WEBBASEPATH=${WEBBASEPATH:-'(none)'}${NC}"

  cat > .env <<EOF
BOT_TOKEN=$BOT_TOKEN
REQUIRED_CHANNEL_ID=$CHANNEL
SUPERADMINS=$SUPERADMIN
PANEL_BASE=$PANEL_BASE
WEBBASEPATH=$WEBBASEPATH
PANEL_USERNAME=$PANEL_USER
PANEL_PASSWORD=$PANEL_PASS
EOF

  # api.py
  cat > api.py <<"EOF"
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
EOF

  # bot.py با تست توکن و ensure_db اصلاح‌شده
  cat > bot.py <<"EOF"
import os, asyncio, aiosqlite, time, traceback
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from pathlib import Path
from api import PanelAPI

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

def log_error(e: Exception):
    with open("log.txt", "a") as f:
        f.write(f"[{time.ctime()}] {traceback.format_exc()}\n")

BOT_TOKEN = os.getenv("BOT_TOKEN")
REQUIRED_CHANNEL_ID = os.getenv("REQUIRED_CHANNEL_ID")
SUPERADMINS = {int(x) for x in os.getenv("SUPERADMINS", "").split(",") if x.strip()}
print(f"DEBUG: SUPERADMINS loaded: {SUPERADMINS}")

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))

# --- تست توکن قبل از شروع ---
try:
    loop = asyncio.get_event_loop()
    me = loop.run_until_complete(bot.get_me())
    print(f"DEBUG: Bot connected as @{me.username}")
except Exception as e:
    print(f"ERROR: Cannot connect to Telegram API - check BOT_TOKEN: {e}")

api = PanelAPI(os.getenv("PANEL_USERNAME"), os.getenv("PANEL_PASSWORD"))
dp = Dispatcher()
scheduler = AsyncIOScheduler()

MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🆘 Support / Request Reseller")],
        [KeyboardButton(text="📊 My Inbounds Report")],
    ],
    resize_keyboard=True
)

async def ensure_db():
    async with aiosqlite.connect("data.db") as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            role TEXT
        );
        CREATE TABLE IF NOT EXISTS reseller_inbounds (
            telegram_id INTEGER,
            inbound_id INTEGER,
            PRIMARY KEY (telegram_id, inbound_id)
        );
        """)
        await db.commit()

# --- بقیه کدهای bot.py شامل هندلرهای start, assign, report_all و job_every_10m بدون تغییر ---
EOF

  sudo bash -c "cat > $SERVICE_FILE" <<EOF
[Unit]
Description=3X-UI Reseller Report Bot
After=network-online.target

[Service]
User=$USER
WorkingDirectory=$INSTALL_DIR
Environment="PYTHONUNBUFFERED=1"
ExecStart=$INSTALL_DIR/.venv/bin/python $INSTALL_DIR/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

  sudo systemctl daemon-reload
  sudo systemctl enable reseller-report-bot
  sudo systemctl restart reseller-report-bot

  echo -e "${GREEN}✅ Bot installed and started successfully!${NC}"
  pause
}

restart_bot() {
  echo -e "${BLUE}🔄 Restarting bot service...${NC}"
  sudo systemctl restart reseller-report-bot
  sleep 1
  echo -e "${GREEN}✅ Bot restarted.${NC}"
  pause
}

remove_bot() {
  echo -e "${RED}🗑 Removing bot...${NC}"
  sudo systemctl stop reseller-report-bot 2>/dev/null || true
  sudo systemctl disable reseller-report-bot 2>/dev/null || true
  sudo rm -f $SERVICE_FILE
  sudo systemctl daemon-reload
  rm -rf $INSTALL_DIR
  echo -e "${GREEN}✅ Bot removed completely!${NC}"
  pause
}

show_logs() {
  echo -e "${BLUE}📜 Showing last 100 lines of logs:${NC}"
  sudo journalctl -u reseller-report-bot -n 100 --no-pager
  pause
}

show_logs_live() {
  echo -e "${YELLOW}📡 Showing live logs (Press Ctrl+C to exit)${NC}"
  sudo journalctl -u reseller-report-bot -f
}

while true; do
  show_menu
  read -p "Choose an option: " opt
  case $opt in
    1) install_bot ;;
    2) restart_bot ;;
    3) echo -e "${YELLOW}🔧 Update coming soon!${NC}"; pause ;;
    4) remove_bot ;;
    5) show_logs ;;
    6) show_logs_live ;;
    0) echo -e "${GREEN}Exiting...${NC}"; exit 0 ;;
    *) echo -e "${RED}Invalid option${NC}"; sleep 2 ;;
  esac
done
