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

        # --- فیکس مقادیر up/down ---
        up = int(c.get("up", c.get("upload", c.get("uplink", 0))))
        down = int(c.get("down", c.get("download", c.get("downlink", 0))))
        stats["up"] += up
        stats["down"] += down

        if c.get("email") in online_emails:
            stats["online"] += 1

        quota = int(c.get("total", 0) or c.get("totalGB", 0))
        used = up + down
        left = quota - used if quota > 0 else None

        exp = int(c.get("expiryTime", 0) or c.get("expire", 0))
        rem = (exp / 1000) - time.time() if exp > 0 else None

        if (rem is not None and rem <= 0) or (left is not None and left <= 0):
            stats["expired"].append(c.get("email", "unknown"))
        elif (left is not None and left <= 1024**3) or (rem is not None and 0 < rem <= 24 * 3600):
            stats["expiring"].append(c.get("email", "unknown"))

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
    if not isinstance(data, list):
        await m.answer(safe_text(f"❌ Unexpected response from panel:\n{data}"))
        return
    all_ids = [ib.get("id") for ib in data if isinstance(ib, dict)]
    report, _ = await build_report(all_ids)
    await m.answer("📢 Full Panel Report:\n" + safe_text(report))

@dp.message(F.text == "📊 My Inbounds Report")
async def my_report(m: Message):
    async with aiosqlite.connect("data.db") as db:
        rows = await db.execute_fetchall("SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=?", (m.from_user.id,))
    if not rows:
        await m.answer("No inbound assigned to you.")
        return
    report, _ = await build_report([r[0] for r in rows])
    await m.answer(safe_text(report))

# --- JOBS ---
async def send_full_reports():
    """Send full report every 24h to each reseller + superadmins."""
    # Resellers
    async with aiosqlite.connect("data.db") as db:
        rows = await db.execute_fetchall("SELECT DISTINCT telegram_id FROM reseller_inbounds")
    for (tg,) in rows:
        async with aiosqlite.connect("data.db") as db:
            ibs = await db.execute_fetchall("SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=?", (tg,))
        inbound_ids = [r[0] for r in ibs]
        report, details = await build_report(inbound_ids)
        try:
            await bot.send_message(tg, "📢 Daily Full Report:\n" + safe_text(report))
            async with aiosqlite.connect("data.db") as db:
                await db.execute("INSERT OR REPLACE INTO last_reports VALUES (?, ?, ?)",
                                 (tg, json.dumps(details), int(time.time())))
                await db.commit()
        except Exception as e:
            log_error(e)

    # Superadmins: full panel
    data = api.inbounds()
    if isinstance(data, list):
        all_ids = [ib.get("id") for ib in data if isinstance(ib, dict)]
        report, details = await build_report(all_ids)
        for tg in SUPERADMINS:
            try:
                await bot.send_message(tg, "📢 Daily Full Panel Report:\n" + safe_text(report))
                async with aiosqlite.connect("data.db") as db:
                    await db.execute("INSERT OR REPLACE INTO last_reports VALUES (?, ?, ?)",
                                     (tg, json.dumps(details), int(time.time())))
                    await db.commit()
            except Exception as e:
                log_error(e)

async def check_changes():
    """Check inbound status every 1m and send only changes (resellers + superadmins)."""
    # Resellers
    async with aiosqlite.connect("data.db") as db:
        rows = await db.execute_fetchall("SELECT DISTINCT telegram_id FROM reseller_inbounds")
    for (tg,) in rows:
        async with aiosqlite.connect("data.db") as db:
            ibs = await db.execute_fetchall("SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=?", (tg,))
        inbound_ids = [r[0] for r in ibs]
        _, details = await build_report(inbound_ids)

        async with aiosqlite.connect("data.db") as db:
            cursor = await db.execute("SELECT last_json FROM last_reports WHERE telegram_id=?", (tg,))
            row = await cursor.fetchone()
            last = json.loads(row[0]) if row and row[0] else {"expiring": [], "expired": [], "up": 0, "down": 0}

        new_expiring = [u for u in details["expiring"] if u not in last["expiring"]]
        new_expired = [u for u in details["expired"] if u not in last["expired"]]

        if new_expiring or new_expired:
            msg = (f"📦 Used Traffic: {hb(details['up'] + details['down'])} "
                   f"(⬇️ {hb(details['down'])} + ⬆️ {hb(details['up'])})\n")
            msg += "📢 Changes detected:\n"
            if new_expiring:
                msg += "⏳ Newly Expiring (&lt;24h or &lt;1GB):\n" + "\n".join(new_expiring) + "\n"
            if new_expired:
                msg += "🚫 Newly Expired:\n" + "\n".join(new_expired)
            try:
                await bot.send_message(tg, safe_text(msg))
            except Exception as e:
                log_error(e)

        async with aiosqlite.connect("data.db") as db:
            await db.execute("INSERT OR REPLACE INTO last_reports VALUES (?, ?, ?)",
                             (tg, json.dumps(details), int(time.time())))
            await db.commit()

    # Superadmins (diff)
    data = api.inbounds()
    if isinstance(data, list):
        all_ids = [ib.get("id") for ib in data if isinstance(ib, dict)]
        _, details = await build_report(all_ids)
        for tg in SUPERADMINS:
            async with aiosqlite.connect("data.db") as db:
                cursor = await db.execute("SELECT last_json FROM last_reports WHERE telegram_id=?", (tg,))
                row = await cursor.fetchone()
                last = json.loads(row[0]) if row and row[0] else {"expiring": [], "expired": [], "up": 0, "down": 0}

            new_expiring = [u for u in details["expiring"] if u not in last["expiring"]]
            new_expired = [u for u in details["expired"] if u not in last["expired"]]

            if new_expiring or new_expired:
                msg = (f"📦 Used Traffic: {hb(details['up'] + details['down'])} "
                       f"(⬇️ {hb(details['down'])} + ⬆️ {hb(details['up'])})\n")
                msg += "📢 SuperAdmin - Panel Changes:\n"
                if new_expiring:
                    msg += "⏳ Newly Expiring:\n" + "\n".join(new_expiring) + "\n"
                if new_expired:
                    msg += "🚫 Newly Expired:\n" + "\n".join(new_expired)
                try:
                    await bot.send_message(tg, safe_text(msg))
                except Exception as e:
                    log_error(e)

            async with aiosqlite.connect("data.db") as db:
                await db.execute("INSERT OR REPLACE INTO last_reports VALUES (?, ?, ?)",
                                 (tg, json.dumps(details), int(time.time())))
                await db.commit()

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