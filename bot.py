# Version: 1.4.0 - Stable (HTML reports enabled)
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

# --- CORE ---
bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
api = PanelAPI(os.getenv("PANEL_USERNAME"), os.getenv("PANEL_PASSWORD"))
dp = Dispatcher()
scheduler = AsyncIOScheduler()

MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🆘 Support / Request Reseller")]],
    resize_keyboard=True
)

# --- STATE ---
pending_assign: dict[int, int] = {}

# --- UTIL ---
def gregorian_to_jalali(g_y, g_m, g_d):
    g_days_in_month = [31,28,31,30,31,30,31,31,30,31,30,31]
    j_days_in_month = [31,31,31,31,31,31,30,30,30,30,30,29]
    gy = g_y - 1600; gm = g_m - 1; gd = g_d - 1
    g_day_no = 365*gy + (gy+3)//4 - (gy+99)//100 + (gy+399)//400
    for i in range(gm): g_day_no += g_days_in_month[i]
    if gm>1 and ((gy%4==0 and gy%100!=0) or (gy%400==0)): g_day_no += 1
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

def safe_text(s: str):
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

# --- TOKEN TEST ---
async def test_token():
    me = await bot.get_me()
    print(f"DEBUG: Bot connected as @{me.username}")
    print(f"DEBUG: SUPERADMINS loaded: {SUPERADMINS}")

# --- START ---
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

    await m.answer("👋 به ربات 3X-UI خوش آمدید!", reply_markup=MAIN_KB)

    if is_new:
        user = m.from_user
        fullname = safe_text((user.first_name or "") + (" " + user.last_name if user.last_name else ""))
        username = safe_text(f"@{user.username}") if user.username else "ندارد"
        uid = user.id
        date_str = now_shamsi_str()
        txt = (f"<b>یک کاربر جدید با مشخصات زیر ربات را استارت کرد ...</b>\n\n"
               f"نام اکانت تلگرام : {fullname}\n"
               f"نام کاربری کاربر : {username}\n"
               f"آی‌دی عددی کاربر : <code>{uid}</code>\n"
               f"تاریخ عضویت در ربات : {date_str}")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ اختصاص اینباند", callback_data=f"assign_inbound:{uid}")]
        ])
        for admin_id in SUPERADMINS:
            try:
                await bot.send_message(admin_id, txt, reply_markup=kb)
            except Exception as e:
                log_error(e)

# --- SUPPORT ---
@dp.message(F.text == "🆘 Support / Request Reseller")
async def support_req(m: Message):
    await m.answer("برای درخواست نمایندگی یا پشتیبانی، به ادمین پیام بدید: @your_admin")

# --- ASSIGN INBOUND ---
@dp.callback_query(F.data.startswith("assign_inbound:"))
async def ask_inbound_id(query):
    admin_id = query.from_user.id
    if admin_id not in SUPERADMINS:
        await query.answer("⛔️ فقط سوپرادمین می‌تواند این کار را انجام دهد.", show_alert=True)
        return
    target_user = int(query.data.split(":")[1])
    pending_assign[admin_id] = target_user
    await query.message.answer(f"📝 لطفاً شناسه اینباند را برای کاربر {target_user} ارسال کنید (فقط عدد).")
    await query.answer()

@dp.message(F.text.regexp(r"^\d+$"))
async def process_inbound_id(m: Message):
    admin_id = m.from_user.id
    if admin_id not in SUPERADMINS or admin_id not in pending_assign:
        return
    target_user = pending_assign.pop(admin_id)
    inbound_id = int(m.text.strip())
    async with aiosqlite.connect("data.db") as db:
        await db.execute("UPDATE users SET role=? WHERE telegram_id=?", ("reseller", target_user))
        await db.execute("INSERT OR IGNORE INTO reseller_inbounds VALUES (?, ?)", (target_user, inbound_id))
        await db.commit()
    await m.answer(f"✅ کاربر {target_user} به عنوان ادمین ریسلر ثبت شد و اینباند {inbound_id} اختصاص داده شد.")
    try:
        await bot.send_message(target_user, f"✅ شما به عنوان ادمین ریسلر ثبت شدید.\n📦 اینباند اختصاصی شما: {inbound_id}")
    except Exception as e:
        log_error(e)

# --- REPORTS ---
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
        stats["up"] += up; stats["down"] += down
        if c.get("email") in online_emails: stats["online"] += 1
        quota = int(c.get("total", 0) or c.get("totalGB", 0))
        used = up + down
        left = quota - used if quota > 0 else None
        exp = int(c.get("expiryTime", 0) or c.get("expire", 0))
        rem = (exp/1000) - time.time() if exp > 0 else None
        if (rem is not None and rem <= 0) or (left is not None and left <= 0):
            stats["expired"].append(c.get("email", "unknown"))
        elif (left is not None and left <= 1024**3) or (rem is not None and 0 < rem <= 24*3600):
            stats["expiring"].append(c.get("email", "unknown"))
    return stats

