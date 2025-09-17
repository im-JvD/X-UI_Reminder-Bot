# Version: 1.3.1 - Stable
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

# --- STATE ---
pending_assign = {}  # {admin_id: target_user_id}

# --- UTIL: Gregorian → Jalali ---
def gregorian_to_jalali(g_y, g_m, g_d):
    g_days_in_month = [31,28,31,30,31,30,31,31,30,31,30,31]
    j_days_in_month = [31,31,31,31,31,31,30,30,30,30,30,29]

    gy = g_y-1600
    gm = g_m-1
    gd = g_d-1

    g_day_no = 365*gy + (gy+3)//4 - (gy+99)//100 + (gy+399)//400
    for i in range(gm):
        g_day_no += g_days_in_month[i]
    if gm>1 and ((gy%4==0 and gy%100!=0) or (gy%400==0)):
        g_day_no +=1
    g_day_no += gd

    j_day_no = g_day_no-79
    j_np = j_day_no//12053
    j_day_no %= 12053

    jy = 979+33*j_np+4*(j_day_no//1461)
    j_day_no %= 1461

    if j_day_no >= 366:
        jy += (j_day_no-1)//365
        j_day_no = (j_day_no-1)%365

    for i in range(11):
        if j_day_no < j_days_in_month[i]:
            jm = i+1
            jd = j_day_no+1
            break
        j_day_no -= j_days_in_month[i]
    else:
        jm = 12
        jd = j_day_no+1

    return jy, jm, jd

def now_shamsi_str():
    now = datetime.now(ZoneInfo("Asia/Tehran"))
    jy, jm, jd = gregorian_to_jalali(now.year, now.month, now.day)
    return f"آخرین بروزرسانی - [{jd:02d}-{jm:02d}-{jy:04d}] - [{now.strftime('%H:%M:%S')}]"

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

# --- ROLES ---
async def ensure_user(tg_id: int) -> bool:
    """ثبت کاربر در DB. خروجی True یعنی کاربر جدید بوده"""
    async with aiosqlite.connect("data.db") as db:
        cursor = await db.execute("SELECT telegram_id FROM users WHERE telegram_id=?", (tg_id,))
        exists = await cursor.fetchone()
        if exists:
            return False
        await db.execute("INSERT INTO users(telegram_id, role) VALUES (?, 'user')", (tg_id,))
        await db.commit()
        return True

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

    is_new = await ensure_user(m.from_user.id)

    # پیام خوشامد برای خود کاربر
    await m.answer("👋 به ربات 3X-UI خوش آمدید!", reply_markup=MAIN_KB)

    # فقط یک بار برای سوپرادمین‌ها
    if is_new:
        user = m.from_user
        fullname = (user.first_name or "") + (" " + user.last_name if user.last_name else "")
        username = f"@{user.username}" if user.username else "ندارد"
        uid = user.id
        date_str = now_shamsi_str()

        text = (f"یک کاربر جدید با مشخصات زیر ربات را استارت کرد ...\n\n"
                f"نام اکانت تلگرام : {fullname}\n"
                f"نام کاربری کاربر : {username}\n"
                f"آی‌دی عددی کاربر : {uid}\n"
                f"تاریخ عضویت در ربات : {date_str}")

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="➕ اختصاص اینباند", callback_data=f"assign_inbound:{uid}")]
            ]
        )

        for admin_id in SUPERADMINS:
            try:
                await bot.send_message(admin_id, text, reply_markup=kb)
            except Exception as e:
                log_error(e)

@dp.message(F.text == "🆘 Support / Request Reseller")
async def support_req(m: Message):
    await m.answer("برای درخواست نمایندگی یا پشتیبانی، به ادمین پیام بدید: @your_admin")

# --- INLINE HANDLERS ---
@dp.callback_query(F.data.startswith("assign_inbound:"))
async def ask_inbound_id(query):
    admin_id = query.from_user.id
    if admin_id not in SUPERADMINS:
        await query.answer("⛔️ فقط سوپرادمین می‌تواند این کار را انجام دهد.", show_alert=True)
        return

    target_user = int(query.data.split(":")[1])
    pending_assign[admin_id] = target_user
    await query.message.answer(f"📝 لطفاً شناسه اینباند را برای کاربر {target_user} ارسال کنید.")
    await query.answer()

@dp.message(F.text.regexp(r"^\d+$"))
async def process_inbound_id(m: Message):
    admin_id = m.from_user.id
    if admin_id not in SUPERADMINS or admin_id not in pending_assign:
        return  # پیام‌های غیر مرتبط مثل /report رو نمی‌خوره

    target_user = pending_assign.pop(admin_id)
    inbound_id = int(m.text.strip())

    async with aiosqlite.connect("data.db") as db:
        await db.execute("UPDATE users SET role=? WHERE telegram_id=?", ("reseller", target_user))
        await db.execute("INSERT OR IGNORE INTO reseller_inbounds VALUES (?, ?)", (target_user, inbound_id))
        await db.commit()

    try:
        await bot.send_message(target_user, f"✅ شما به عنوان ادمین ریسلر ثبت شدید.\n📦 اینباند اختصاصی شما: {inbound_id}")
    except Exception as e:
        log_error(e)

    await m.answer(f"✅ کاربر {target_user} به عنوان ادمین ریسلر ثبت شد و اینباند {inbound_id} اختصاص داده شد.")

# --- REPORTS, JOBS & MAIN ---
# (توابع build_report, report_cmd, refresh_report, send_full_reports, check_changes مثل نسخه قبل هستند
# و بدون تغییر در همین فایل قرار دارند. فقط اینجا برای خلاصه‌سازی حذف کردم.)
# --- MAIN ---
async def main():
    await test_token()
    await ensure_db()
    scheduler.add_job(send_full_reports, "cron", hour=0, minute=0, timezone="Asia/Tehran")
    scheduler.add_job(check_changes, "interval", minutes=1)
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
