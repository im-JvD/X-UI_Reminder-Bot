
import os
import asyncio
import aiosqlite
import time
import traceback
import json
import logging
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
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from pathlib import Path

# ---------------- Logging / ENV ----------------
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

MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🆘 Support / Request Reseller")]],
    resize_keyboard=True
)

# ---------------- DB ----------------
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

# ---------------- Time / Helpers ----------------
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
    if j_day_no >= 366:
        jy += (j_day_no-1)//365
        j_day_no = (j_day_no-1)%365
    for i in range(11):
        if j_day_no < j_days_in_month[i]:
            jm = i+1; jd = j_day_no+1; break
        j_day_no -= j_days_in_month[i]
    else:
        jm = 12; jd = j_day_no+1
    return jy, jm, jd

def now_shamsi_str():
    now = datetime.now(ZoneInfo("Asia/Tehran"))
    jy, jm, jd = gregorian_to_jalali(now.year, now.month, now.day)
    return f"آخرین بروزرسانی - [{jd:02d}-{jm:02d}-{jy:04d}] - [{now.strftime('%H:%M:%S')}]"

def safe_text(s: str) -> str:
    if s is None: return ""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def format_bytes(num: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    n = float(num or 0)
    idx = 0
    while n >= 1024.0 and idx < len(units) - 1:
        n /= 1024.0
        idx += 1
    return f"{n:.2f} {units[idx]}"

# ---------------- Core Snapshot ----------------
def _extract_clients_from_inbound(ib: dict) -> List[dict]:
    settings = ib.get("settings")
    if isinstance(settings, str):
        try:
            settings = json.loads(settings)
        except Exception:
            settings = {}
    if not isinstance(settings, dict):
        settings = {}
    clients = settings.get("clients", ib.get("clients", []))
    return clients if isinstance(clients, list) else []

def _label_client(c: dict) -> str:
    return (
        c.get("email") or
        str(c.get("id") or "") or
        str(c.get("flow") or "") or
        f"client_{abs(hash(json.dumps(c, sort_keys=True))) & 0xffff}"
    )

def _calc_status_for_client(c: dict, now_ts: float) -> Tuple[bool, bool]:
    up = int(c.get("up", 0) or 0)
    down = int(c.get("down", 0) or 0)
    used = up + down

    total = c.get("total", c.get("totalGB", 0))
    try: total = int(total or 0)
    except Exception: total = 0

    expiry_ms = c.get("expiryTime", c.get("expire", 0))
    try: expiry_ms = int(expiry_ms or 0)
    except Exception: expiry_ms = 0

    left_bytes = None
    if total > 0:
        left_bytes = total - used

    expired_quota = (left_bytes is not None and left_bytes <= 0)
    expired_time = (expiry_ms > 0 and (expiry_ms/1000.0) <= now_ts)
    is_expired = expired_quota or expired_time

    expiring_time = False
    if not is_expired and expiry_ms > 0:
        secs_left = (expiry_ms/1000.0) - now_ts
        expiring_time = (0 < secs_left <= 24*3600)

    expiring_quota = False
    if not is_expired and left_bytes is not None:
        expiring_quota = (left_bytes <= 1024**3)  # 1GB

    is_expiring = (expiring_time or expiring_quota) and not is_expired
    return is_expiring, is_expired

async def _get_scope_inbound_ids(user_id: int) -> List[int]:
    if user_id in SUPERADMINS:
        data = api.inbounds()
        return [ib.get("id") for ib in data if isinstance(ib, dict)]
    async with aiosqlite.connect("data.db") as db:
        rows = await db.execute_fetchall(
            "SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=?", (user_id,)
        )
    return [r[0] for r in rows]

def build_snapshot(inbound_ids: List[int]) -> Dict[str, Any]:
    """
    Unified snapshot for the given inbound IDs.
    {
      "all": [labels...],
      "online": [labels...],
      "expiring": [labels...],
      "expired": [labels...],
      "counts": {...},
      "usage": {"used": int, "capacity": int, "remaining": int, "unlimited": bool}
    }
    """
    snapshot = {"all": [], "online": [], "expiring": [], "expired": [],
                "counts": {"users":0,"online":0,"expiring":0,"expired":0},
                "usage": {"used":0,"capacity":0,"remaining":0,"unlimited":False}}
    try:
        data = api.inbounds()
        if not isinstance(data, list):
            return snapshot

        online_all = set(api.online_clients() or [])
        now_ts = time.time()

        # ---- USERS (همان منطق قبل؛ بر اساس کلاینت‌ها) ----
        all_labels, expiring, expired = [], [], []

        # ---- USAGE (جدید؛ بر اساس خود اینباند) ----
        total_inbound_used = 0
        total_inbound_capacity = 0
        has_unlimited = False

        for ib in data:
            if not isinstance(ib, dict) or ib.get("id") not in inbound_ids:
                continue

            # مصرف و ظرفیت در سطح اینباند
            ib_up = int(ib.get("up", 0) or 0)
            ib_down = int(ib.get("down", 0) or 0)
            ib_total =  int(ib.get("total", 0) or 0)  # 0 یعنی نامحدود

            total_inbound_used += (ib_up + ib_down)
            if ib_total > 0:
                total_inbound_capacity += ib_total
            else:
                has_unlimited = True

            # کاربران/کلاینت‌ها برای لیست‌ها
            clients = _extract_clients_from_inbound(ib)
            for c in clients:
                label = _label_client(c)
                if not label:
                    continue
                all_labels.append(label)

                # همان منطق expiring/expired قبلی، اما بر پایهٔ کلاینت
                is_expiring, is_expired = _calc_status_for_client(c, now_ts)
                if is_expired:
                    expired.append(label)
                elif is_expiring:
                    expiring.append(label)

        all_set = set(all_labels)
        online = sorted(list(all_set & online_all))  # ممکنه فقط ایمیل‌ها کراس بخورن

        snapshot["all"] = sorted(list(all_set))
        snapshot["online"] = online
        snapshot["expiring"] = sorted(list(set(expiring)))
        snapshot["expired"] = sorted(list(set(expired)))
        snapshot["counts"] = {
            "users": len(snapshot["all"]),
            "online": len(snapshot["online"]),
            "expiring": len(snapshot["expiring"]),
            "expired": len(snapshot["expired"])
        }

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

    # اگر کل ظرفیت اینباند صفر است ولی نامحدود است
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
    await m.answer("👋 Welcome to X-UI Reminder Bot!", reply_markup=MAIN_KB)

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
               f"تاریخ عضویت در ربات : {date_str}")
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="➕ اختصاص اینباند", callback_data=f"assign_inbound:{uid}")]]
        )
        for admin_id in SUPERADMINS:
            try:
                await bot.send_message(admin_id, safe_text(txt), reply_markup=kb)
            except Exception as e:
                log_error(e)

