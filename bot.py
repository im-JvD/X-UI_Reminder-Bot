# Version: 1.0.0 - Stable
import os, asyncio, aiosqlite, time, traceback, json
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
        CREATE TABLE IF NOT EXISTS last_reports (
            telegram_id INTEGER PRIMARY KEY,
            last_json TEXT,
            last_full_report INTEGER
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

# --- HELPERS ---
def safe_text(text: str, limit: int = 4000) -> str:
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    if len(text) > limit:
        return text[:limit] + "\n... [truncated]"
    return text

def hb(n):
    for u in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            return f"{n:.0f} {u}"
        n /= 1024
    return f"{n:.1f} PB"

# --- REPORT BUILDER ---
def analyze_inbound(ib, online_emails):
    stats = {"users": 0, "up": 0, "down": 0, "online": 0, "expiring": [], "expired": []}
    if not isinstance(ib, dict):
        return stats

    inbound_id = ib.get("id")
    if not inbound_id:
        return stats

    # گرفتن مصرف واقعی کاربران از API (امن)
    traffics = api.client_traffics(inbound_id)

    settings = ib.get("settings")
    if isinstance(settings, str):
        try:
            settings = json.loads(settings)
        except Exception:
            settings = {}
    if not isinstance(settings, dict):
        settings = {}

    clients = settings.get("clients", ib.get("clients", []))
    for c in clients:
        stats["users"] += 1
        email = c.get("email", "unknown")

        up = traffics.get(email, {}).get("up", 0)
        down = traffics.get(email, {}).get("down", 0)
        stats["up"] += up
        stats["down"] += down

        if email in online_emails:
            stats["online"] += 1

        quota = int(c.get("total", 0) or c.get("totalGB", 0))
        used = up + down
        left = quota - used if quota > 0 else None

        exp = int(c.get("expiryTime", 0) or c.get("expire", 0))
        rem = (exp / 1000) - time.time() if exp > 0 else None

        if (rem is not None and rem <= 0) or (left is not None and left <= 0):
            stats["expired"].append(email)
        elif (left is not None and left <= 1024**3) or (rem is not None and 0 < rem <= 24 * 3600):
            stats["expiring"].append(email)

    return stats

async def build_report(inbound_ids):
    try:
        data = api.inbounds()
        if not isinstance(data, list):
            return safe_text(f"❌ Invalid response from panel: {data}"), {"expiring": [], "expired": [], "up": 0, "down": 0}

        online_emails = set(api.online_clients() or [])
        total_users = total_up = total_down = online_count = 0
        expiring, expired = [], []

        for ib in data:
            if not isinstance(ib, dict) or ib.get("id") not in inbound_ids:
                continue
            s = analyze_inbound(ib, online_emails)
            total_users += s["users"]
            total_up += s["up"]
            total_down += s["down"]
            online_count += s["online"]
            expiring.extend(s["expiring"])
            expired.extend(s["expired"])

        report = (f"📊 Report:\n"
                  f"👥 Users: {total_users}\n"
                  f"📦 Used Traffic: {hb(total_up + total_down)} "
                  f"(⬇️ {hb(total_down)} + ⬆️ {hb(total_up)})\n"
                  f"🟢 Online: {online_count}\n"
                  f"⏳ Expiring (&lt;24h or &lt;1GB): {len(expiring)}\n"
                  f"🚫 Expired: {len(expired)}")
        return safe_text(report), {"expiring": expiring, "expired": expired, "up": total_up, "down": total_down}
    except Exception as e:
        log_error(e)
        return "❌ Error while generating report. Check log.txt", {"expiring": [], "expired": [], "up": 0, "down": 0}

# --- HANDLERS (start, assign, report_all, my_report) ---
# همون نسخه‌ی قبلی بدون تغییر ...

# --- JOBS (send_full_reports, check_changes) ---
# همون نسخه‌ی قبلی که قبلاً برات نوشتم (diff + Used Traffic در بالای گزارش)

# --- MAIN ---
async def main():
    await test_token()
    await ensure_db()
    scheduler.add_job(send_full_reports, "interval", hours=24)
    scheduler.add_job(check_changes, "interval", minutes=1)  # تست روی 1 دقیقه
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())