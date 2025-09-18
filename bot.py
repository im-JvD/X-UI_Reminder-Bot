# Version: 1.4.0
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
        with open("log.txt", "a", encoding="utf-8") as f:
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
pending_assign: dict[int, int] = {}  # {admin_id: target_user_id}

# --- UTIL: Gregorian → Jalali & helpers ---
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

# --- COMMANDS ---
@dp.message(Command("start"))
async def start(m: Message):
    # Check membership (inform user, but do not block notifying superadmins)
    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL_ID, m.from_user.id)
        is_member = member.status in ("member", "administrator", "creator")
    except Exception:
        is_member = False
    if not is_member:
        await m.answer(f"برای استفاده از ربات ابتدا باید عضو کانال {REQUIRED_CHANNEL_ID} شوید.")

    is_new = await ensure_user_and_check_new(m.from_user.id)
    print(f"DEBUG START: user_id={m.from_user.id}, is_new={is_new}, SUPERADMINS={SUPERADMINS}")

    # Welcome message
    await m.answer("👋 به ربات گزارش‌دهی X-UI خوش‌آمدید .", reply_markup=MAIN_KB)

    # Notify superadmins only once (when user is really new)
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
                # safe_text to avoid HTML parse issues in arbitrary names/usernames
                await bot.send_message(admin_id, safe_text(txt), reply_markup=kb)
            except Exception as e:
                log_error(e)

@dp.message(F.text == "🆘 Support / Request Reseller")
async def support_req(m: Message):
    await m.answer("برای درخواست نمایندگی یا پشتیبانی، به ادمین پیام بدید: @your_admin")

# --- INLINE HANDLERS (Assign Inbound) ---
@dp.callback_query(F.data.startswith("assign_inbound:"))
async def ask_inbound_id(query):
    admin_id = query.from_user.id
    if admin_id not in SUPERADMINS:
        await query.answer("⛔️ فقط سوپرادمین می‌تواند این کار را انجام دهد.", show_alert=True)
        return
    try:
        target_user = int(query.data.split(":")[1])
    except Exception:
        await query.answer("داده نامعتبر.", show_alert=True)
        return
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
        await db.execute("INSERT OR IGNORE INTO reseller_inbounds(telegram_id, inbound_id) VALUES (?, ?)", (target_user, inbound_id))
        await db.commit()
    await m.answer(f"✅ کاربر {target_user} به عنوان ادمین فروشنده ثبت شد و اینباند {inbound_id} به او اختصاص داده شد .")
    try:
        await bot.send_message(target_user, f"✅ شما به عنوان ادمین ریسلر ثبت شدید.\n📦 اینباند اختصاصی شما: {inbound_id}")
    except Exception as e:
        log_error(e)

# --- REPORTS ---
def analyze_inbound(ib, online_emails):
    stats = {"users": 0, "up": 0, "down": 0, "online": 0, "expiring": [], "expired": []}
    if not isinstance(ib, dict):
        return stats

def _collect_emails_for_inbounds(inbound_ids: list[int]) -> list[str]:
    emails = []
    try:
        data = api.inbounds()
        if not isinstance(data, list):
            return emails
        for ib in data:
            if not isinstance(ib, dict) or ib.get("id") not in inbound_ids:
                continue
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
                em = c.get("email")
                if em:
                    emails.append(em)
    except Exception as e:
        log_error(e)
    return emails

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

async def build_report(inbound_ids: list[int]):
    """
    Build the admin/reseller report in the requested Farsi format with bold tags.
    NOTE: We do NOT escape the final string with safe_text because we intentionally include HTML (<b>).
    """
    try:
        data = api.inbounds()
        if not isinstance(data, list):
            # This message has no HTML tags, so safe_text is fine here.
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
        # New Farsi + bold formatted report
        report = (
            "📊 <b>گزارش نهایی از وضعیت فعلی پنل شما : </b>\n\n"
            f"👥 <b>تعداد کل کاربران شما :</b> [ {total_users} ] \n"
            f"🟢 <b>تعداد کاربران آنلاین :</b> [ {online_count} ] \n"
            f"⏳ <b>کاربرانی که بزودی منقضی خواهند شد :</b> [ {len(expiring)} ] \n"
            f"🚫 <b>کاربرانی که منقضی شده‌اند :</b> [ {len(expired)} ]"
        )
        return report, {"expiring": expiring, "expired": expired, "up": total_up, "down": total_down}
    except Exception as e:
        log_error(e)
        return "❌ Error while generating report. Check log.txt", {"expiring": [], "expired": [], "up": 0, "down": 0}

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
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 بروزرسانی وضعیت", callback_data="refresh_report")]
    ])
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
            await query.answer()
            return
        inbound_ids = [r[0] for r in rows]
        report, _ = await build_report(inbound_ids)

    report += f"\n\n{now_shamsi_str()}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 بروزرسانی وضعیت", callback_data="refresh_report")]
    ])
    try:
        await query.message.edit_text(report, reply_markup=kb)
        await query.answer("✅ گزارش بروزرسانی شد", show_alert=False)
    except Exception as e:
        log_error(e)
        await query.answer("ℹ️ تغییری نسبت به گزارش قبلی نبود.", show_alert=False)