pending_assign: Dict[int, int] = {}

@dp.callback_query(F.data.startswith("assign_inbound:"))
async def ask_inbound_id(query: CallbackQuery):
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
        await db.execute(
            "INSERT OR IGNORE INTO reseller_inbounds(telegram_id, inbound_id) VALUES (?, ?)",
            (target_user, inbound_id)
        )
        await db.commit()
    await m.answer(f"✅ کاربر {target_user} به عنوان ادمین ریسلر ثبت شد و اینباند {inbound_id} اختصاص داده شد.")
    try:
        await bot.send_message(
            target_user,
            f"✅ شما به عنوان ادمین ریسلر ثبت شدید.\n📦 اینباند اختصاصی شما: {inbound_id}"
        )
    except Exception as e:
        log_error(e)

# /report
@dp.message(Command("report"))
async def report_cmd(m: Message):
    inbound_ids = await _get_scope_inbound_ids(m.from_user.id)
    if not inbound_ids:
        await m.answer("❌ هیچ اینباندی به شما اختصاص داده نشده.")
        return
    snap = build_snapshot(inbound_ids)
    report = format_main_report(snap["counts"], snap["usage"]) + f"\n\n{now_shamsi_str()}"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="♻️ بروزرسانی به آخرین وضعیت", callback_data="refresh_report")]]
    )
    await m.answer(report, reply_markup=kb)

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