async def build_report(inbound_ids: list[int]):
    try:
        data = api.inbounds()
        if not isinstance(data, list):
            return "❌ Invalid response from panel.", {"expiring": [], "expired": [], "up": 0, "down": 0}
        online_emails = set(api.online_clients() or [])
        total_users = total_up = total_down = online_count = 0
        expiring, expired = [], []
        for ib in data:
            if not isinstance(ib, dict) or ib.get("id") not in inbound_ids: continue
            s = analyze_inbound(ib, online_emails)
            total_users += s["users"]; total_up += s["up"]; total_down += s["down"]
            online_count += s["online"]; expiring.extend(s["expiring"]); expired.extend(s["expired"])
        report = (f"📊 <b>گزارش مربوط به اینباند شما :</b>\n\n"
                  f"👥 <b>تعداد کاربران </b>: [ {total_users} ]\n"
                  f"🟢 <b>کاربران آنلاین </b>: [ {online_count} ]\n"
                  f"⏳ <b>کاربران در حال انقضا (&lt;24h)</b>: [ {len(expiring)} ]\n"
                  f"🚫 <b>کاربران منقضی شده </b>: [ {len(expired)} ]")
        return report, {"expiring": expiring, "expired": expired, "up": total_up, "down": total_down}
    except Exception as e:
        log_error(e)
        return "❌ Error while generating report.", {"expiring": [], "expired": [], "up": 0, "down": 0}

@dp.message(Command("report"))
async def report_cmd(m: Message):
    if m.from_user.id in SUPERADMINS:
        data = api.inbounds()
        all_ids = [ib.get("id") for ib in data if isinstance(ib, dict)]
        report, _ = await build_report(all_ids)
    else:
        async with aiosqlite.connect("data.db") as db:
            rows = await db.execute_fetchall("SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=?", (m.from_user.id,))
        if not rows:
            await m.answer("❌ هیچ اینباندی به شما اختصاص داده نشده.")
            return
        inbound_ids = [r[0] for r in rows]
        report, _ = await build_report(inbound_ids)
    report += f"\n\n{now_shamsi_str()}"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 بروزرسانی وضعیت", callback_data="refresh_report")]])
    await m.answer(report, reply_markup=kb)

@dp.callback_query(F.data == "refresh_report")
async def refresh_report(query):
    user_id = query.from_user.id
    if user_id in SUPERADMINS:
        data = api.inbounds()
        all_ids = [ib.get("id") for ib in data if isinstance(ib, dict)]
        report, _ = await build_report(all_ids)
    else:
        async with aiosqlite.connect("data.db") as db:
            rows = await db.execute_fetchall("SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=?", (user_id,))
        if not rows:
            await query.message.edit_text("❌ هیچ اینباندی به شما اختصاص داده نشده.")
            await query.answer(); return
        inbound_ids = [r[0] for r in rows]
        report, _ = await build_report(inbound_ids)
    report += f"\n\n{now_shamsi_str()}"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 بروزرسانی وضعیت", callback_data="refresh_report")]])
    try:
        await query.message.edit_text(report, reply_markup=kb)
        await query.answer("✅ گزارش بروزرسانی شد", show_alert=False)
    except Exception as e:
        log_error(e)
        await query.answer("ℹ️ تغییری نسبت به گزارش قبلی نبود.", show_alert=False)

# --- JOBS ---
async def send_full_reports():
    async with aiosqlite.connect("data.db") as db:
        rows = await db.execute_fetchall("SELECT DISTINCT telegram_id FROM reseller_inbounds")
    for (tg,) in rows:
        async with aiosqlite.connect("data.db") as db:
            ibs = await db.execute_fetchall("SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=?", (tg,))
        inbound_ids = [r[0] for r in ibs]
        report, details = await build_report(inbound_ids)
        report += f"\n\n{now_shamsi_str()}"
        try: await bot.send_message(tg, "📢 Daily Full Report:\n" + report)
        except Exception as e: log_error(e)
        async with aiosqlite.connect("data.db") as db:
            await db.execute("INSERT OR REPLACE INTO last_reports VALUES (?, ?, ?)", (tg, json.dumps(details), int(time.time())))
            await db.commit()
    data = api.inbounds()
    if isinstance(data, list):
        all_ids = [ib.get("id") for ib in data if isinstance(ib, dict)]
        report, details = await build_report(all_ids)
        report += f"\n\n{now_shamsi_str()}"
        for tg in SUPERADMINS:
            try: await bot.send_message(tg, "📢 Daily Full Panel Report:\n" + report)
            except Exception as e: log_error(e)
            async with aiosqlite.connect("data.db") as db:
                await db.execute("INSERT OR REPLACE INTO last_reports VALUES (?, ?, ?)", (tg, json.dumps(details), int(time.time())))
                await db.commit()

# --- MAIN ---
async def main():
    await ensure_db(); await test_token()
    scheduler.add_job(send_full_reports, "cron", hour=0, minute=0, timezone="Asia/Tehran")
    scheduler.add_job(check_changes, "interval", minutes=1)
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