# --- EXTRA COMMANDS ---
@dp.message(Command("online"))
async def online_cmd(m: Message):
    if m.from_user.id in SUPERADMINS:
        data = api.inbounds()
        all_ids = [ib.get("id") for ib in data if isinstance(ib, dict)]
        _, details = await build_report(all_ids)
        online = set(api.online_clients() or [])
    else:
        async with aiosqlite.connect("data.db") as db:
            rows = await db.execute_fetchall("SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=?", (m.from_user.id,))
        if not rows:
            await m.answer("❌ هیچ اینباندی به شما اختصاص داده نشده.")
            return
        inbound_ids = [r[0] for r in rows]
        _, details = await build_report(inbound_ids)
        online = set(api.online_clients() or [])
    msg = "🟢 کاربران آنلاین:\n\n"
    if online:
        msg += "\n".join(online)
    else:
        msg += "هیچ کاربری آنلاین نیست."
    msg = f"👥 تعداد: {len(online)}\n\n" + msg
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 بروزرسانی وضعیت", callback_data="refresh_online")]
    ])
    await m.answer(msg, reply_markup=kb)

@dp.callback_query(F.data == "refresh_online")
async def refresh_online(query):
    user_id = query.from_user.id
    if user_id in SUPERADMINS:
        data = api.inbounds()
        all_ids = [ib.get("id") for ib in data if isinstance(ib, dict)]
        _, details = await build_report(all_ids)
        online = set(api.online_clients() or [])
    else:
        async with aiosqlite.connect("data.db") as db:
            rows = await db.execute_fetchall("SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=?", (user_id,))
        if not rows:
            await query.message.edit_text("❌ هیچ اینباندی به شما اختصاص داده نشده.")
            await query.answer()
            return
        inbound_ids = [r[0] for r in rows]
        _, details = await build_report(inbound_ids)
        online = set(api.online_clients() or [])
    msg = "🟢 کاربران آنلاین:\n\n"
    if online:
        msg += "\n".join(online)
    else:
        msg += "هیچ کاربری آنلاین نیست."
    msg = f"👥 تعداد: {len(online)}\n\n" + msg
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 بروزرسانی وضعیت", callback_data="refresh_online")]
    ])
    try:
        await query.message.edit_text(msg, reply_markup=kb)
        await query.answer("✅ بروزرسانی شد", show_alert=False)
    except Exception as e:
        log_error(e)
        await query.answer("ℹ️ تغییری نسبت به گزارش قبلی نبود.", show_alert=False)


@dp.message(Command("expiring"))
async def expiring_cmd(m: Message):
    if m.from_user.id in SUPERADMINS:
        data = api.inbounds()
        all_ids = [ib.get("id") for ib in data if isinstance(ib, dict)]
        _, details = await build_report(all_ids)
        expiring = details.get("expiring", [])
    else:
        async with aiosqlite.connect("data.db") as db:
            rows = await db.execute_fetchall("SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=?", (m.from_user.id,))
        if not rows:
            await m.answer("❌ هیچ اینباندی به شما اختصاص داده نشده.")
            return
        inbound_ids = [r[0] for r in rows]
        _, details = await build_report(inbound_ids)
        expiring = details.get("expiring", [])
    msg = "⏳ کاربران رو به انقضا:\n\n"
    if expiring:
        msg += "\n".join(expiring)
    else:
        msg += "هیچ کاربری در حال انقضا نیست."
    msg = f"👥 تعداد: {len(expiring)}\n\n" + msg
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 بروزرسانی وضعیت", callback_data="refresh_expiring")]
    ])
    await m.answer(msg, reply_markup=kb)

