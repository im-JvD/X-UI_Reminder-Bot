import os
import asyncio
import aiosqlite
import time
import traceback
import json
import logging
import jdatetime
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, List, Tuple, Any

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

def log_error(e: Exception):
    try:
        with open("log.txt", "a", encoding="utf-8") as f:
            f.write(f"[{time.ctime()}]\n{traceback.format_exc()}\n")
    except Exception:
        pass

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
REQUIRED_CHANNEL_ID = os.getenv("REQUIRED_CHANNEL_ID", "")
SUPERADMINS = {int(x) for x in os.getenv("SUPERADMINS", "").split(",") if x.strip()}

PANEL_BASE = os.getenv("PANEL_BASE", "").rstrip("/")
WEBBASEPATH = os.getenv("WEBBASEPATH", "").rstrip("/")
PANEL_USERNAME = os.getenv("PANEL_USERNAME", "")
PANEL_PASSWORD = os.getenv("PANEL_PASSWORD", "")

if PANEL_BASE and WEBBASEPATH:
    LOGIN_URL = f"{PANEL_BASE}{WEBBASEPATH}/login"
elif PANEL_BASE:
    LOGIN_URL = f"{PANEL_BASE}/login"
else:
    LOGIN_URL = ""

EXPIRING_DAYS_THRESHOLD = int(os.getenv("EXPIRING_DAYS_THRESHOLD", "1"))
EXPIRING_GB_THRESHOLD = int(os.getenv("EXPIRING_GB_THRESHOLD", "1"))

EXPIRING_SECONDS_THRESHOLD = EXPIRING_DAYS_THRESHOLD * 24 * 3600
EXPIRING_BYTES_THRESHOLD = EXPIRING_GB_THRESHOLD * (1024**3)


# ---------------- Panel API ----------------
try:
    from api import PanelAPI
except Exception:
    class PanelAPI:
        def __init__(self, user, pwd):
            self.user, self.pwd = user, pwd
        def inbounds(self) -> List[dict]:
            return []
        def online_clients(self) -> List[str]:
            return []

api = PanelAPI(PANEL_USERNAME, PANEL_PASSWORD)

# ---------------- Bot / Dispatcher / Scheduler ----------------
bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
scheduler = AsyncIOScheduler()

def get_main_kb(user_id: int) -> ReplyKeyboardMarkup:
    if user_id in SUPERADMINS:
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📊 گزارش کلی")],
                [KeyboardButton(text="🟢 کاربران آنلاین")],
                [KeyboardButton(text="⏳ رو به انقضا")],
                [KeyboardButton(text="🚫 منقضی‌شده")],
                [KeyboardButton(text="🧑‍💼 مدیریت ریسلرها")]
            ],
            resize_keyboard=True
        )
    else:
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📊 گزارش کلی")],
                [KeyboardButton(text="🟢 کاربران آنلاین")],
                [KeyboardButton(text="⏳ رو به انقضا")],
                [KeyboardButton(text="🚫 منقضی‌شده")]
            ],
            resize_keyboard=True
        )

# ---------------- DataBase ----------------
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

async def _get_scope_inbound_ids(tg_id: int) -> List[int]:
    """ Return all inbound IDs for superadmins, or assigned IDs for resellers """
    if tg_id in SUPERADMINS:
        try:
            data = api.inbounds()
            return [ib.get("id") for ib in data if isinstance(ib, dict) and ib.get("id")]
        except Exception as e:
            log_error(e)
            return []
    else:
        async with aiosqlite.connect("data.db") as db:
            cur = await db.execute("SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=?", (tg_id,))
            rows = await cur.fetchall()
            return [r[0] for r in rows]

# ---------------- Utils ----------------
def now_shamsi_str() -> str:
    """
    برگرداندن تاریخ و ساعت فعلی به شمسی
    فرمت: تاریخ = [ 25 مهر 1404 ] - ساعت = [ 23:17 ]
    """
    tz = ZoneInfo("Asia/Tehran")
    now = datetime.now(tz)
    
    # تبدیل به تاریخ شمسی
    shamsi = jdatetime.datetime.fromgregorian(datetime=now)
    
    # نام ماه‌های فارسی
    month_names = {
        1: 'فروردین',
        2: 'اردیبهشت',
        3: 'خرداد',
        4: 'تیر',
        5: 'مرداد',
        6: 'شهریور',
        7: 'مهر',
        8: 'آبان',
        9: 'آذر',
        10: 'دی',
        11: 'بهمن',
        12: 'اسفند'
    }
    
    day = shamsi.day
    month = month_names[shamsi.month]
    year = shamsi.year
    time_str = shamsi.strftime("%H:%M")
    
    return f"تاریخ = [ {day} {month} {year} ] - ساعت = [ {time_str} ]"
    