# /online
@dp.message(Command("online"))
async def online_cmd(m: Message):
    inbound_ids = await _get_scope_inbound_ids(m.from_user.id)
    if not inbound_ids:
        await m.answer("❌ هیچ اینباندی به شما اختصاص داده نشده.")
        return
    snap = build_snapshot(inbound_ids)
    header = "🟢 <b>تعداد کل کاربران آنلاین شما</b>"
    msg = format_list(header, snap["online"])
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
    new_msg = format_list(header, snap["online"])
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="♻️ بروزرسانی به آخرین وضعیت", callback_data="refresh_online")]]
    )
    if query.message.text != new_msg:
        await query.message.edit_text(new_msg, reply_markup=kb)
        await query.answer("✅ بروزرسانی شد", show_alert=False)
    else:
        await query.answer("ℹ️ بدون تغییر", show_alert=False)

# /expiring
@dp.message(Command("expiring"))
async def expiring_cmd(m: Message):
    inbound_ids = await _get_scope_inbound_ids(m.from_user.id)
    if not inbound_ids:
        await m.answer("❌ هیچ اینباندی به شما اختصاص داده نشده.")
        return
    snap = build_snapshot(inbound_ids)
    header = "🟢 <b>تعداد کل کاربران رو به انقضا شما</b>"
    msg = format_list(header, snap["expiring"])
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
    header = "🟢 <b>تعداد کل کاربران رو به انقضا شما</b>"
    new_msg = format_list(header, snap["expiring"])
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="♻️ بروزرسانی به آخرین وضعیت", callback_data="refresh_expiring")]]
    )
    if query.message.text != new_msg:
        await query.message.edit_text(new_msg, reply_markup=kb)
        await query.answer("✅ بروزرسانی شد", show_alert=False)
    else:
        await query.answer("ℹ️ بدون تغییر", show_alert=False)

# /expired
@dp.message(Command("expired"))
async def expired_cmd(m: Message):
    inbound_ids = await _get_scope_inbound_ids(m.from_user.id)
    if not inbound_ids:
        await m.answer("❌ هیچ اینباندی به شما اختصاص داده نشده.")
        return
    snap = build_snapshot(inbound_ids)
    header = "🟢 <b>تعداد کل کاربران منقضی شده شما</b>"
    msg = format_list(header, snap["expired"])
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
    header = "🟢 <b>تعداد کل کاربران منقضی شده شما</b>"
    new_msg = format_list(header, snap["expired"])
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="♻️ بروزرسانی به آخرین وضعیت", callback_data="refresh_expired")]]
    )
    if query.message.text != new_msg:
        await query.message.edit_text(new_msg, reply_markup=kb)
        await query.answer("✅ بروزرسانی شد", show_alert=False)
    else:
        await query.answer("ℹ️ بدون تغییر", show_alert=False)

# ---------------- Nightly Reports & Change Notifications ----------------
def _format_expiring_msg_super(name: str) -> str:
    return (
        "📢 <b>مدیرت محترم ... </b>\n\n"
        "⏳ اشتراک با مشخصات زیر، <b>[ بزودی ]</b> منقضی خواهد شد ... \n\n"
        f"👥 [ {safe_text(name)} ]\n\n"
        "+ <b>درصورت تمایل ، نسبت به شارژ مجدد از داخل پنل کاربری خود اقدام کنید </b>"
    )

def _format_expired_msg_super(name: str) -> str:
    return (
        "📢 <b>نماینده محترم ... </b>\n\n"
        "⏳ اشتراک با مشخصات زیر ، <b>[ منقضی ]</b> گردیده است ... \n\n"
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
        "⏳ اشتراک با مشخصات زیر ، <b>[ منقضی ]</b> گردیده است ... \n\n"
        f"👥 [ {safe_text(name)} ]\n\n"
        "+ <b>درصورت تمایل ، نسبت به شارژ مجدد از داخل پنل کاربری خود اقدام کنید </b>"
    )

