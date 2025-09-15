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
  echo -e "${GREEN}3)${NC} Update Bot (Reinstall source, keep .env)"
  echo -e "${RED}4) Remove Bot (full wipe)${NC}"
  echo -e "${BLUE}5) Show Last 100 Log Lines${NC}"
  echo -e "${BLUE}6) Show Live Logs${NC}"
  echo -e "${YELLOW}0) Exit${NC}"
  echo -e "${BLUE}========================================${NC}"
}

write_api_py() {
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
}

write_bot_py() {
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

# --- ENV ---
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

def log_error(e: Exception):
    with open("log.txt", "a") as f:
        f.write(f"[{time.ctime()}] {traceback.format_exc()}\n")

BOT_TOKEN = os.getenv("BOT_TOKEN")
REQUIRED_CHANNEL_ID = os.getenv("REQUIRED_CHANNEL_ID")
SUPERADMINS = {int(x) for x in os.getenv("SUPERADMINS", "").split(",") if x.strip()}
print(f"DEBUG: SUPERADMINS loaded: {SUPERADMINS}")

# --- CORE OBJECTS ---
bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
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

# --- DB ---
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

# --- TOKEN TEST ---
async def test_token():
    try:
        me = await bot.get_me()
        print(f"DEBUG: Bot connected as @{me.username}")
    except Exception as e:
        print(f"ERROR: Cannot connect to Telegram API - check BOT_TOKEN: {e}")
        raise

# --- REPORT BUILDER ---
async def build_report(inbound_ids):
    try:
        data = api.inbounds()
        online_emails = set(api.online_clients() or [])
        total_users = total_up = total_down = expiring = expired = online_count = low_traffic = 0

        for ib in data:
            if ib.get("id") not in inbound_ids:
                continue
            clients = ib.get("settings", {}).get("clients", ib.get("clients", []))
            for c in clients:
                total_users += 1
                up, down = int(c.get("up", 0)), int(c.get("down", 0))
                total_up += up
                total_down += down
                if c.get("email") in online_emails:
                    online_count += 1
                quota = int(c.get("total", 0))
                used = up + down
                if quota > 0 and (quota - used) < 1024**3:
                    low_traffic += 1
                exp = int(c.get("expiryTime", 0) or c.get("expire", 0))
                if exp > 0:
                    rem = (exp / 1000) - time.time()
                    if 0 < rem <= 24 * 3600:
                        expiring += 1
                    if rem <= 0:
                        expired += 1

        def hb(n):
            for u in ["B", "KB", "MB", "GB", "TB"]:
                if n < 1024:
                    return f"{n:.0f} {u}"
                n /= 1024
            return f"{n:.1f} PB"

        return (f"📊 Report:\n"
                f"👥 Users: {total_users}\n"
                f"⬇️ Download: {hb(total_down)}\n"
                f"⬆️ Upload: {hb(total_up)}\n"
                f"🟢 Online: {online_count}\n"
                f"⏳ Expiring (<24h): {expiring}\n"
                f"🚫 Expired: {expired}\n"
                f"⚠️ Low traffic (<1GB): {low_traffic}")
    except Exception as e:
        log_error(e)
        return "❌ Error while generating report. Check log.txt"

# --- HANDLERS ---
@dp.message(Command("start"))
async def start(m: Message):
    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL_ID, m.from_user.id)
        if member.status not in ("member", "administrator", "creator"):
            await m.answer(f"Please join {REQUIRED_CHANNEL_ID} first and then send /start again.")
            return
    except Exception:
        await m.answer("❌ Cannot verify channel membership right now. Try again later.")
        return

    async with aiosqlite.connect("data.db") as db:
        await db.execute("INSERT OR IGNORE INTO users(telegram_id, role) VALUES (?, 'user')", (m.from_user.id,))
        await db.commit()
    await m.answer("Welcome to 3X-UI Report Bot 👋", reply_markup=MAIN_KB)