def format_bytes(byte_count: int) -> str:
    if byte_count is None: return "N/A"
    power = 1024
    n = 0
    power_labels = {0: '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while byte_count >= power and n < len(power_labels) -1 :
        byte_count /= power
        n += 1
    return f"{byte_count:.2f} {power_labels[n]}B"

def safe_text(s: str) -> str:
    return s.replace("<", "&lt;").replace(">", "&gt;").replace("&", "&amp;")

def _calc_status_for_client(c: dict, now_ts: float) -> Tuple[bool, bool]:
    """
    Calculates if a client is 'expiring' or 'expired'.
    Returns a tuple (is_expiring, is_expired).
    """
    up = int(c.get("up", 0) or 0)
    down = int(c.get("down", 0) or 0)
    used = up + down

    total_gb_val = c.get("totalGB", 0)
    total_bytes_val = c.get("total", 0)

    try:
        if total_gb_val > 0:
            total_bytes = int(float(total_gb_val or 0) * (1024**3))
        else:
            total_bytes = int(float(total_bytes_val or 0))
    except (ValueError, TypeError):
        total_bytes = 0

    expiry_ms = c.get("expiryTime", c.get("expire", 0))
    try:
        expiry_ms = int(expiry_ms or 0)
    except (ValueError, TypeError):
        expiry_ms = 0

    left_bytes = None
    if total_bytes > 0:
        left_bytes = total_bytes - used

    expired_quota = (left_bytes is not None and left_bytes <= 0)
    expired_time = (expiry_ms > 0 and (expiry_ms / 1000.0) <= now_ts)
    is_expired = expired_quota or expired_time

    is_expiring = False
    if not is_expired:
        expiring_time = False
        if expiry_ms > 0:
            secs_left = (expiry_ms / 1000.0) - now_ts
            if 0 < secs_left <= EXPIRING_SECONDS_THRESHOLD:
                expiring_time = True

        expiring_quota = False
        if left_bytes is not None:
            if 0 < left_bytes <= EXPIRING_BYTES_THRESHOLD:
                expiring_quota = True

        if expiring_time or expiring_quota:
            is_expiring = True

    return is_expiring, is_expired


def build_snapshot(inbound_ids: List[int]) -> Dict[str, Any]:
    """ Build a full data snapshot for a given list of inbounds """
    snapshot = {
        "counts": {"users": 0, "online": 0, "expiring": 0, "expired": 0},
        "lists": {"online": [], "expiring": [], "expired": []},
        "usage": {"used": 0, "capacity": 0, "remaining": 0, "unlimited": False}
    }
    if not inbound_ids:
        return snapshot

    try:
        now = time.time()
        all_inbounds = api.inbounds()
        online_clients_emails = api.online_clients()

        target_inbounds = [ib for ib in all_inbounds if ib.get("id") in inbound_ids]
        if not target_inbounds:
            return snapshot

        total_inbound_used = 0
        total_inbound_capacity = 0
        has_unlimited = False

        for ib in target_inbounds:
            if not isinstance(ib, dict): continue
            
            ib_total = int(ib.get("total", 0) or 0)
            ib_up = int(ib.get("up", 0) or 0)
            ib_down = int(ib.get("down", 0) or 0)
            
            if ib_total == 0:
                has_unlimited = True
            
            total_inbound_capacity += ib_total
            total_inbound_used += (ib_up + ib_down)

            clients = ib.get("clientStats", [])
            if not isinstance(clients, list):
                try:
                    clients = json.loads(ib.get("settings", "{}")).get("clients", [])
                except (json.JSONDecodeError, AttributeError):
                    clients = []
            
            snapshot["counts"]["users"] += len(clients)

            for c in clients:
                if not isinstance(c, dict): continue
                email = c.get("email", "Unnamed")
                
                is_expiring, is_expired = _calc_status_for_client(c, now)
                
                if is_expired:
                    snapshot["counts"]["expired"] += 1
                    snapshot["lists"]["expired"].append(email)
                elif is_expiring:
                    snapshot["counts"]["expiring"] += 1
                    snapshot["lists"]["expiring"].append(email)

                if c.get("enable") and email in online_clients_emails:
                    snapshot["counts"]["online"] += 1
                    snapshot["lists"]["online"].append(email)

        remaining = max(total_inbound_capacity - total_inbound_used, 0) if total_inbound_capacity > 0 else 0
        snapshot["usage"] = {
            "used": total_inbound_used,
            "capacity": total_inbound_capacity,
            "remaining": remaining,
            "unlimited": has_unlimited and total_inbound_capacity == 0
        }
        return snapshot
    except Exception as e:
        log_error(e)
        return snapshot

# ---------------- Formatting ----------------
def format_main_report(counts: Dict[str,int], usage: Dict[str,int]) -> str:
    used_str = format_bytes(usage.get("used", 0))

    if usage.get("capacity", 0) == 0 and usage.get("unlimited"):
        remaining_str = "نامحدود"
    else:
        remaining_str = format_bytes(usage.get("remaining", 0))

    return (
        "📊 <b>گزارش نهایی از وضعیت فعلی شما :</b>\n\n"
        f"📈 <b>مصرف کل:</b> [ {used_str} ]\n"
        f"💾 <b>حجم باقی‌مانده:</b> [ {remaining_str} ]\n\n"
        f"👥 <b>تعداد کل کاربران شما :</b> [ {counts.get('users',0)} ]\n"
        f"🟢 <b>تعداد کاربران آنلاین :</b> [ {counts.get('online',0)} ]\n"
        f"⏳ <b>کاربرانی که بزودی منقضی خواهند شد :</b> [ {counts.get('expiring',0)} ]\n"
        f"🚫 <b>کاربرانی که منقضی شده‌اند :</b> [ {counts.get('expired',0)} ]"
    )

def format_list(header_title: str, items: List[str]) -> str:
    msg = f"{header_title} [ {len(items)} ]\n\n"
    if items:
        msg += "\n".join([f"👤 - [ {safe_text(u)} ]" for u in items])
    return msg


# ---------------- Commands ----------------
@dp.message(Command("start"))
async def start_cmd(m: Message):
    try:
        if REQUIRED_CHANNEL_ID:
            member = await bot.get_chat_member(REQUIRED_CHANNEL_ID, m.from_user.id)
            is_member = member.status in ("member", "administrator", "creator")
        else:
            is_member = True
    except Exception:
        is_member = False
    if not is_member:
        await m.answer(f"برای استفاده از ربات ابتدا باید عضو کانال {REQUIRED_CHANNEL_ID} شوید.")

    is_new = await ensure_user_and_check_new(m.from_user.id)
    kb = get_main_kb(m.from_user.id)
    await m.answer("👋 Welcome to X-UI Reminder Bot!", reply_markup=kb)

    if is_new:
        u = m.from_user
        fullname = (u.first_name or "") + ((" " + u.last_name) if u.last_name else "")
        username = f"@{u.username}" if u.username else "N/A"
        uid = u.id
        date_str = now_shamsi_str()
        txt = (f"یک کاربر جدید با مشخصات زیر ربات را استارت کرد ...\n\n"
               f"نام اکانت تلگرام : {fullname}\n"
               f"نام کاربری کاربر : {username}\n"
               f"آی‌دی عددی کاربر : {uid}\n"
               f"عضویت در ربات : {date_str}")
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="➕ اختصاص اینباند", callback_data=f"assign_inbound:{uid}")]]
        )
        for admin_id in SUPERADMINS:
            try:
                await bot.send_message(admin_id, safe_text(txt), reply_markup=kb)
            except Exception as e:
                log_error(e)