@dp.callback_query(F.data == "refresh_expiring")
async def refresh_expiring(query):
    user_id = query.from_user.id
    if user_id in SUPERADMINS:
        data = api.inbounds()
        all_ids = [ib.get("id") for ib in data if isinstance(ib, dict)]
        _, details = await build_report(all_ids)
        expiring = details.get("expiring", [])
    else:
        async with aiosqlite.connect("data.db") as db:
            rows = await db.execute_fetchall("SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=?", (user_id,))
        if not rows:
            await query.message.edit_text("❌ هیچ اینباندی به شما اختصاص داده نشده.")
            await query.answer()
            return
        inbound_ids = [r[0] for r in rows]
        _, details = await build_report(inbound_ids)
        expiring = details.get("expiring", [])
    msg = "⏳ کاربران رو به انقضا:\n\n"
    if expiring:
        msg += "\n".join(expiring)
    else:
        msg += "هیچ کاربری در حال انقضا نیست."
    msg = f"👥 تعداد: {len(expiring)}\n\n" + msg
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 بروزرسانی وضعیت", callback_data="refresh_expiring")]
    ])
    try:
        await query.message.edit_text(msg, reply_markup=kb)
        await query.answer("✅ بروزرسانی شد", show_alert=False)
    except Exception as e:
        log_error(e)
        await query.answer("ℹ️ تغییری نسبت به گزارش قبلی نبود.", show_alert=False)


@dp.message(Command("expired"))
async def expired_cmd(m: Message):
    if m.from_user.id in SUPERADMINS:
        data = api.inbounds()
        all_ids = [ib.get("id") for ib in data if isinstance(ib, dict)]
        _, details = await build_report(all_ids)
        expired = details.get("expired", [])
    else:
        async with aiosqlite.connect("data.db") as db:
            rows = await db.execute_fetchall("SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=?", (m.from_user.id,))
        if not rows:
            await m.answer("❌ هیچ اینباندی به شما اختصاص داده نشده.")
            return
        inbound_ids = [r[0] for r in rows]
        _, details = await build_report(inbound_ids)
        expired = details.get("expired", [])
    msg = "🚫 کاربران منقضی شده:\n\n"
    if expired:
        msg += "\n".join(expired)
    else:
        msg += "هیچ کاربری منقضی نشده است."
    msg = f"👥 تعداد: {len(expired)}\n\n" + msg
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 بروزرسانی وضعیت", callback_data="refresh_expired")]
    ])
    await m.answer(msg, reply_markup=kb)

@dp.callback_query(F.data == "refresh_expired")
async def refresh_expired(query):
    user_id = query.from_user.id
    if user_id in SUPERADMINS:
        data = api.inbounds()
        all_ids = [ib.get("id") for ib in data if isinstance(ib, dict)]
        _, details = await build_report(all_ids)
        expired = details.get("expired", [])
    else:
        async with aiosqlite.connect("data.db") as db:
            rows = await db.execute_fetchall("SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=?", (user_id,))
        if not rows:
            await query.message.edit_text("❌ هیچ اینباندی به شما اختصاص داده نشده.")
            await query.answer()
            return
        inbound_ids = [r[0] for r in rows]
        _, details = await build_report(inbound_ids)
        expired = details.get("expired", [])
    msg = "🚫 کاربران منقضی شده:\n\n"
    if expired:
        msg += "\n".join(expired)
    else:
        msg += "هیچ کاربری منقضی نشده است."
    msg = f"👥 تعداد: {len(expired)}\n\n" + msg
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 بروزرسانی وضعیت", callback_data="refresh_expired")]
    ])
    try:
        await query.message.edit_text(msg, reply_markup=kb)
        await query.answer("✅ بروزرسانی شد", show_alert=False)
    except Exception as e:
        log_error(e)
        await query.answer("ℹ️ تغییری نسبت به گزارش قبلی نبود.", show_alert=False)

# --- EXTRA COMMANDS ---
@dp.message(Command("online"))
async def online_cmd(m: Message):
    if m.from_user.id in SUPERADMINS:
        data = api.inbounds()
        inbound_ids = [ib.get("id") for ib in data if isinstance(ib, dict)]
    else:
        async with aiosqlite.connect("data.db") as db:
            rows = await db.execute_fetchall("SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=?", (m.from_user.id,))
        if not rows:
            await m.answer("❌ هیچ اینباندی به شما اختصاص داده نشده.")
            return
        inbound_ids = [r[0] for r in rows]

    online_all = set(api.online_clients() or [])
    my_emails = set(_collect_emails_for_inbounds(inbound_ids))
    online = sorted(list(online_all & my_emails)) if m.from_user.id not in SUPERADMINS else sorted(list(online_all))

    msg = f"🟢 <b>تعداد کل کاربران آنلاین شما</b> [ {len(online)} ]\n\n"
    if online:
        msg += "\n".join([f"👤 - [ {safe_text(u)} ]" for u in online])
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="♻️ بروزرسانی به آخرین وضعیت", callback_data="refresh_online")]])
    await m.answer(msg, reply_markup=kb)