async def send_full_reports():
    # Resellers
    async with aiosqlite.connect("data.db") as db:
        rows = await db.execute_fetchall("SELECT DISTINCT telegram_id FROM reseller_inbounds")
    for (tg,) in rows:
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
        except Exception as e:
            log_error(e)
        async with aiosqlite.connect("data.db") as db:
            await db.execute(
                "INSERT OR REPLACE INTO last_reports(telegram_id, last_json, last_full_report) VALUES (?, ?, ?)",
                (tg, json.dumps(snap), int(time.time()))
            )
            await db.commit()

    # Superadmins
    data = api.inbounds()
    all_ids = [ib.get("id") for ib in data if isinstance(ib, dict)]
    if all_ids:
        snap = build_snapshot(all_ids)
        report = format_main_report(snap["counts"], snap["usage"]) + f"\n\n{now_shamsi_str()}"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="♻️ بروزرسانی به آخرین وضعیت", callback_data="refresh_report")]]
        )
        for tg in SUPERADMINS:
            try:
                await bot.send_message(tg, report, reply_markup=kb)
            except Exception as e:
                log_error(e)
            async with aiosqlite.connect("data.db") as db:
                await db.execute(
                    "INSERT OR REPLACE INTO last_reports(telegram_id, last_json, last_full_report) VALUES (?, ?, ?)",
                    (tg, json.dumps(snap), int(time.time()))
                )
                await db.commit()

async def check_changes():
    # Resellers
    async with aiosqlite.connect("data.db") as db:
        rows = await db.execute_fetchall("SELECT DISTINCT telegram_id FROM reseller_inbounds")
    for (tg,) in rows:
        async with aiosqlite.connect("data.db") as db:
            ibs = await db.execute_fetchall("SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=?", (tg,))
        inbound_ids = [r[0] for r in ibs]
        if not inbound_ids:
            continue
        snap = build_snapshot(inbound_ids)
        async with aiosqlite.connect("data.db") as db:
            cur = await db.execute("SELECT last_json FROM last_reports WHERE telegram_id=?", (tg,))
            row = await cur.fetchone()
            last = json.loads(row[0]) if row and row[0] else {"expiring": [], "expired": []}

        new_expiring = [u for u in snap["expiring"] if u not in last.get("expiring", [])]
        new_expired = [u for u in snap["expired"] if u not in last.get("expired", [])]

        for name in new_expiring:
            try:
                await bot.send_message(tg, _format_expiring_msg_reseller(name))
            except Exception as e:
                log_error(e)
        for name in new_expired:
            try:
                await bot.send_message(tg, _format_expired_msg_reseller(name))
            except Exception as e:
                log_error(e)

        async with aiosqlite.connect("data.db") as db:
            await db.execute(
                "INSERT OR REPLACE INTO last_reports(telegram_id, last_json, last_full_report) VALUES (?, ?, ?)",
                (tg, json.dumps(snap), int(time.time()))
            )
            await db.commit()

    # Superadmins
    data = api.inbounds()
    all_ids = [ib.get("id") for ib in data if isinstance(ib, dict)]
    if all_ids:
        snap = build_snapshot(all_ids)
        for tg in SUPERADMINS:
            async with aiosqlite.connect("data.db") as db:
                cur = await db.execute("SELECT last_json FROM last_reports WHERE telegram_id=?", (tg,))
                row = await cur.fetchone()
                last = json.loads(row[0]) if row and row[0] else {"expiring": [], "expired": []}

            new_expiring = [u for u in snap["expiring"] if u not in last.get("expiring", [])]
            new_expired = [u for u in snap["expired"] if u not in last.get("expired", [])]

            for name in new_expiring:
                try:
                    await bot.send_message(tg, _format_expiring_msg_super(name))
                except Exception as e:
                    log_error(e)
            for name in new_expired:
                try:
                    await bot.send_message(tg, _format_expired_msg_super(name))
                except Exception as e:
                    log_error(e)

            async with aiosqlite.connect("data.db") as db:
                await db.execute(
                    "INSERT OR REPLACE INTO last_reports(telegram_id, last_json, last_full_report) VALUES (?, ?, ?)",
                    (tg, json.dumps(snap), int(time.time()))
                )
                await db.commit()

# ---------------- Main ----------------
async def test_token():
    me = await bot.get_me()
    logging.info(f"Bot connected as @{me.username}; SUPERADMINS={SUPERADMINS}")
    logging.info(f"PANEL_BASE={PANEL_BASE}, WEBBASEPATH={WEBBASEPATH}, LOGIN_URL={LOGIN_URL}")

async def main():
    await ensure_db()
    await test_token()

    scheduler.add_job(send_full_reports, "cron", hour=0, minute=0, timezone="Asia/Tehran")
    scheduler.add_job(check_changes, "interval", minutes=1)
    scheduler.start()

    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        logging.exception("FATAL: bot crashed")