@dp.callback_query(F.data.startswith("assign_inbound:"))
async def ask_inbound_id(query: CallbackQuery):
    admin_id = query.from_user.id
    if admin_id not in SUPERADMINS:
        await query.answer("⛔️ فقط سوپرادمین می‌تواند این کار را انجام دهد.", show_alert=True)
        return
    try:
        reseller_id = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        await query.answer("داده نامعتبر.", show_alert=True)
        return
    
    current_action[admin_id] = ("assign_inbound_for_add", reseller_id)
    await query.message.answer(
        f"✅ کاربر با شناسه {reseller_id} برای افزودن به عنوان ریسلر انتخاب شد.\n"
        f"حالا شناسه اینباند(ها) را برای این کاربر ارسال کنید (می‌توانید چند شناسه را با کاما , جدا کنید)."
    )
    await query.answer()


@dp.message(Command("report"))
async def report_cmd(m: Message):
    inbound_ids = await _get_scope_inbound_ids(m.from_user.id)
    if not inbound_ids:
        await m.answer("❌ هیچ اینباندی به شما اختصاص داده نشده.")
        return
    snap = build_snapshot(inbound_ids)
    msg = format_main_report(snap["counts"], snap["usage"]) + f"\n\n{now_shamsi_str()}"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="♻️ بروزرسانی به آخرین وضعیت", callback_data="refresh_report")]]
    )
    await m.answer(msg, reply_markup=kb)