@dp.callback_query(F.data == "refresh_online")
async def refresh_online(query):
    user_id = query.from_user.id
    if user_id in SUPERADMINS:
        data = api.inbounds()
        inbound_ids = [ib.get("id") for ib in data if isinstance(ib, dict)]
    else:
        async with aiosqlite.connect("data.db") as db:
            rows = await db.execute_fetchall("SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=?", (user_id,))
        if not rows:
            await query.message.edit_text("❌ هیچ اینباندی به شما اختصاص داده نشده.")
            await query.answer()
            return
        inbound_ids = [r[0] for r in rows]

    online_all = set(api.online_clients() or [])
    my_emails = set(_collect_emails_for_inbounds(inbound_ids))
    online = sorted(list(online_all & my_emails)) if user_id not in SUPERADMINS else sorted(list(online_all))

    msg = f"🟢 <b>تعداد کل کاربران آنلاین شما</b> [ {len(online)} ]\n\n"
    if online:
        msg += "\n".join([f"👤 - [ {safe_text(u)} ]" for u in online])
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="♻️ بروزرسانی به آخرین وضعیت", callback_data="refresh_online")]])
    try:
        await query.message.edit_text(msg, reply_markup=kb)
        await query.answer("✅ بروزرسانی شد", show_alert=False)
    except Exception as e:
        log_error(e)
        await query.answer("ℹ️ تغییری نسبت به گزارش قبلی نبود.", show_alert=False)


@dp.message(Command("expiring"))
async def expiring_cmd(m: Message):
    if m.from_user.id in SUPERADMINS:
        data = api.inbounds()
        inbound_ids = [ib.get("id") for ib in data if isinstance(ib, dict)]
    else:
        async with aiosqlite.connect("data.db") as db:
            rows = await db.execute_fetchall("SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=?", (m.from_user.id,))
        if not rows:
            await m.answer("❌ هیچ اینباندی به شما اختصاص داده نشده.")
            return
        inbound_ids = [r[0] for r in rows]

    _, details = await build_report(inbound_ids)
    expiring = sorted(details.get("expiring", []))
    msg = f"🟢 <b>تعداد کل کاربران رو به انقضا شما</b> [ {len(expiring)} ]\n\n"
    if expiring:
        msg += "\n".join([f"👤 - [ {safe_text(u)} ]" for u in expiring])
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="♻️ بروزرسانی به آخرین وضعیت", callback_data="refresh_expiring")]])
    await m.answer(msg, reply_markup=kb)

@dp.callback_query(F.data == "refresh_expiring")
async def refresh_expiring(query):
    user_id = query.from_user.id
    if user_id in SUPERADMINS:
        data = api.inbounds()
        inbound_ids = [ib.get("id") for ib in data if isinstance(ib, dict)]
    else:
        async with aiosqlite.connect("data.db") as db:
            rows = await db.execute_fetchall("SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=?", (user_id,))
        if not rows:
            await query.message.edit_text("❌ هیچ اینباندی به شما اختصاص داده نشده.")
            await query.answer()
            return
        inbound_ids = [r[0] for r in rows]

    _, details = await build_report(inbound_ids)
    expiring = sorted(details.get("expiring", []))
    msg = f"🟢 <b>تعداد کل کاربران رو به انقضا شما</b> [ {len(expiring)} ]\n\n"
    if expiring:
        msg += "\n".join([f"👤 - [ {safe_text(u)} ]" for u in expiring])
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="♻️ بروزرسانی به آخرین وضعیت", callback_data="refresh_expiring")]])
    try:
        await query.message.edit_text(msg, reply_markup=kb)
        await query.answer("✅ بروزرسانی شد", show_alert=False)
    except Exception as e:
        log_error(e)
        await query.answer("ℹ️ تغییری نسبت به گزارش قبلی نبود.", show_alert=False)


