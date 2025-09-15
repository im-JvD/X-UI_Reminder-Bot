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

# --- HELPERS ---
def safe_text(text: str, limit: int = 4000) -> str:
    """Ensure text length does not exceed Telegram's limit."""
    if len(text) > limit:
        return text[:limit] + "\n... [truncated]"
    return text

# --- REPORT BUILDER ---
async def build_report(inbound_ids):
    try:
        data = api.inbounds()
        if not isinstance(data, list):
            return safe_text(f"❌ Invalid response from panel: {data}")

        online_emails = set(api.online_clients() or [])
        total_users = total_up = total_down = expiring = expired = online_count = low_traffic = 0

        for ib in data:
            if not isinstance(ib, dict):
                continue
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

        report = (f"📊 Report:\n"
                  f"👥 Users: {total_users}\n"
                  f"⬇️ Download: {hb(total_down)}\n"
                  f"⬆️ Upload: {hb(total_up)}\n"
                  f"🟢 Online: {online_count}\n"
                  f"⏳ Expiring (<24h): {expiring}\n"
                  f"🚫 Expired: {expired}\n"
                  f"⚠️ Low traffic (<1GB): {low_traffic}")
        return safe_text(report)
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
    if not isinstance(data, list):
        await m.answer(safe_text(f"❌ Unexpected response from panel:\n{data}"))
        return

    all_ids = [ib.get("id") for ib in data if isinstance(ib, dict)]
    report = await build_report(all_ids)
    await m.answer("📢 Full Panel Report:\n" + safe_text(report))

@dp.message(F.text == "📊 My Inbounds Report")
async def my_report(m: Message):
    async with aiosqlite.connect("data.db") as db:
        rows = await db.execute_fetchall("SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=?", (m.from_user.id,))
    if not rows:
        await m.answer("No inbound assigned to you.")
        return
    report = await build_report([r[0] for r in rows])
    await m.answer(safe_text(report))

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
                await bot.send_message(tg, "⏱ 10-min report:\n" + safe_text(rep))
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