@dp.callback_query(F.data == "refresh_report")
async def refresh_report(query: CallbackQuery):
    inbound_ids = await _get_scope_inbound_ids(query.from_user.id)
    if not inbound_ids:
        await query.message.edit_text("❌ هیچ اینباندی به شما اختصاص داده نشده.")
        await query.answer()
        return
    snap = build_snapshot(inbound_ids)
    new_msg = format_main_report(snap["counts"], snap["usage"]) + f"\n\n{now_shamsi_str()}"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="♻️ بروزرسانی به آخرین وضعیت", callback_data="refresh_report")]]
    )
    if query.message.text != new_msg:
        await query.message.edit_text(new_msg, reply_markup=kb)
        await query.answer("✅ بروزرسانی شد", show_alert=False)
    else:
        await query.answer("ℹ️ بدون تغییر", show_alert=False)

@dp.message(Command("online"))
async def online_cmd(m: Message):
    inbound_ids = await _get_scope_inbound_ids(m.from_user.id)
    if not inbound_ids:
        await m.answer("❌ هیچ اینباندی به شما اختصاص داده نشده.")
        return
    snap = build_snapshot(inbound_ids)
    header = "🟢 <b>تعداد کل کاربران آنلاین شما</b>"
    msg = format_list(header, snap["lists"]["online"])
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="♻️ بروزرسانی به آخرین وضعیت", callback_data="refresh_online")]]
    )
    await m.answer(msg, reply_markup=kb)

@dp.callback_query(F.data == "refresh_online")
async def refresh_online(query: CallbackQuery):
    inbound_ids = await _get_scope_inbound_ids(query.from_user.id)
    if not inbound_ids:
        await query.message.edit_text("❌ هیچ اینباندی به شما اختصاص داده نشده.")
        await query.answer()
        return
    snap = build_snapshot(inbound_ids)
    header = "🟢 <b>تعداد کل کاربران آنلاین شما</b>"
    new_msg = format_list(header, snap["lists"]["online"])
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="♻️ بروزرسانی به آخرین وضعیت", callback_data="refresh_online")]]
    )
    if query.message.text != new_msg:
        await query.message.edit_text(new_msg, reply_markup=kb)
        await query.answer("✅ بروزرسانی شد", show_alert=False)
    else:
        await query.answer("ℹ️ بدون تغییر", show_alert=False)

@dp.message(Command("expiring"))
async def expiring_cmd(m: Message):
    inbound_ids = await _get_scope_inbound_ids(m.from_user.id)
    if not inbound_ids:
        await m.answer("❌ هیچ اینباندی به شما اختصاص داده نشده.")
        return
    snap = build_snapshot(inbound_ids)
    header = "⏳ <b>تعداد کل کاربران رو به انقضا شما</b>"
    msg = format_list(header, snap["lists"]["expiring"])
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="♻️ بروزرسانی به آخرین وضعیت", callback_data="refresh_expiring")]]
    )
    await m.answer(msg, reply_markup=kb)


@dp.callback_query(F.data == "refresh_expiring")
async def refresh_expiring(query: CallbackQuery):
    inbound_ids = await _get_scope_inbound_ids(query.from_user.id)
    if not inbound_ids:
        await query.message.edit_text("❌ هیچ اینباندی به شما اختصاص داده نشده.")
        await query.answer()
        return
    snap = build_snapshot(inbound_ids)
    header = "⏳ <b>تعداد کل کاربران رو به انقضا شما</b>"
    new_msg = format_list(header, snap["lists"]["expiring"])
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="♻️ بروزرسانی به آخرین وضعیت", callback_data="refresh_expiring")]]
    )
    if query.message.text != new_msg:
        await query.message.edit_text(new_msg, reply_markup=kb)
        await query.answer("✅ بروزرسانی شد", show_alert=False)
    else:
        await query.answer("ℹ️ بدون تغییر", show_alert=False)

