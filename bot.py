# Version: 1.0.0 - Stable
import os, asyncio, aiosqlite, time, traceback, json
import jdatetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
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
        log_error(e)
        raise

# --- UTILS ---
def hb(n):
    try:
        n = int(n)
    except Exception:
        return "0B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n //= 1024
        i += 1
    return f"{n}{units[i]}"

def safe_text(s: str) -> str:
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;"))

# --- ROLES ---
async def is_superadmin(tg_id: int) -> bool:
    return tg_id in SUPERADMINS

async def ensure_user(tg_id: int):
    async with aiosqlite.connect("data.db") as db:
        await db.execute("INSERT OR IGNORE INTO users(telegram_id, role) VALUES (?, 'user')", (tg_id,))
        await db.commit()

# --- COMMANDS ---
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

    await ensure_user(m.from_user.id)
    await m.answer("Welcome to 3X-UI Report Bot 👋", reply_markup=MAIN_KB)

@dp.message(F.text == "🆘 Support / Request Reseller")
async def support_req(m: Message):
    await m.answer("برای درخواست نمایندگی یا پشتیبانی، به ادمین پیام بدید: @your_admin")

# --- ANALYSIS ---
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
        up, down = int(c.get("up", 0)), int(c.get("down", 0))
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
                  f"🟢 Online: {online_count}\n"
                  f"⏳ Expiring (&lt;24h): {len(expiring)}\n"
                  f"🚫 Expired: {len(expired)}")
        return safe_text(report), {"expiring": expiring, "expired": expired, "up": total_up, "down": total_down}
    except Exception as e:
        log_error(e)
        return "❌ Error while generating report. Check log.txt", {"expiring": [], "expired": [], "up": 0, "down": 0}

# --- /report COMMAND ---
@dp.message(Command("report"))
async def report_cmd(m: Message):
    async with aiosqlite.connect("data.db") as db:
        rows = await db.execute_fetchall("SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=?", (m.from_user.id,))
    if not rows and m.from_user.id not in SUPERADMINS:
        await m.answer("❌ هیچ اینباندی به شما اختصاص داده نشده.")
        return

    if m.from_user.id in SUPERADMINS:
        data = api.inbounds()
        all_ids = [ib.get("id") for ib in data if isinstance(ib, dict)]
        report, _ = await build_report(all_ids)
    else:
        inbound_ids = [r[0] for r in rows]
        report, _ = await build_report(inbound_ids)

    # افزودن تاریخ شمسی
    report += f"\n\n⏱ آخرین بروزرسانی: {jdatetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 بروزرسانی وضعیت", callback_data="refresh_report")]
        ]
    )
    await m.answer(report, reply_markup=kb)

@dp.callback_query(F.data == "refresh_report")
async def refresh_report(query):
    user_id = query.from_user.id
    async with aiosqlite.connect("data.db") as db:
        rows = await db.execute_fetchall("SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=?", (user_id,))
    if not rows and user_id not in SUPERADMINS:
        await query.message.edit_text("❌ هیچ اینباندی به شما اختصاص داده نشده.")
        return

    if user_id in SUPERADMINS:
        data = api.inbounds()
        all_ids = [ib.get("id") for ib in data if isinstance(ib, dict)]
        report, _ = await build_report(all_ids)
    else:
        inbound_ids = [r[0] for r in rows]
        report, _ = await build_report(inbound_ids)

    # افزودن تاریخ شمسی
    report += f"\n\n⏱ آخرین بروزرسانی: {jdatetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 بروزرسانی وضعیت", callback_data="refresh_report")]
        ]
    )
    await query.message.edit_text(report, reply_markup=kb)
    await query.answer("✅ گزارش بروزرسانی شد", show_alert=False)

# --- JOBS ---
async def send_full_reports():
    async with aiosqlite.connect("data.db") as db:
        rows = await db.execute_fetchall("SELECT DISTINCT telegram_id FROM reseller_inbounds")
    for (tg,) in rows:
        async with aiosqlite.connect("data.db") as db:
            ibs = await db.execute_fetchall("SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=?", (tg,))
        inbound_ids = [r[0] for r in ibs]
        report, details = await build_report(inbound_ids)
        # افزودن تاریخ شمسی
        report += f"\n\n⏱ آخرین بروزرسانی: {jdatetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        try:
            await bot.send_message(tg, "📢 Daily Full Report:\n" + report)
        except Exception as e:
            log_error(e)
        async with aiosqlite.connect("data.db") as db:
            await db.execute("INSERT OR REPLACE INTO last_reports VALUES (?, ?, ?)",
                             (tg, json.dumps(details), int(time.time())))
            await db.commit()

    data = api.inbounds()
    if isinstance(data, list):
        all_ids = [ib.get("id") for ib in data if isinstance(ib, dict)]
        report, details = await build_report(all_ids)
        report += f"\n\n⏱ آخرین بروزرسانی: {jdatetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        for tg in SUPERADMINS:
            try:
                await bot.send_message(tg, "📢 Daily Full Panel Report:\n" + report)
                async with aiosqlite.connect("data.db") as db:
                    await db.execute("INSERT OR REPLACE INTO last_reports VALUES (?, ?, ?)",
                                     (tg, json.dumps(details), int(time.time())))
                    await db.commit()
            except Exception as e:
                log_error(e)

async def check_changes():
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
            msg = "📢 Changes detected:\n"
            if new_expiring:
                msg += "⏳ Newly Expiring (&lt;24h):\n" + "\n".join(new_expiring) + "\n"
            if new_expired:
                msg += "🚫 Newly Expired:\n" + "\n".join(new_expired)
            msg += f"\n\n⏱ آخرین بروزرسانی: {jdatetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            try:
                await bot.send_message(tg, safe_text(msg))
            except Exception as e:
                log_error(e)

        async with aiosqlite.connect("data.db") as db:
            await db.execute("INSERT OR REPLACE INTO last_reports VALUES (?, ?, ?)",
                             (tg, json.dumps(details), int(time.time())))
            await db.commit()

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
                msg = "📢 SuperAdmin - Panel Changes:\n"
                if new_expiring:
                    msg += "⏳ Newly Expiring:\n" + "\n".join(new_expiring) + "\n"
                if new_expired:
                    msg += "🚫 Newly Expired:\n" + "\n".join(new_expired)
                msg += f"\n\n⏱ آخرین بروزرسانی: {jdatetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
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
    scheduler.add_job(check_changes, "interval", minutes=1)
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