@dp.message(Command("expired"))
async def expired_cmd(m: Message):
    if m.from_user.id in SUPERADMINS:
        data = api.inbounds()
        inbound_ids = [ib.get("id") for ib in data if isinstance(ib, dict)]
    else:
        async with aiosqlite.connect("data.db") as db:
            rows = await db.execute_fetchall("SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=?", (m.from_user.id,))
        if not rows:
            await m.answer("❌ هیچ اینباندی به شما اختصاص داده نشده.")
            return
        inbound_ids = [r[0] for r in rows]

    _, details = await build_report(inbound_ids)
    expired = sorted(details.get("expired", []))
    msg = f"🟢 <b>تعداد کل کاربران منقضی شده شما</b> [ {len(expired)} ]\n\n"
    if expired:
        msg += "\n".join([f"👤 - [ {safe_text(u)} ]" for u in expired])
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="♻️ بروزرسانی به آخرین وضعیت", callback_data="refresh_expired")]])
    await m.answer(msg, reply_markup=kb)

@dp.callback_query(F.data == "refresh_expired")
async def refresh_expired(query):
    user_id = query.from_user.id
    if user_id in SUPERADMINS:
        data = api.inbounds()
        inbound_ids = [ib.get("id") for ib in data if isinstance(ib, dict)]
    else:
        async with aiosqlite.connect("data.db") as db:
            rows = await db.execute_fetchall("SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=?", (user_id,))
        if not rows:
            await query.message.edit_text("❌ هیچ اینباندی به شما اختصاص داده نشده.")
            await query.answer()
            return
        inbound_ids = [r[0] for r in rows]

    _, details = await build_report(inbound_ids)
    expired = sorted(details.get("expired", []))
    msg = f"🟢 <b>تعداد کل کاربران منقضی شده شما</b> [ {len(expired)} ]\n\n"
    if expired:
        msg += "\n".join([f"👤 - [ {safe_text(u)} ]" for u in expired])
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="♻️ بروزرسانی به آخرین وضعیت", callback_data="refresh_expired")]])
    try:
        await query.message.edit_text(msg, reply_markup=kb)
        await query.answer("✅ بروزرسانی شد", show_alert=False)
    except Exception as e:
        log_error(e)
        await query.answer("ℹ️ تغییری نسبت به گزارش قبلی نبود.", show_alert=False)

# --- JOBS ---
async def send_full_reports():
    # for all resellers
    async with aiosqlite.connect("data.db") as db:
        rows = await db.execute_fetchall("SELECT DISTINCT telegram_id FROM reseller_inbounds")
    for (tg,) in rows:
        async with aiosqlite.connect("data.db") as db:
            ibs = await db.execute_fetchall("SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=?", (tg,))
        inbound_ids = [r[0] for r in ibs]
        report, details = await build_report(inbound_ids)
        report += f"\n\n{now_shamsi_str()}"
        try:
            # No extra prefix to respect the requested format
            await bot.send_message(tg, report)
        except Exception as e:
            log_error(e)
        async with aiosqlite.connect("data.db") as db:
            await db.execute(
                "INSERT OR REPLACE INTO last_reports(telegram_id, last_json, last_full_report) VALUES (?, ?, ?)",
                (tg, json.dumps(details), int(time.time()))
            )
            await db.commit()

    # for superadmins: whole panel
    data = api.inbounds()
    if isinstance(data, list):
        all_ids = [ib.get("id") for ib in data if isinstance(ib, dict)]
        report, details = await build_report(all_ids)
        report += f"\n\n{now_shamsi_str()}"
        for tg in SUPERADMINS:
            try:
                await bot.send_message(tg, report)
            except Exception as e:
                log_error(e)
            async with aiosqlite.connect("data.db") as db:
                await db.execute(
                    "INSERT OR REPLACE INTO last_reports(telegram_id, last_json, last_full_report) VALUES (?, ?, ?)",
                    (tg, json.dumps(details), int(time.time()))
                )
                await db.commit()

def _format_expiring_msg_super(name: str) -> str:
    name = safe_text(name)
    return (
        "📢 <b>مدیریت محترم ... </b>\n\n"
        "⏳ اشتراک با مشخصات زیر، <b>[ بزودی ]</b> منقضی خواهد شد ... \n\n"
        f"👥 [ {name} ]\n\n"
        "+ <b>درصورت تمایل ، نسبت به شارژ مجدد از داخل پنل کاربری خود اقدام کنید </b>"
    )