@dp.message(Command("expired"))
async def expired_cmd(m: Message):
    inbound_ids = await _get_scope_inbound_ids(m.from_user.id)
    if not inbound_ids:
        await m.answer("❌ هیچ اینباندی به شما اختصاص داده نشده.")
        return
    snap = build_snapshot(inbound_ids)
    header = "🚫 <b>تعداد کل کاربران منقضی شده شما</b>"
    msg = format_list(header, snap["lists"]["expired"])
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="♻️ بروزرسانی به آخرین وضعیت", callback_data="refresh_expired")]]
    )
    await m.answer(msg, reply_markup=kb)

@dp.callback_query(F.data == "refresh_expired")
async def refresh_expired(query: CallbackQuery):
    inbound_ids = await _get_scope_inbound_ids(query.from_user.id)
    if not inbound_ids:
        await query.message.edit_text("❌ هیچ اینباندی به شما اختصاص داده نشده.")
        await query.answer()
        return
    snap = build_snapshot(inbound_ids)
    header = "🚫 <b>تعداد کل کاربران منقضی شده شما</b>"
    new_msg = format_list(header, snap["lists"]["expired"])
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="♻️ بروزرسانی به آخرین وضعیت", callback_data="refresh_expired")]]
    )
    if query.message.text != new_msg:
        await query.message.edit_text(new_msg, reply_markup=kb)
        await query.answer("✅ بروزرسانی شد", show_alert=False)
    else:
        await query.answer("ℹ️ بدون تغییر", show_alert=False)

# ---------------- Button Handlers (added) ----------------
MANAGE_RESELLERS_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="➕ افزودن ریسلر جدید", callback_data="add_reseller")],
    [InlineKeyboardButton(text="🔁 تغییر شناسه اینباند", callback_data="edit_reseller")],
    [InlineKeyboardButton(text="❌ حذف ریسلر", callback_data="delete_reseller")],
    [InlineKeyboardButton(text="⬅️ بازگشت به منوی اصلی", callback_data="back_main")]
])

@dp.message(F.text == "📊 گزارش کلی")
async def btn_report(m: Message):
    await report_cmd(m)

@dp.message(F.text == "🟢 کاربران آنلاین")
async def btn_online(m: Message):
    await online_cmd(m)

@dp.message(F.text == "⏳ رو به انقضا")
async def btn_expiring(m: Message):
    await expiring_cmd(m)

@dp.message(F.text == "🚫 منقضی‌شده")
async def btn_expired(m: Message):
    await expired_cmd(m)

# ---------------- Reseller Management ----------------
@dp.message(F.text == "🧑‍💼 مدیریت ریسلرها")
async def manage_resellers_menu(m: Message):
    if m.from_user.id not in SUPERADMINS:
        return await m.answer("⛔️ این بخش فقط برای ادمین اصلی در دسترس است.")
    await m.answer("🧑‍💼 <b>مدیریت ادمین‌های ریسلر</b>\nگزینه مورد نظر را انتخاب کنید:", reply_markup=MANAGE_RESELLERS_KB)

@dp.callback_query(F.data == "add_reseller")
async def add_reseller_callback(c: CallbackQuery):
    await c.message.answer("🆔 شناسه تلگرام ریسلر جدید را ارسال کنید:")
    await c.answer()

@dp.callback_query(F.data == "edit_reseller")
async def edit_reseller_callback(c: CallbackQuery):
    await c.message.answer("🆔 شناسه تلگرام ریسلر را بفرستید تا شناسه اینباند جدید را تنظیم کنم:")
    await c.answer()

@dp.callback_query(F.data == "delete_reseller")
async def delete_reseller_callback(c: CallbackQuery):
    await c.message.answer("🆔 شناسه تلگرام ریسلری که می‌خواهید حذف شود را ارسال کنید:")
    await c.answer()

@dp.callback_query(F.data == "back_main")
async def back_to_main(c: CallbackQuery):
    kb = get_main_kb(c.from_user.id)
    await c.message.edit_text("↩️ بازگشت به منوی اصلی:", reply_markup=kb)
    await c.answer()

# ---------------- Full Reports & Change Notifications ----------------
def _format_expiring_msg_super(name: str) -> str:
    return (
        "📢 <b>مدیر محترم ... </b>\n\n"
        "⏳ اشتراک با مشخصات زیر، <b>[ بزودی ]</b> منقضی خواهد شد ... \n\n"
        f"👥 [ {safe_text(name)} ]\n\n"
        "+ <b>درصورت تمایل ، نسبت به شارژ مجدد از داخل پنل کاربری خود اقدام کنید </b>"
    )