@dp.message(Command("assign"))
async def assign_inbound(m: Message):
    print(f"DEBUG: Checking admin: from_user.id={m.from_user.id}, SUPERADMINS={SUPERADMINS}")
    if m.from_user.id not in SUPERADMINS:
        await m.answer("⛔️ Access denied.")
        return
    parts = m.text.split()
    if len(parts) != 3:
        await m.answer("Usage: /assign <telegram_id> <inbound_id>")
        return
    tg_id, inbound_id = int(parts[1]), int(parts[2])
    async with aiosqlite.connect("data.db") as db:
        await db.execute("INSERT OR IGNORE INTO users (telegram_id, role) VALUES (?, 'reseller')", (tg_id,))
        await db.execute("INSERT OR REPLACE INTO reseller_inbounds (telegram_id, inbound_id) VALUES (?, ?)", (tg_id, inbound_id))
        await db.commit()
    await m.answer(f"✅ Assigned inbound {inbound_id} to user {tg_id}")
    try:
        await bot.send_message(tg_id, f"🔑 You have been assigned to inbound {inbound_id}.")
    except Exception:
        pass

@dp.message(Command("report_all"))
async def report_all(m: Message):
    if m.from_user.id not in SUPERADMINS:
        await m.answer("⛔️ Access denied.")
        return
    data = api.inbounds()
    all_ids = [ib.get("id") for ib in data]
    report = await build_report(all_ids)
    await m.answer("📢 Full Panel Report:\n" + report)

@dp.message(F.text == "📊 My Inbounds Report")
async def my_report(m: Message):
    async with aiosqlite.connect("data.db") as db:
        rows = await db.execute_fetchall("SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=?", (m.from_user.id,))
    if not rows:
        await m.answer("No inbound assigned to you.")
        return
    report = await build_report([r[0] for r in rows])
    await m.answer(report)

# --- SCHEDULED JOB ---
async def job_every_10m():
    try:
        async with aiosqlite.connect("data.db") as db:
            rows = await db.execute_fetchall("SELECT DISTINCT telegram_id FROM reseller_inbounds")
        for (tg,) in rows:
            async with aiosqlite.connect("data.db") as db:
                ibs = await db.execute_fetchall("SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=?", (tg,))
            inbound_ids = [r[0] for r in ibs]
            rep = await build_report(inbound_ids)
            try:
                await bot.send_message(tg, "⏱ 10-min report:\n" + rep)
            except Exception:
                pass
    except Exception as e:
        log_error(e)

# --- MAIN ---
async def main():
    await test_token()
    await ensure_db()
    scheduler.add_job(job_every_10m, "interval", minutes=10)
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
EOF
}

ensure_service() {
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

  write_api_py
  write_bot_py
  ensure_service
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

update_bot() {
  echo -e "${YELLOW}⬆️ Updating bot source (keeping .env)...${NC}"
  sudo systemctl stop reseller-report-bot 2>/dev/null || true
  cd $INSTALL_DIR || { echo -e "${RED}❌ Not installed.${NC}"; pause; return; }
  source .venv/bin/activate || true
  pip install --upgrade pip
  pip install --upgrade "aiogram>=3.7" requests apscheduler python-dotenv aiosqlite tzlocal
  # بازنویسی سورس‌ها (به‌جز .env)
  write_api_py
  write_bot_py
  ensure_service
  sudo systemctl restart reseller-report-bot
  echo -e "${GREEN}✅ Update completed and service restarted.${NC}"
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

# --- MAIN MENU LOOP ---
while true; do
  show_menu
  read -p "Choose an option: " opt
  case $opt in
    1) install_bot ;;
    2) restart_bot ;;
    3) update_bot ;;
    4) remove_bot ;;
    5) show_logs ;;
    6) show_logs_live ;;
    0) echo -e "${GREEN}Exiting...${NC}"; exit 0 ;;
    *) echo -e "${RED}Invalid option${NC}"; sleep 1 ;;
  esac
done