def _format_expiring_msg_reseller(name: str) -> str:
    name = safe_text(name)
    return (
        "📢 <b>نماینده محترم ... </b>\n\n"
        "⏳ اشتراک با مشخصات زیر، <b>[ بزودی ]</b> منقضی خواهد شد ... \n\n"
        f"👥 [ {name} ]\n\n"
        "+ <b>درصورت تمایل ، نسبت به شارژ مجدد از داخل پنل کاربری خود اقدام کنید </b>"
    )

def _format_expired_msg_super(name: str) -> str:
    name = safe_text(name)
    return (
        "📢 <b>مدیریت محترم ... </b>\n\n"
        "⏳ اشتراک با مشخصات زیر ، <b>[ منقضی ]</b> گردیده است ... \n\n"
        f"👥 [ {name} ]\n\n"
        "+ <b>درصورت تمایل ، نسبت به شارژ مجدد از داخل پنل کاربری خود اقدام کنید </b>"
    )

def _format_expired_msg_reseller(name: str) -> str:
    name = safe_text(name)
    return (
        "📢 <b>نماینده محترم ... </b>\n\n"
        "⏳ اشتراک با مشخصات زیر ، <b>[ منقضی ]</b> گردیده است ... \n\n"
        f"👥 [ {name} ]\n\n"
        "+ <b>درصورت تمایل ، نسبت به شارژ مجدد از داخل پنل کاربری خود اقدام کنید </b>"
    )

async def check_changes():
    # changes for each reseller
    async with aiosqlite.connect("data.db") as db:
        rows = await db.execute_fetchall("SELECT DISTINCT telegram_id FROM reseller_inbounds")
    for (tg,) in rows:
        async with aiosqlite.connect("data.db") as db:
            ibs = await db.execute_fetchall("SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=?", (tg,))
        inbound_ids = [r[0] for r in ibs]
        _, details = await build_report(inbound_ids)

        async with aiosqlite.connect("data.db") as db:
            cur = await db.execute("SELECT last_json FROM last_reports WHERE telegram_id=?", (tg,))
            row = await cur.fetchone()
            last = json.loads(row[0]) if row and row[0] else {"expiring": [], "expired": [], "up": 0, "down": 0}

        new_expiring = [u for u in details["expiring"] if u not in last["expiring"]]
        new_expired = [u for u in details["expired"] if u not in last["expired"]]

        # Send per-user formatted messages to reseller
        for user_name in new_expiring:
            try:
                await bot.send_message(tg, _format_expiring_msg_reseller(user_name))
            except Exception as e:
                log_error(e)
        for user_name in new_expired:
            try:
                await bot.send_message(tg, _format_expired_msg_reseller(user_name))
            except Exception as e:
                log_error(e)

        async with aiosqlite.connect("data.db") as db:
            await db.execute(
                "INSERT OR REPLACE INTO last_reports(telegram_id, last_json, last_full_report) VALUES (?, ?, ?)",
                (tg, json.dumps(details), int(time.time()))
            )
            await db.commit()

    # panel changes for superadmins
    data = api.inbounds()
    if isinstance(data, list):
        all_ids = [ib.get("id") for ib in data if isinstance(ib, dict)]
        _, details = await build_report(all_ids)
        for tg in SUPERADMINS:
            async with aiosqlite.connect("data.db") as db:
                cur = await db.execute("SELECT last_json FROM last_reports WHERE telegram_id=?", (tg,))
                row = await cur.fetchone()
                last = json.loads(row[0]) if row and row[0] else {"expiring": [], "expired": [], "up": 0, "down": 0}

            new_expiring = [u for u in details["expiring"] if u not in last["expiring"]]
            new_expired = [u for u in details["expired"] if u not in last["expired"]]

            # Send per-user formatted messages to superadmin
            for user_name in new_expiring:
                try:
                    await bot.send_message(tg, _format_expiring_msg_super(user_name))
                except Exception as e:
                    log_error(e)
            for user_name in new_expired:
                try:
                    await bot.send_message(tg, _format_expired_msg_super(user_name))
                except Exception as e:
                    log_error(e)

            async with aiosqlite.connect("data.db") as db:
                await db.execute(
                    "INSERT OR REPLACE INTO last_reports(telegram_id, last_json, last_full_report) VALUES (?, ?, ?)",
                    (tg, json.dumps(details), int(time.time()))
                )
                await db.commit()

# --- MAIN ---
async def main():
    await ensure_db()
    await test_token()
    scheduler.add_job(send_full_reports, "cron", hour=0, minute=0, timezone="Asia/Tehran")
    scheduler.add_job(check_changes, "interval", minutes=1)
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