def _format_expired_msg_super(name: str) -> str:
    return (
        "📢 <b>مدیر محترم ... </b>\n\n"
        "🚫 اشتراک با مشخصات زیر ، <b>[ منقضی ]</b> گردیده است ... \n\n"
        f"👥 [ {safe_text(name)} ]\n\n"
        "+ <b>درصورت تمایل ، نسبت به شارژ مجدد از داخل پنل کاربری خود اقدام کنید </b>"
    )

def _format_expiring_msg_reseller(name: str) -> str:
    return (
        "📢 <b>نماینده محترم ... </b>\n\n"
        "⏳ اشتراک با مشخصات زیر، <b>[ بزودی ]</b> منقضی خواهد شد ... \n\n"
        f"👥 [ {safe_text(name)} ]\n\n"
        "+ <b>درصورت تمایل ، نسبت به شارژ مجدد از داخل پنل کاربری خود اقدام کنید </b>"
    )

def _format_expired_msg_reseller(name: str) -> str:
    return (
        "📢 <b>نماینده محترم ... </b>\n\n"
        "🚫 اشتراک با مشخصات زیر ، <b>[ منقضی ]</b> گردیده است ... \n\n"
        f"👥 [ {safe_text(name)} ]\n\n"
        "+ <b>درصورت تمایل ، نسبت به شارژ مجدد از داخل پنل کاربری خود اقدام کنید </b>"
    )

async def send_full_reports():
    # Resellers
    async with aiosqlite.connect("data.db") as db:
        rows = await db.execute_fetchall("SELECT DISTINCT telegram_id FROM reseller_inbounds")
    
    reseller_ids = [r[0] for r in rows if r[0] not in SUPERADMINS]

    for tg in reseller_ids:
        async with aiosqlite.connect("data.db") as db:
            ibs = await db.execute_fetchall("SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=?", (tg,))
        inbound_ids = [r[0] for r in ibs]
        if not inbound_ids:
            continue
        snap = build_snapshot(inbound_ids)
        report = format_main_report(snap["counts"], snap["usage"]) + f"\n\n{now_shamsi_str()}"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="♻️ بروزرسانی به آخرین وضعیت", callback_data="refresh_report")]]
        )
        try:
            await bot.send_message(tg, report, reply_markup=kb)
            await asyncio.sleep(0.2)
        except TelegramForbiddenError:
            logging.warning(f"⚠️ کاربر {tg} ربات را بلاک کرده است. گزارش روزانه ارسال نشد.")
        except Exception as e:
            log_error(e) 
        async with aiosqlite.connect("data.db") as db:
            await db.execute(
                "INSERT OR REPLACE INTO last_reports(telegram_id, last_json, last_full_report) VALUES (?, ?, ?)",
                (tg, json.dumps(snapshot), int(time.time()))
            )
            await db.commit()

    # Superadmins
    all_ids = await _get_scope_inbound_ids(next(iter(SUPERADMINS)) if SUPERADMINS else 0)
    if all_ids:
        snap = build_snapshot(all_ids)
        report = format_main_report(snap["counts"], snap["usage"]) + f"\n\n{now_shamsi_str()}"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="♻️ بروزرسانی به آخرین وضعیت", callback_data="refresh_report")]]
        )
        try:
            await bot.send_message(tg, report, reply_markup=kb)
            await asyncio.sleep(0.2)
        except TelegramForbiddenError:
            logging.warning(f"⚠️ سوپرادمین {tg} ربات را بلاک کرده است. گزارش روزانه ارسال نشد.")
        except Exception as e:
            log_error(e)
            async with aiosqlite.connect("data.db") as db:
                await db.execute(
                    "INSERT OR REPLACE INTO last_reports(telegram_id, last_json, last_full_report) VALUES (?, ?, ?)",
                    (tg, json.dumps(snap), int(time.time()))
                )
                await db.commit()


