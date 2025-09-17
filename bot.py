# Version: 1.3.7 - Debug NewUser Notify
import os, asyncio, aiosqlite, time, traceback, json
from datetime import datetime
from zoneinfo import ZoneInfo
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
    try:
        with open("log.txt", "a") as f:
            f.write(f"[{time.ctime()}] {traceback.format_exc()}\n")
    except Exception:
        pass

BOT_TOKEN = os.getenv("BOT_TOKEN")
REQUIRED_CHANNEL_ID = os.getenv("REQUIRED_CHANNEL_ID")
SUPERADMINS = {int(x) for x in os.getenv("SUPERADMINS", "").split(",") if x.strip()}

# --- CORE OBJECTS ---
bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
api = PanelAPI(os.getenv("PANEL_USERNAME"), os.getenv("PANEL_PASSWORD"))
dp = Dispatcher()
scheduler = AsyncIOScheduler()

MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🆘 Support / Request Reseller")]],
    resize_keyboard=True
)

pending_assign: dict[int, int] = {}

# --- UTIL: Gregorian → Jalali ---
def gregorian_to_jalali(g_y, g_m, g_d):
    g_days_in_month = [31,28,31,30,31,30,31,31,30,31,30,31]
    j_days_in_month = [31,31,31,31,31,31,30,30,30,30,30,29]
    gy = g_y - 1600; gm = g_m - 1; gd = g_d - 1
    g_day_no = 365*gy + (gy+3)//4 - (gy+99)//100 + (gy+399)//400
    for i in range(gm): g_day_no += g_days_in_month[i]
    if gm>1 and ((gy%4==0 and gy%100!=0) or (gy%400==0)): g_day_no +=1
    g_day_no += gd
    j_day_no = g_day_no - 79
    j_np = j_day_no // 12053; j_day_no %= 12053
    jy = 979 + 33*j_np + 4*(j_day_no // 1461); j_day_no %= 1461
    if j_day_no >= 366: jy += (j_day_no-1)//365; j_day_no = (j_day_no-1)%365
    for i in range(11):
        if j_day_no < j_days_in_month[i]:
            jm = i+1; jd = j_day_no+1; break
        j_day_no -= j_days_in_month[i]
    else: jm = 12; jd = j_day_no+1
    return jy, jm, jd

def now_shamsi_str():
    now = datetime.now(ZoneInfo("Asia/Tehran"))
    jy, jm, jd = gregorian_to_jalali(now.year, now.month, now.day)
    return f"آخرین بروزرسانی - [{jd:02d}-{jm:02d}-{jy:04d}] - [{now.strftime('%H:%M:%S')}]"

def safe_text(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

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

async def ensure_user_and_check_new(tg_id: int) -> bool:
    async with aiosqlite.connect("data.db") as db:
        cur = await db.execute("SELECT 1 FROM users WHERE telegram_id=?", (tg_id,))
        row = await cur.fetchone()
        if row:
            return False
        await db.execute("INSERT INTO users(telegram_id, role) VALUES (?, 'user')", (tg_id,))
        await db.commit()
        return True

# --- COMMANDS ---
@dp.message(Command("start"))
async def start(m: Message):
    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL_ID, m.from_user.id)
        is_member = member.status in ("member", "administrator", "creator")
    except Exception:
        is_member = False
    if not is_member:
        await m.answer(f"برای استفاده از ربات ابتدا باید عضو کانال {REQUIRED_CHANNEL_ID} شوید.")

    is_new = await ensure_user_and_check_new(m.from_user.id)

    print(f"DEBUG START: user_id={m.from_user.id}, is_new={is_new}, SUPERADMINS={SUPERADMINS}")

    await m.answer("👋 به ربات 3X-UI خوش آمدید!", reply_markup=MAIN_KB)

    if is_new:
        user = m.from_user
        fullname = (user.first_name or "") + (" " + user.last_name if user.last_name else "")
        username = f"@{user.username}" if user.username else "ندارد"
        uid = user.id
        date_str = now_shamsi_str()
        txt = (f"یک کاربر جدید با مشخصات زیر ربات را استارت کرد ...\n\n"
               f"نام اکانت تلگرام : {fullname}\n"
               f"نام کاربری کاربر : {username}\n"
               f"آی‌دی عددی کاربر : {uid}\n"
               f"تاریخ عضویت در ربات : {date_str}")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ اختصاص اینباند", callback_data=f"assign_inbound:{uid}")]
        ])
        for admin_id in SUPERADMINS:
            try:
                print(f"DEBUG: sending new user info to superadmin {admin_id}")
                await bot.send_message(admin_id, txt, reply_markup=kb)
            except Exception as e:
                print(f"DEBUG: failed sending to {admin_id} error={e}")
                log_error(e)

# (باقی کد: assign inbound, report, jobs, main همون نسخه 1.3.6 هست بدون تغییر)
# ...

async def main():
    await ensure_db()
    await test_token()
    scheduler.add_job(send_full_reports, "cron", hour=0, minute=0, timezone="Asia/Tehran")
    scheduler.add_job(check_changes, "interval", minutes=1)
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())