async def check_for_changes():
    
    users_to_check = set()
    users_to_check.update(SUPERADMINS)
    
    async with aiosqlite.connect("data.db") as db:
        rows = await db.execute_fetchall("SELECT DISTINCT telegram_id FROM reseller_inbounds")
        for (tg,) in rows:
            users_to_check.add(tg)
    
    for tg_id in users_to_check:
        try:
            async with aiosqlite.connect("data.db") as db:
                cur = await db.execute("SELECT last_json FROM last_reports WHERE telegram_id=?", (tg_id,))
                row = await cur.fetchone()
            
            if not row or not row[0]:
                inbound_ids = await _get_scope_inbound_ids(tg_id)
                if inbound_ids:
                    current_snap = build_snapshot(inbound_ids)
                    async with aiosqlite.connect("data.db") as db:
                        await db.execute(
                            "INSERT OR REPLACE INTO last_reports(telegram_id, last_json, last_full_report) VALUES (?, ?, ?)",
                            (tg_id, json.dumps(current_snap), int(time.time()))
                        )
                        await db.commit()
                    logging.info(f"  📝 Snapshot Overall Inbound Statistics for {tg_id} successfully recorded.")
                continue  
            
            last_snap = json.loads(row[0])
            last_expiring = set(last_snap.get("lists", {}).get("expiring", []))
            last_expired = set(last_snap.get("lists", {}).get("expired", []))
            
            inbound_ids = await _get_scope_inbound_ids(tg_id)
            if not inbound_ids:
                continue
            
            current_snap = build_snapshot(inbound_ids)
            current_expiring = set(current_snap.get("lists", {}).get("expiring", []))
            current_expired = set(current_snap.get("lists", {}).get("expired", []))
            
            newly_expiring = current_expiring - last_expiring
            newly_expired = current_expired - last_expired
            
            is_super = tg_id in SUPERADMINS
            
            if newly_expiring:
                for name in newly_expiring:
                    msg = _format_expiring_msg_super(name) if is_super else _format_expiring_msg_reseller(name)
                    try:
                        await bot.send_message(tg_id, msg)
                        await asyncio.sleep(0.3)
                    except TelegramForbiddenError:
                        logging.warning(f"⚠️ کاربر {tg_id} ربات را بلاک کرده است. نوتیفیکیشن 'رو به انقضا' ارسال نشد.")
                        break 
                    except Exception as e:
                        log_error(e)

            if newly_expired:
                for name in newly_expired:
                    msg = _format_expired_msg_super(name) if is_super else _format_expired_msg_reseller(name)
                    try:
                        await bot.send_message(tg_id, msg)
                        await asyncio.sleep(0.3)
                    except TelegramForbiddenError:
                        logging.warning(f"⚠️ کاربر {tg_id} ربات را بلاک کرده است. نوتیفیکیشن 'منقضی شده' ارسال نشد.")
                        break 
                    except Exception as e:
                        log_error(e)
                        
            async with aiosqlite.connect("data.db") as db:
                await db.execute(
                    "UPDATE last_reports SET last_json = ? WHERE telegram_id = ?",
                    (json.dumps(current_snap), tg_id)
                )
                await db.commit()
            
            await asyncio.sleep(0.5)
            
        except Exception as e:
            log_error(e)
            logging.error(f"  ❌ خطا در بررسی {tg_id}: {e}")
            continue
    
    logging.info("✅ The entire Panel was Successfully reviewed.")

# ---------------- Message Handlers for Reseller Management ----------------
current_action: Dict[int, Tuple[str, Any]] = {}

@dp.message(F.text)
async def text_handler(m: Message):
    admin_id = m.from_user.id
    if admin_id not in SUPERADMINS:
        return
    if admin_id not in current_action:
        return
    
    action, target_user = current_action[admin_id]
    
    if action == "add_reseller":
        try:
            reseller_id = int(m.text)
            current_action[admin_id] = ("assign_inbound_for_add", reseller_id)
            await m.answer(f"✅ ریسلر با شناسه {reseller_id} ثبت شد.\nحالا شناسه اینباند(ها) را برای این ریسلر ارسال کنید (می‌توانید چند شناسه را با کاما , جدا کنید).")
        except ValueError:
            await m.answer("❌ شناسه تلگرام باید یک عدد باشد. لطفاً دوباره تلاش کنید.")
            del current_action[admin_id]

    elif action == "assign_inbound_for_add":
        try:
            inbound_ids_str = m.text.split(',')
            inbound_ids = [int(i.strip()) for i in inbound_ids_str]
            reseller_id = target_user
            
            async with aiosqlite.connect("data.db") as db:
                for ib_id in inbound_ids:
                    await db.execute("INSERT OR IGNORE INTO reseller_inbounds(telegram_id, inbound_id) VALUES (?, ?)", (reseller_id, ib_id))
                await db.commit()

            await m.answer(f"✅ اینباند(های) {', '.join(map(str, inbound_ids))} با موفقیت به ریسلر {reseller_id} اختصاص داده شد.")
            del current_action[admin_id]
        except ValueError:
            await m.answer("❌ شناسه اینباند باید عدد باشد. اگر چند شناسه وارد می‌کنید، با کاما جدا کنید. مثال: 1, 5, 12")

    elif action == "edit_reseller":
        try:
            reseller_id = int(m.text)
            async with aiosqlite.connect("data.db") as db:
                cur = await db.execute("SELECT 1 FROM reseller_inbounds WHERE telegram_id=?", (reseller_id,))
                if not await cur.fetchone():
                    await m.answer(f"❌ ریسلری با شناسه {reseller_id} یافت نشد.")
                    del current_action[admin_id]
                    return
            
            current_action[admin_id] = ("assign_inbound_for_edit", reseller_id)
            await m.answer(f"🔄 لطفاً شناسه اینباند(های) جدید را برای ریسلر {reseller_id} ارسال کنید. توجه: تمام اینباندهای قبلی حذف خواهند شد.")
        except ValueError:
            await m.answer("❌ شناسه تلگرام باید یک عدد باشد.")
            del current_action[admin_id]

    elif action == "assign_inbound_for_edit":
        try:
            inbound_ids_str = m.text.split(',')
            inbound_ids = [int(i.strip()) for i in inbound_ids_str]
            reseller_id = target_user
            
            async with aiosqlite.connect("data.db") as db:
                await db.execute("DELETE FROM reseller_inbounds WHERE telegram_id=?", (reseller_id,))
                for ib_id in inbound_ids:
                    await db.execute("INSERT INTO reseller_inbounds(telegram_id, inbound_id) VALUES (?, ?)", (reseller_id, ib_id))
                await db.commit()

            await m.answer(f"✅ اینباند(های) ریسلر {reseller_id} با موفقیت به {', '.join(map(str, inbound_ids))} به‌روزرسانی شد.")
            del current_action[admin_id]
        except ValueError:
             await m.answer("❌ شناسه اینباند باید عدد باشد. اگر چند شناسه وارد می‌کنید، با کاما جدا کنید.")
    
    elif action == "delete_reseller":
        try:
            reseller_id = int(m.text)
            async with aiosqlite.connect("data.db") as db:
                cur = await db.execute("DELETE FROM reseller_inbounds WHERE telegram_id=?", (reseller_id,))
                await db.commit()
                if cur.rowcount > 0:
                    await m.answer(f"✅ ریسلر با شناسه {reseller_id} و تمام اینباندهای اختصاص‌یافته به او با موفقیت حذف شدند.")
                else:
                    await m.answer(f"ℹ️ ریسلری با شناسه {reseller_id} یافت نشد.")
            del current_action[admin_id]
        except ValueError:
            await m.answer("❌ شناسه تلگرام باید یک عدد باشد.")
            del current_action[admin_id]

@dp.callback_query(F.data == "add_reseller")
async def add_reseller_callback(c: CallbackQuery):
    current_action[c.from_user.id] = ("add_reseller", None)
    await c.message.answer("🆔 شناسه تلگرام ریسلر جدید را ارسال کنید:")
    await c.answer()

@dp.callback_query(F.data == "edit_reseller")
async def edit_reseller_callback(c: CallbackQuery):
    current_action[c.from_user.id] = ("edit_reseller", None)
    await c.message.answer("🆔 شناسه تلگرام ریسلر را بفرستید تا شناسه اینباند جدید را تنظیم کنم:")
    await c.answer()

@dp.callback_query(F.data == "delete_reseller")
async def delete_reseller_callback(c: CallbackQuery):
    current_action[c.from_user.id] = ("delete_reseller", None)
    await c.message.answer("🆔 شناسه تلگرام ریسلری که می‌خواهید حذف شود را ارسال کنید:")
    await c.answer()

# ---------------- Main Loop ----------------
async def main():
    await ensure_db()

    if not api.login(LOGIN_URL):
        logging.error("FATAL: Could not log in to the panel. Check credentials and URL in .env file.")
        return

    # Schedule jobs
    scheduler.add_job(send_full_reports, "cron", hour=20, minute=30)
    scheduler.add_job(check_for_changes, "interval", minutes=15)
    scheduler.add_job(api.login, "interval", hours=5, args=[LOGIN_URL])
    
    scheduler.start()

    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot has Stopped by User.")
    except Exception as e:
        log_error(e)
        logging.error(f"An unexpected error occurred: {e}")
