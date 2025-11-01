import os
import asyncio
import aiosqlite
import time
import traceback
import json
import logging
import jdatetime
import math
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

# Multi-panel support
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

DAILY_REPORT_HOUR = int(os.getenv("DAILY_REPORT_HOUR", "0"))
DAILY_REPORT_MINUTE = int(os.getenv("DAILY_REPORT_MINUTE", "0"))
CHANGE_CHECK_INTERVAL_MINUTES = int(os.getenv("CHANGE_CHECK_INTERVAL_MINUTES", "8"))

# 🔍 Validation
if not (0 <= DAILY_REPORT_HOUR <= 23):
    DAILY_REPORT_HOUR = 0
if not (0 <= DAILY_REPORT_MINUTE <= 59):
    DAILY_REPORT_MINUTE = 0
if CHANGE_CHECK_INTERVAL_MINUTES < 1:
    CHANGE_CHECK_INTERVAL_MINUTES = 8

EXPIRING_SECONDS_THRESHOLD = EXPIRING_DAYS_THRESHOLD * 24 * 3600
EXPIRING_BYTES_THRESHOLD = EXPIRING_GB_THRESHOLD * (1024**3)

# ---------------- Panel API ----------------
try:
    from api import PanelAPI
except Exception:
    class PanelAPI:
        def __init__(self, user, pwd, base_url="", web_base_path=""):
            self.user, self.pwd = user, pwd
            self.base_url = base_url
            self.web_base_path = web_base_path
        def login(self):
            return True
        def inbounds(self) -> List[dict]:
            return []
        def online_clients(self) -> List[str]:
            return []

# ---------------- Bot / Dispatcher / Scheduler ----------------
bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
scheduler = AsyncIOScheduler()

current_action: Dict[int, Tuple[str, Any]] = {}

# ---------------- Keyboards ----------------
MANAGE_RESELLERS_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="➕ افزودن ادمین جدید", callback_data="add_reseller")],
    [InlineKeyboardButton(text="🔁 ویرایش ادمین", callback_data="edit_reseller")],
    [InlineKeyboardButton(text="❌ حذف ادمین", callback_data="delete_reseller")],
    [InlineKeyboardButton(text="📜 لیست نمایندگان فروش", callback_data="list_resellers")],
])

MANAGE_PANELS_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="➕ افزودن پنل جدید", callback_data="add_panel")],
    [InlineKeyboardButton(text="🗑 حذف پنل", callback_data="delete_panel")],
    [InlineKeyboardButton(text="📜 لیست پنل‌ها", callback_data="list_panels")],
])

def get_main_kb(user_id: int) -> ReplyKeyboardMarkup:
    if user_id in SUPERADMINS:
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📊 گزارش کلی")],
                [KeyboardButton(text="🟢 کاربران آنلاین"), KeyboardButton(text="⏳ رو به انقضا"), KeyboardButton(text="🚫 منقضی‌شده")],
                [KeyboardButton(text="🧑‍💼 نمایندگان فروش"), KeyboardButton(text="🎛 مدیریت پنل‌ها")]
            ],
            resize_keyboard=True,
            input_field_placeholder="گزینه مورد نظر را انتخاب کنید ..."
        )
    else:
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📊 گزارش کلی")],
                [KeyboardButton(text="🟢 کاربران آنلاین")],
                [KeyboardButton(text="⏳ رو به انقضا"), KeyboardButton(text="🚫 منقضی‌شده")]
            ],
            resize_keyboard=True,
            input_field_placeholder="گزینه مورد نظر را انتخاب کنید ..."
        )

def safe_text(text: str) -> str:
    """Escape special characters for HTML parsing."""
    if not text:
        return ""
    return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

# ---------------- Database ----------------
async def ensure_db():
    """
    Ensures the database and its tables are created with the new multi-panel schema.
    """
    async with aiosqlite.connect("data.db") as db:
        await db.execute("PRAGMA foreign_keys = ON")

        await db.executescript("""
        CREATE TABLE IF NOT EXISTS panels (
            panel_id INTEGER PRIMARY KEY AUTOINCREMENT,
            panel_name TEXT UNIQUE NOT NULL,
            base_url TEXT NOT NULL,
            web_base_path TEXT,
            username TEXT NOT NULL,
            password TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            role TEXT NOT NULL DEFAULT 'user'
        );

        CREATE TABLE IF NOT EXISTS reseller_inbounds (
            telegram_id INTEGER NOT NULL,
            panel_id INTEGER NOT NULL,
            inbound_id INTEGER NOT NULL,
            PRIMARY KEY (telegram_id, panel_id, inbound_id),
            FOREIGN KEY (panel_id) REFERENCES panels (panel_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS last_reports (
            telegram_id INTEGER PRIMARY KEY,
            last_json TEXT,
            last_full_report INTEGER
        );
        """)
        await db.commit()
        logging.info("DataBase Schema Checked and ensured.")

async def ensure_user_and_check_new(tg_id: int) -> bool:
    async with aiosqlite.connect("data.db") as db:
        cur = await db.execute("SELECT 1 FROM users WHERE telegram_id=?", (tg_id,))
        row = await cur.fetchone()
        if row:
            return False
        await db.execute("INSERT INTO users(telegram_id, role) VALUES (?, 'user')", (tg_id,))
        await db.commit()
        return True

async def get_panel_api(panel_id: int) -> PanelAPI | None:
    """
    Fetches panel credentials from DB, creates an API instance, and logs in.
    Returns the logged-in API instance or None on failure.
    """
    async with aiosqlite.connect("data.db") as db:
        cur = await db.execute("SELECT base_url, web_base_path, username, password FROM panels WHERE panel_id=?", (panel_id,))
        panel_data = await cur.fetchone()

    if not panel_data:
        logging.error(f"Could not find credentials for panel ID {panel_id} in the database.")
        return None

    base_url, web_base_path, username, password = panel_data
    api = PanelAPI(username, password, base_url, web_base_path)

    try:
        if api.login():
            return api
        else:
            return None
    except Exception as e:
        log_error(e)
        logging.error(f"An exception occurred during login to panel ID {panel_id}: {e}")
        return None

async def _get_scope_inbound_ids(tg_id: int) -> List[int]:
    """
    Returns a list of all inbound IDs assigned to a user across all panels.
    For superadmins, returns all inbound IDs from all panels.
    Skips panels that no longer exist in the database.
    """
    inbound_ids = set()

    async with aiosqlite.connect("data.db") as db:
        if tg_id in SUPERADMINS:
            # For Superadmins, get all inbounds from ALL panels
            async with db.execute("SELECT panel_id FROM panels") as panel_cur:
                all_panels = await panel_cur.fetchall()
                for (panel_id,) in all_panels:
                    api = await get_panel_api(panel_id)
                    if not api:
                        logging.warning(f"Could not get API for panel {panel_id}, skipping...")
                        continue
                    try:
                        data = api.inbounds()
                        panel_inbound_ids = [ib['id'] for ib in data if isinstance(ib, dict) and 'id' in ib]
                        inbound_ids.update(panel_inbound_ids)
                    except Exception as e:
                        log_error(e)
                        logging.error(f"Error fetching inbounds for panel {panel_id} for superadmin: {e}")
        else:
            # For Resellers, get their specific assigned inbounds
            # First, get all valid panel IDs
            async with db.execute("SELECT panel_id FROM panels") as panel_cur:
                valid_panels = {row[0] for row in await panel_cur.fetchall()}
            
            # Get reseller's inbounds, but only for panels that still exist
            async with db.execute(
                """
                SELECT ri.inbound_id, ri.panel_id 
                FROM reseller_inbounds ri
                WHERE ri.telegram_id = ?
                """, (tg_id,)
            ) as cur:
                rows = await cur.fetchall()
                for (inbound_id, panel_id) in rows:
                    # Skip if panel no longer exists
                    if panel_id not in valid_panels:
                        logging.warning(f"Panel {panel_id} assigned to reseller {tg_id} no longer exists, skipping inbound {inbound_id}")
                        # Optional: Clean up orphaned records
                        await db.execute(
                            "DELETE FROM reseller_inbounds WHERE telegram_id = ? AND panel_id = ?",
                            (tg_id, panel_id)
                        )
                        await db.commit()
                        continue
                    inbound_ids.add(inbound_id)
                
    return list(inbound_ids)

async def _get_scope_inbounds_by_panel(tg_id: int) -> Dict[int, List[int]]:
    """
    Returns a dictionary mapping panel_id to a list of its assigned inbound_ids for a user.
    For superadmins, it returns all inbounds from all panels.
    Handles deleted panels gracefully.
    """
    scoped_inbounds = {}
    
    async with aiosqlite.connect("data.db") as db:
        # Get all valid panels first
        async with db.execute("SELECT panel_id FROM panels") as panel_cur:
            valid_panels = {row[0] for row in await panel_cur.fetchall()}
        
        if not valid_panels:
            logging.warning("No panels found in database")
            return scoped_inbounds

        if tg_id in SUPERADMINS:
            # For Superadmins, get all inbounds from ALL valid panels
            for panel_id in valid_panels:
                api = await get_panel_api(panel_id)
                if not api:
                    logging.warning(f"Could not get API for panel {panel_id}, skipping...")
                    continue
                try:
                    data = api.inbounds()
                    if not data or not isinstance(data, list):
                        logging.warning(f"Panel {panel_id}: No valid inbounds data")
                        continue
                    
                    inbound_ids = [ib['id'] for ib in data if isinstance(ib, dict) and 'id' in ib]
                    if inbound_ids:
                        scoped_inbounds[panel_id] = inbound_ids
                except Exception as e:
                    log_error(e)
                    logging.error(f"Error fetching inbounds for panel {panel_id} for superadmin: {e}")
        else:
            # For Resellers, get their specific assigned inbounds
            async with db.execute(
                "SELECT panel_id, inbound_id FROM reseller_inbounds WHERE telegram_id=?", (tg_id,)
            ) as cur:
                rows = await cur.fetchall()
                for panel_id, inbound_id in rows:
                    # Skip if panel no longer exists
                    if panel_id not in valid_panels:
                        logging.warning(f"Reseller {tg_id}: Panel {panel_id} no longer exists, cleaning up...")
                        # Clean up orphaned records
                        await db.execute(
                            "DELETE FROM reseller_inbounds WHERE telegram_id = ? AND panel_id = ?",
                            (tg_id, panel_id)
                        )
                        await db.commit()
                        continue
                    
                    if panel_id not in scoped_inbounds:
                        scoped_inbounds[panel_id] = []
                    scoped_inbounds[panel_id].append(inbound_id)
                    
    return scoped_inbounds


# ---------------- Helper Functions for Client Processing ----------------
# Replace the _calc_status_for_client function with the improved version above
def _calc_status_for_client(client: dict, now: float) -> Tuple[bool, bool]:
    """
    Calculates if a client is expiring or expired.
    """
    try:
        # Extract usage data - TRY MULTIPLE FIELDS
        up = int(client.get("up", 0) or client.get("up", 0) or 0)
        down = int(client.get("down", 0) or client.get("down", 0) or 0)
        used_bytes = up + down
        
        # Try multiple total fields (like old code)
        total_gb_val = client.get("totalGB", 0) or client.get("totalGB", 0) or 0
        total_bytes_val = client.get("total", 0) or client.get("total", 0) or 0
        total_gb_raw = client.get("totalGB", 0)  # Raw value from API
        
        # Calculate total_bytes using the same logic as old code
        total_bytes = 0
        if float(total_gb_val or 0) > 0:
            # If totalGB exists, convert to bytes
            total_bytes = int(float(total_gb_val) * (1024**3))
            logging.debug(f"Using totalGB={total_gb_val}, converted to {total_bytes} bytes")
        elif float(total_bytes_val or 0) > 0:
            # Fallback to total (bytes)
            total_bytes = int(float(total_bytes_val))
            logging.debug(f"Using total={total_bytes_val} bytes directly")
        else:
            # Try alternative fields
            alt_total_gb = client.get("totalGB", 0) or client.get("limit", 0) or 0
            if float(alt_total_gb) > 0:
                total_bytes = int(float(alt_total_gb) * (1024**3))
                logging.debug(f"Using alternative totalGB={alt_total_gb}")

        # Expiry time
        expiry_ms = int(client.get("expiryTime", 0) or client.get("expire", 0) or client.get("expiry", 0) or 0)
        now_ts = now

        # Calculate remaining
        left_bytes = None
        if total_bytes > 0:
            left_bytes = total_bytes - used_bytes
            logging.debug(f"Client {client.get('email', 'unknown')}: used={used_bytes}, total={total_bytes}, left={left_bytes}")

        # Check expiration (same as old logic)
        expired_quota = (left_bytes is not None and left_bytes <= 0)
        expired_time = (expiry_ms > 0 and (expiry_ms / 1000.0) <= now_ts)
        is_expired = expired_quota or expired_time

        logging.debug(f"Client {client.get('email', 'unknown')}: expired_quota={expired_quota}, expired_time={expired_time}, is_expired={is_expired}")

        # Check if expiring (not expired)
        is_expiring = False
        if not is_expired:
            # Expiring time
            expiring_time = False
            if expiry_ms > 0:
                secs_left = (expiry_ms / 1000.0) - now_ts
                if 0 < secs_left <= EXPIRING_SECONDS_THRESHOLD:
                    expiring_time = True
                    logging.debug(f"Client expiring by time: {secs_left:.0f} seconds left")

            # Expiring quota
            expiring_quota = False
            if left_bytes is not None and total_bytes > 0:
                if 0 < left_bytes <= EXPIRING_BYTES_THRESHOLD:
                    expiring_quota = True
                    logging.debug(f"Client expiring by quota: {left_bytes} bytes left")

            if expiring_time or expiring_quota:
                is_expiring = True

        logging.debug(f"Client {client.get('email', 'unknown')}: is_expiring={is_expiring}, is_expired={is_expired}")
        return is_expiring, is_expired
        
    except (ValueError, TypeError, KeyError) as e:
        logging.warning(f"Error calculating status for client {client.get('email', 'unknown')}: {e}")
        logging.debug(f"Client data: {client}")
        return False, False

# Replace the _extract_clients_from_inbound function with the improved version above
def _extract_clients_from_inbound(inbound: dict) -> List[dict]:
    """
    Extracts client data from an inbound configuration. Tries multiple possible locations.
    """
    clients = []
    
    if not isinstance(inbound, dict):
        logging.warning("Inbound is not a dict")
        return clients
    
    inbound_id = inbound.get('id', 'unknown')
    
    # Method 1: Direct clientStats (most common in X-UI)
    if 'clientStats' in inbound and isinstance(inbound['clientStats'], list):
        clients = inbound['clientStats']
        logging.debug(f"Inbound {inbound_id}: Found {len(clients)} clients in 'clientStats'")
    
    # Method 2: Settings -> clients (JSON encoded or dict)
    elif 'settings' in inbound:
        try:
            if isinstance(inbound['settings'], str):
                settings = json.loads(inbound['settings'])
            else:
                settings = inbound['settings']
            
            if isinstance(settings, dict) and 'clients' in settings and isinstance(settings['clients'], list):
                clients = settings['clients']
                logging.debug(f"Inbound {inbound_id}: Found {len(clients)} clients in 'settings.clients'")
        except (json.JSONDecodeError, TypeError) as e:
            logging.debug(f"Inbound {inbound_id}: Error parsing settings: {e}")
    
    # Method 3: Direct 'clients' key
    elif 'clients' in inbound and isinstance(inbound['clients'], list):
        clients = inbound['clients']
        logging.debug(f"Inbound {inbound_id}: Found {len(clients)} clients in direct 'clients' key")
    
    # Method 4: Alternative locations (some X-UI versions)
    elif 'client_list' in inbound and isinstance(inbound['client_list'], list):
        clients = inbound['client_list']
        logging.debug(f"Inbound {inbound_id}: Found {len(clients)} clients in 'client_list'")
    
    # Filter out non-dict clients and add debugging
    valid_clients = [c for c in clients if isinstance(c, dict)]
    invalid_count = len(clients) - len(valid_clients)
    
    if invalid_count > 0:
        logging.debug(f"Inbound {inbound_id}: {invalid_count} invalid clients filtered out")
        
    # Log first few clients for debugging
    for i, client in enumerate(valid_clients[:3]):
        email = client.get('email', 'no-email')
        total_gb = client.get('totalGB', client.get('total', 'N/A'))
        logging.debug(f"  Client {i+1}: {email}, total={total_gb}, has 'up'={ 'up' in client}, has 'down'={ 'down' in client}")
    
    return valid_clients

# ---------------- Panel Management ----------------
@dp.message(F.text == "🎛 مدیریت پنل‌ها")
async def manage_panels_menu(m: Message):
    if m.from_user.id not in SUPERADMINS:
        return await m.answer("⛔️ این بخش فقط برای سوپرادمین در دسترس است.")
    await m.answer("🎛 <b>مدیریت پنل‌ها</b>\nگزینه مورد نظر را انتخاب کنید:", reply_markup=MANAGE_PANELS_KB)

@dp.callback_query(F.data == "add_panel")
async def add_panel_callback(c: CallbackQuery):
    if c.from_user.id not in SUPERADMINS: return
    admin_id = c.from_user.id
    current_action[admin_id] = ("get_panel_name", {})
    await c.message.edit_text(
        "📝 برای افزودن، <b>نام پنل جدید</b> را وارد کنید...\n\n"
        "مثال = <b>🇩🇪 - Germany</b>",
    )
    await c.answer()

@dp.callback_query(F.data == "list_panels")
async def list_panels_callback(c: CallbackQuery):
    if c.from_user.id not in SUPERADMINS: return
    
    async with aiosqlite.connect("data.db") as db:
        cur = await db.execute("SELECT panel_id, panel_name, base_url FROM panels")
        panels = await cur.fetchall()

    if not panels:
        await c.message.edit_text("ℹ️ هیچ پنیلی در سیستم ثبت نشده است.", reply_markup=MANAGE_PANELS_KB)
        await c.answer()
        return

    msg = "📜 <b>لیست پنل‌های ثبت‌شده</b>\n\n"
    for panel_id, panel_name, base_url in panels:
        msg += f"🆔 <b>شناسه پنل =</b> <code>{panel_id}</code>\n"
        msg += f"🏷 <b>نام پنل =</b> {safe_text(panel_name)}\n"
        msg += f"🌐 <b>آدرس =</b> {safe_text(base_url)}\n\n"

    await c.message.edit_text(msg, reply_markup=MANAGE_PANELS_KB)
    await c.answer()

@dp.callback_query(F.data == "delete_panel")
async def delete_panel_callback(c: CallbackQuery):
    if c.from_user.id not in SUPERADMINS: return
    
    async with aiosqlite.connect("data.db") as db:
        cur = await db.execute("SELECT panel_id, panel_name FROM panels")
        panels = await cur.fetchall()

    if not panels:
        await c.answer("ℹ️ هیچ پنیلی برای حذف وجود ندارد.", show_alert=True)
        return

    buttons = []
    for panel_id, panel_name in panels:
        buttons.append([InlineKeyboardButton(
            text=f"🆔 {safe_text(panel_name)}",
            callback_data=f"confirm_delete_panel:{panel_id}"
        )])
    buttons.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="back_to_panels_menu")])

    await c.message.edit_text(
        "پنلی که می‌خواهید حذف کنید ، <b>از لیست زیر انتخاب نمایید...</b>\n\n"
        "⚠️ <b>توجه =</b> با حذف پنل، تمام نمایندگان فروش  و دسترسی‌های مربوط به اینباند‌های آن پنل نیز <b>به طور کامل حذف خواهند شد.</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await c.answer()

@dp.callback_query(F.data.startswith("confirm_delete_panel:"))
async def confirm_delete_panel(c: CallbackQuery):
    if c.from_user.id not in SUPERADMINS: return
    try:
        panel_id_to_delete = int(c.data.split(":")[1])
    except (IndexError, ValueError):
        await c.answer("❌ شناسه پنل نامعتبر است.", show_alert=True)
        return

    async with aiosqlite.connect("data.db") as db:
        cursor = await db.execute("SELECT panel_name FROM panels WHERE panel_id = ?", (panel_id_to_delete,))
        panel = await cursor.fetchone()
        if not panel:
            await c.answer("❌ پنل مورد نظر یافت نشد.", show_alert=True)
            return

        await db.execute("DELETE FROM panels WHERE panel_id = ?", (panel_id_to_delete,))
        await db.commit()

    await c.message.edit_text(
        f"✅ پنل '<b>{safe_text(panel[0])}</b>' و تمام داده‌های مرتبط با آن با موفقیت حذف شد.",
        reply_markup=MANAGE_PANELS_KB
    )
    await c.answer()

@dp.callback_query(F.data == "back_to_panels_menu")
async def back_to_panels_menu(c: CallbackQuery):
    if c.from_user.id not in SUPERADMINS: return
    await c.message.edit_text("🎛 <b>مدیریت پنل‌ها</b>", reply_markup=MANAGE_PANELS_KB)
    await c.answer()

# ---------------- Panel Input Handlers ----------------
@dp.message(F.text & ~F.command(), lambda m: m.from_user.id in SUPERADMINS and current_action.get(m.from_user.id, (None, None))[0] == "get_panel_name")
async def handle_panel_name(m: Message):
    admin_id = m.from_user.id
    panel_name = m.text.strip()
    
    if len(panel_name) < 2:
        await m.answer("❌ نام پنل باید حداقل 2 کاراکتر باشد.")
        return
    
    current_action[admin_id] = ("get_panel_base_url", {"panel_name": panel_name})
    await m.answer(
        f"✅ نام پنل '<b>{safe_text(panel_name)}</b>' ثبت شد.\n\n"
        "🌐 حالا <b>آدرس پایه</b> پنل را وارد کنید...\n\n"
        "مثال = <b>https://panel.example.com</b>",
        parse_mode="HTML"
    )

@dp.message(F.text & ~F.command(), lambda m: m.from_user.id in SUPERADMINS and current_action.get(m.from_user.id, (None, None))[0] == "get_panel_base_url")
async def handle_panel_base_url(m: Message):
    admin_id = m.from_user.id
    base_url = m.text.strip().rstrip("/")
    
    if not base_url.startswith(('http://', 'https://')):
        await m.answer("❌ آدرس باید با http:// یا https:// شروع شود.")
        return
    
    data = current_action[admin_id][1]
    data["base_url"] = base_url
    current_action[admin_id] = ("get_panel_web_path", data)
    
    await m.answer(
        f"✅ آدرس پایه '<b>{safe_text(base_url)}</b>' ثبت شد.\n\n"
        "📁 حالا مسیر <b>WebPath</b>  ( اختیاری ) را وارد کنید...\n\n"
        "مثال = <b>/panel</b>\n"
        "اگر ندارید، فقط <b>[ / ]</b>  را به تنهایی ارسال نمایید !",
        parse_mode="HTML"
    )

@dp.message(F.text & ~F.command(), lambda m: m.from_user.id in SUPERADMINS and current_action.get(m.from_user.id, (None, None))[0] == "get_panel_web_path")
async def handle_panel_web_path(m: Message):
    admin_id = m.from_user.id
    web_path = m.text.strip().rstrip("/")
    
    data = current_action[admin_id][1]
    data["web_base_path"] = web_path if web_path != "/" else ""
    current_action[admin_id] = ("get_panel_username", data)
    
    await m.answer(
        f"✅ مسیر <b>WebPath</b> ثبت شد.\n\n"
        f"👤 حالا <b>نام کاربری پنل</b> را وارد کنید...",
        parse_mode="HTML"
    )

@dp.message(F.text & ~F.command(), lambda m: m.from_user.id in SUPERADMINS and current_action.get(m.from_user.id, (None, None))[0] == "get_panel_username")
async def handle_panel_username(m: Message):
    admin_id = m.from_user.id
    username = m.text.strip()
    
    if len(username) < 3:
        await m.answer("❌ نام کاربری باید حداقل 3 کاراکتر باشد.")
        return
    
    data = current_action[admin_id][1]
    data["username"] = username
    current_action[admin_id] = ("get_panel_password", data)
    
    await m.answer(
        f"✅ نام کاربری '<b>{safe_text(username)}</b>' ثبت شد.\n\n"
        "🔐 حالا <b>رمز عبور پنل</b> را وارد کنید...",
        parse_mode="HTML"
    )

@dp.message(F.text & ~F.command(), lambda m: m.from_user.id in SUPERADMINS and current_action.get(m.from_user.id, (None, None))[0] == "get_panel_password")
async def handle_panel_password(m: Message):
    admin_id = m.from_user.id
    password = m.text.strip()
    
    if len(password) < 4:
        await m.answer("❌ رمز عبور باید حداقل 4 کاراکتر باشد.")
        return
    
    data = current_action[admin_id][1]
    data["password"] = password
    
    # Try to add the panel
    try:
        async with aiosqlite.connect("data.db") as db:
            await db.execute(
                """INSERT INTO panels (panel_name, base_url, web_base_path, username, password) 
                VALUES (?, ?, ?, ?, ?)""",
                (data["panel_name"], data["base_url"], data["web_base_path"], 
                 data["username"], data["password"])
            )
            await db.commit()
        
        # Test connection
        api = PanelAPI(data["username"], data["password"], data["base_url"], data["web_base_path"])
        if api.login():
            await m.answer(
                f"✅ <b>پنل با موفقیت اضافه شد!</b>\n\n"
                f"🏷 <b>نام =</b> {safe_text(data['panel_name'])}\n"
                f"🌐 <b>آدرس =</b> {safe_text(data['base_url'])}\n"
                f"👤 <b>نام کاربری =</b> {safe_text(data['username'])}\n"
                f"✅ <b>وضعیت تست اتصال به پنل =</b> موفق",
                reply_markup=MANAGE_PANELS_KB,
                parse_mode="HTML"
            )
        else:
            await m.answer(
                f"⚠️ <b>پنل اضافه شد اما اتصال ناموفق است!</b>\n\n"
                f"لطفاً اطلاعات ورود را بررسی کنید.\n"
                f"🏷 <b>نام =</b> {safe_text(data['panel_name'])}\n"
                f"🌐 <b>آدرس =</b> {safe_text(data['base_url'])}",
                reply_markup=MANAGE_PANELS_KB,
                parse_mode="HTML"
            )
            
    except Exception as e:
        log_error(e)
        await m.answer(
            f"❌ خطا در اضافه کردن پنل:\n<code>{str(e)}</code>",
            reply_markup=MANAGE_PANELS_KB,
            parse_mode="HTML"
        )
    
    del current_action[admin_id]

# ---------------- Reseller Management ----------------
@dp.message(F.text == "🧑‍💼 نمایندگان فروش")
async def manage_resellers_menu(m: Message):
    if m.from_user.id not in SUPERADMINS:
        return await m.answer("⛔️ این بخش فقط برای سوپرادمین در دسترس است.")
    await m.answer("🧑‍💼 <b>مدیریت نمایندگان فروش</b>\nگزینه مورد نظر را انتخاب کنید:", reply_markup=MANAGE_RESELLERS_KB)

@dp.callback_query(F.data == "add_reseller")
async def add_reseller_callback(c: CallbackQuery):
    if c.from_user.id not in SUPERADMINS: return
    
    async with aiosqlite.connect("data.db") as db:
        cur = await db.execute("SELECT panel_id, panel_name FROM panels")
        panels = await cur.fetchall()

    if not panels:
        await c.answer("❌ ابتدا باید حداقل یک پنل اضافه کنید.", show_alert=True)
        return

    buttons = []
    for panel_id, panel_name in panels:
        buttons.append([InlineKeyboardButton(
            text=f"🏢 {safe_text(panel_name)}",
            callback_data=f"select_panel_for_reseller:add:{panel_id}"
        )])
    buttons.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="back_to_main_menu_superadmin")])

    await c.message.edit_text(
        "پنل منتخب این نماینده رو از لیست زیر انتخاب نمایید.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await c.answer()

@dp.callback_query(F.data.startswith("select_panel_for_reseller:"))
async def select_panel_for_reseller_callback(c: CallbackQuery):
    if c.from_user.id not in SUPERADMINS: return

    try:
        _, action_type, panel_id_str = c.data.split(":")
        panel_id = int(panel_id_str)
    except (ValueError, IndexError):
        await c.answer("❌ داده نامعتبر.", show_alert=True)
        return

    admin_id = c.from_user.id
    data_to_store = {'panel_id': panel_id}

    if action_type == "add":
        current_action[admin_id] = ("get_reseller_id_for_add", data_to_store)
        prompt_message = "🆔 حالا <b>شناسه تلگرام کاربری</b> که می‌خواهید به این پنل به عنوان <b>( نماینده فروش )</b> اضافه شود را ارسال کنید..."
    elif action_type == "edit":
        current_action[admin_id] = ("get_reseller_id_for_edit", data_to_store)
        prompt_message = "🆔 حالا <b>شناسه تلگرام نماینده فروشی</b> که می‌خواهید <b>اینباندهای او را در این پنل</b> ویرایش کنید، ارسال کنید..."
    elif action_type == "delete":
        current_action[admin_id] = ("get_reseller_id_for_delete", data_to_store)
        prompt_message = "🆔 <b>شناسه تلگرام نماینده فروشی</b> که می‌خواهید <b>از این پنل حذف شود</b> را ارسال کنید..."
    else:
        return

    await c.message.edit_text(prompt_message)
    await c.answer()

@dp.message(F.text & ~F.command(), lambda m: m.from_user.id in SUPERADMINS and current_action.get(m.from_user.id, (None, None))[0] == "get_reseller_id_for_add")
async def handle_reseller_id_for_add(m: Message):
    admin_id = m.from_user.id
    try:
        reseller_id = int(m.text.strip())
    except ValueError:
        await m.answer("❌ لطفاً یک شماره معتبر وارد کنید.")
        return

    data = current_action[admin_id][1]
    data['reseller_id'] = reseller_id
    current_action[admin_id] = ("assign_inbound_for_add", data)
    
    await m.answer(
        f"✅ کاربر با شناسه [ <code>{reseller_id}</code> ] برای افزودن به عنوان نماینده فروش انتخاب شد.\n"
        f"در این مرحله <b>شناسه اینباندهایی</b> که می‌خواهید به <b>این کاربر اختصاص دهید</b>، را ارسال کنید...\n"
        f"می‌توانید شناسه اینباند ها را با [ , ] از هم جدا کنید !\n"
        f"مثال = <b>1, 2, 3, ...</b>",
        parse_mode="HTML"
    )

@dp.message(F.text & ~F.command(), lambda m: m.from_user.id in SUPERADMINS and current_action.get(m.from_user.id, (None, None))[0] == "assign_inbound_for_add")
async def handle_inbound_for_add(m: Message):
    admin_id = m.from_user.id
    inbound_text = m.text.strip()
    
    try:
        # Split and clean inbound IDs
        inbound_ids = [int(x.strip()) for x in inbound_text.split(",") if x.strip().isdigit()]
        if not inbound_ids:
            await m.answer("❌ هیچ شناسه اینباند معتبری یافت نشد.")
            return
        
        data = current_action[admin_id][1]
        panel_id = data['panel_id']
        reseller_id = data['reseller_id']
        
        # Verify panel exists and get inbounds
        api = await get_panel_api(panel_id)
        if not api:
            await m.answer("❌ خطا در اتصال به پنل.")
            return
        
        all_inbounds = api.inbounds()
        available_inbound_ids = [ib['id'] for ib in all_inbounds if isinstance(ib, dict) and 'id' in ib]
        
        # Filter valid inbounds
        valid_inbounds = [iid for iid in inbound_ids if iid in available_inbound_ids]
        invalid_inbounds = [iid for iid in inbound_ids if iid not in available_inbound_ids]
        
        if not valid_inbounds:
            await m.answer(
                f"❌ هیچ‌کدام از شناسه‌های واردشده معتبر نیست.\n"
                f"اینباندهای موجود در پنل: {', '.join(map(str, available_inbound_ids))}"
            )
            return
        
        # Add to database
        async with aiosqlite.connect("data.db") as db:
            for inbound_id in valid_inbounds:
                try:
                    await db.execute(
                        "INSERT INTO reseller_inbounds (telegram_id, panel_id, inbound_id) VALUES (?, ?, ?)",
                        (reseller_id, panel_id, inbound_id)
                    )
                except aiosqlite.IntegrityError:
                    # Already exists, skip
                    pass
            await db.commit()
        
        success_msg = f"✅ <b>{len(valid_inbounds)} اینباند</b> با موفقیت به کاربر <code>{reseller_id}</code> اختصاص یافت."
        if invalid_inbounds:
            success_msg += f"\n\n⚠️ <b>{len(invalid_inbounds)} شناسه نامعتبر</b> نادیده گرفته شد."
        
        await m.answer(
            success_msg + "\n\nکاربر حالا می‌تواند گزارشات مربوط به این اینباند‌ها را دریافت کند.",
            reply_markup=MANAGE_RESELLERS_KB,
            parse_mode="HTML"
        )
        
    except Exception as e:
        log_error(e)
        await m.answer(f"❌ خطا در اختصاص اینباند: {str(e)}")
    
    del current_action[admin_id]

@dp.callback_query(F.data == "list_resellers")
async def list_resellers_callback(c: CallbackQuery):
    if c.from_user.id not in SUPERADMINS: return
    
    async with aiosqlite.connect("data.db") as db:
        cur = await db.execute("""
            SELECT r.telegram_id, p.panel_name, GROUP_CONCAT(r.inbound_id) as inbounds
            FROM reseller_inbounds r
            JOIN panels p ON r.panel_id = p.panel_id
            GROUP BY r.telegram_id, p.panel_id
            ORDER BY r.telegram_id
        """)
        resellers = await cur.fetchall()

    if not resellers:
        await c.message.edit_text("ℹ️ هیچ نماینده ای یافت نشد.", reply_markup=MANAGE_RESELLERS_KB)
        await c.answer()
        return

    msg = "📜 <b>لیست نمایندگان فروش شما</b>\n\n"
    current_user = None
    for reseller_id, panel_name, inbounds in resellers:
        if current_user != reseller_id:
            if current_user is not None:
                msg += "\n\n"
            msg += f"   👤 <b>کاربر [ <code>{reseller_id}</code> ]</b>\n"
            current_user = reseller_id
        
        msg += f"  📦 <b>{safe_text(panel_name)} =</b> [ <code>{inbounds or 'هیچ'}</code> ]\n"

    await c.message.edit_text(msg, reply_markup=MANAGE_RESELLERS_KB, parse_mode="HTML")
    await c.answer()

@dp.callback_query(F.data == "delete_reseller")
async def delete_reseller_callback(c: CallbackQuery):
    if c.from_user.id not in SUPERADMINS: return

    async with aiosqlite.connect("data.db") as db:
        cur = await db.execute("""
            SELECT DISTINCT p.panel_id, p.panel_name
            FROM panels p
            JOIN reseller_inbounds ri ON p.panel_id = ri.panel_id
        """)
        panels_with_resellers = await cur.fetchall()

    if not panels_with_resellers:
        await c.answer("❌ هیچ نماینده فروشی یافت نشد", show_alert=True)
        return

    buttons = []
    for panel_id, panel_name in panels_with_resellers:
        buttons.append([InlineKeyboardButton(
            text=f"🏢 {safe_text(panel_name)}",
            callback_data=f"select_panel_for_reseller:delete:{panel_id}"
        )])
    buttons.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="back_to_main_menu_superadmin")])

    await c.message.edit_text(
        "نماینده را از کدام پنل حذف میکنید ؟",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await c.answer()

# ============ Edit Reseller Implementation ============

@dp.callback_query(F.data == "edit_reseller")
async def edit_reseller_callback(c: CallbackQuery):
    """نمایش لیست پنل‌ها برای انتخاب جهت ویرایش نماینده"""
    if c.from_user.id not in SUPERADMINS: 
        return

    async with aiosqlite.connect("data.db") as db:
        cur = await db.execute("""
            SELECT DISTINCT p.panel_id, p.panel_name
            FROM panels p
            JOIN reseller_inbounds ri ON p.panel_id = ri.panel_id
        """)
        panels_with_resellers = await cur.fetchall()

    if not panels_with_resellers:
        await c.answer("❌ هیچ نماینده فروشی یافت نشد", show_alert=True)
        return

    buttons = []
    for panel_id, panel_name in panels_with_resellers:
        buttons.append([InlineKeyboardButton(
            text=f"🏢 {safe_text(panel_name)}",
            callback_data=f"select_panel_for_reseller:edit:{panel_id}"
        )])
    buttons.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="back_to_main_menu_superadmin")])

    await c.message.edit_text(
        "📝 پنل مورد نظر برای ویرایش نماینده را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await c.answer()


@dp.message(F.text & ~F.command(), 
            lambda m: m.from_user.id in SUPERADMINS and 
            current_action.get(m.from_user.id, (None, None))[0] == "get_reseller_id_for_edit")
async def handle_reseller_id_for_edit(m: Message):
    """دریافت شناسه نماینده برای ویرایش و نمایش لیست نمایندگان"""
    admin_id = m.from_user.id
    data = current_action[admin_id][1]
    panel_id = data['panel_id']
    
    try:
        reseller_id = int(m.text.strip())
    except ValueError:
        await m.answer("❌ لطفاً یک شماره معتبر وارد کنید.")
        return

    # بررسی وجود نماینده در این پنل
    async with aiosqlite.connect("data.db") as db:
        cur = await db.execute(
            "SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=? AND panel_id=?",
            (reseller_id, panel_id)
        )
        inbounds = await cur.fetchall()

    if not inbounds:
        await m.answer(
            f"❌ کاربر <code>{reseller_id}</code> در این پنل نماینده فروش نیست.",
            reply_markup=MANAGE_RESELLERS_KB,
            parse_mode="HTML"
        )
        del current_action[admin_id]
        return

    # نمایش اینباندهای فعلی
    current_inbounds = [str(row[0]) for row in inbounds]
    inbound_list = ", ".join(current_inbounds)

    # ذخیره اطلاعات برای مرحله بعد
    data['reseller_id'] = reseller_id
    data['current_inbounds'] = current_inbounds
    current_action[admin_id] = ("get_new_inbounds_for_edit", data)

    await m.answer(
        f"📋 <b>اینباندهای فعلی کاربر</b> [ <code>{reseller_id}</code> ]\n\n"
        f"<code>{inbound_list}</code>\n\n"
        f"🔄 <b>اینباندهای جدید را وارد کنید...</b>\n"
        f"   • برای چند اینباند از کاما استفاده کنید\n"
        f"   • مثال = <b>1, 2, 3, ...</b>\n\n"
        f"💡 اینباندهای جدید جایگزین اینباندهای قبلی می‌شوند.",
        parse_mode="HTML"
    )


@dp.message(F.text & ~F.command(), 
            lambda m: m.from_user.id in SUPERADMINS and 
            current_action.get(m.from_user.id, (None, None))[0] == "get_new_inbounds_for_edit")
async def handle_new_inbounds_for_edit(m: Message):
    """دریافت اینباندهای جدید و ویرایش نماینده"""
    admin_id = m.from_user.id
    data = current_action[admin_id][1]
    panel_id = data['panel_id']
    reseller_id = data['reseller_id']

    try:
        # پارس کردن اینباندهای جدید
        inbound_ids_str = [x.strip() for x in m.text.strip().split(",")]
        inbound_ids = [int(x) for x in inbound_ids_str if x]
    except ValueError:
        await m.answer("❌ فرمت نادرست! لطفاً فقط اعداد وارد کنید (مثال: 1,2,3)")
        return

    if not inbound_ids:
        await m.answer("❌ حداقل یک شناسه اینباند باید وارد شود.")
        return

    # اعتبارسنجی اینباندها با API
    try:
        async with aiosqlite.connect("data.db") as db:
            cur = await db.execute(
                "SELECT base_url, web_base_path, username, password FROM panels WHERE panel_id = ?",
                (panel_id,)
            )
            panel_info = await cur.fetchone()

        if not panel_info:
            await m.answer("❌ پنل یافت نشد!")
            del current_action[admin_id]
            return

        base_url, web_base_path, username, password = panel_info
        api = PanelAPI(username, password, base_url, web_base_path or "")
        
        if not api.login():
            await m.answer("❌ خطا در اتصال به پنل!")
            del current_action[admin_id]
            return

        # دریافت لیست اینباندهای موجود
        inbounds = api.inbounds()
        valid_inbound_ids = {ib.get('id') for ib in inbounds if isinstance(ib, dict) and 'id' in ib}

        # جداسازی معتبر و نامعتبر
        valid_inbounds = [iid for iid in inbound_ids if iid in valid_inbound_ids]
        invalid_inbounds = [iid for iid in inbound_ids if iid not in valid_inbound_ids]

        if not valid_inbounds:
            await m.answer(
                "❌ هیچ یک از شناسه‌های وارد شده معتبر نیستند!\n\n"
                f"شناسه‌های نامعتبر: <code>{', '.join(map(str, invalid_inbounds))}</code>",
                parse_mode="HTML"
            )
            return

        # بروزرسانی در دیتابیس
        async with aiosqlite.connect("data.db") as db:
            # حذف اینباندهای قبلی
            await db.execute(
                "DELETE FROM reseller_inbounds WHERE telegram_id=? AND panel_id=?",
                (reseller_id, panel_id)
            )
            
            # اضافه کردن اینباندهای جدید
            for inbound_id in valid_inbounds:
                await db.execute(
                    "INSERT OR IGNORE INTO reseller_inbounds (telegram_id, panel_id, inbound_id) VALUES (?, ?, ?)",
                    (reseller_id, panel_id, inbound_id)
                )
            await db.commit()

        # پیام موفقیت
        success_msg = (
            f"✅ اینباندهای کاربر [ <code>{reseller_id}</code> ] با موفقیت بروزرسانی شد!\n\n"
            f"📋 <b>اینباندهای جدید =</b> <code>{', '.join(map(str, valid_inbounds))}</code>"
        )
        
        if invalid_inbounds:
            success_msg += f"\n\n⚠️ <b>شناسه‌های نامعتبر (نادیده گرفته شد):</b>\n<code>{', '.join(map(str, invalid_inbounds))}</code>"

        await m.answer(
            success_msg,
            reply_markup=MANAGE_RESELLERS_KB,
            parse_mode="HTML"
        )

    except Exception as e:
        log_error(e)
        await m.answer(f"❌ خطا در ویرایش اینباندها: {str(e)}")

    del current_action[admin_id]

@dp.message(F.text & ~F.command(), lambda m: m.from_user.id in SUPERADMINS and current_action.get(m.from_user.id, (None, None))[0] == "get_reseller_id_for_delete")
async def handle_reseller_id_for_delete(m: Message):
    admin_id = m.from_user.id
    try:
        reseller_id = int(m.text.strip())
    except ValueError:
        await m.answer("❌ لطفاً یک شماره معتبر وارد کنید.")
        return

    data = current_action[admin_id][1]
    panel_id = data['panel_id']
    
    # Check if reseller exists in this panel
    async with aiosqlite.connect("data.db") as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM reseller_inbounds WHERE telegram_id=? AND panel_id=?",
            (reseller_id, panel_id)
        )
        count = await cur.fetchone()
        
        if count[0] == 0:
            await m.answer(
                f"❌ کاربر <code>{reseller_id}</code> در این پنل نماینده فروش نیست.",
                reply_markup=MANAGE_RESELLERS_KB,
                parse_mode="HTML"
            )
            del current_action[admin_id]
            return
        
        # Delete the reseller from this panel
        await db.execute(
            "DELETE FROM reseller_inbounds WHERE telegram_id=? AND panel_id=?",
            (reseller_id, panel_id)
        )
        await db.commit()
    
    await m.answer(
        f"✅ تمام دسترسی‌های کاربر [ <code>{reseller_id}</code> ] از پنل حذف شد.",
        reply_markup=MANAGE_RESELLERS_KB,
        parse_mode="HTML"
    )
    del current_action[admin_id]

# ---------------- Report Generation (اصلاح‌شده و async) ----------------
def now_shamsi_str() -> str:
    """
    برگرداندن تاریخ و ساعت فعلی به شمسی
    فرمت: تاریخ = [ 25 مهر 1404 ] - ساعت = [ 23:17 ]
    """
    tz = ZoneInfo("Asia/Tehran")
    now = datetime.now(tz)
    
    shamsi = jdatetime.datetime.fromgregorian(datetime=now)
    
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
    time_str = shamsi.strftime("%H:%M:%S")
    
    return f"تاریخ = [ {day} {month} {year} ] و ساعت = [ {time_str} ]"

def format_bytes(byte_count: int) -> str:
    """Convert bytes to human readable format with 2 decimal places, rounded up"""
    if byte_count is None: 
        return "N/A"
    
    power = 1024
    n = 0
    power_labels = {0: '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    
    while byte_count >= power and n < len(power_labels) - 1:
        byte_count /= power
        n += 1
    
    # ✅ گرد کردن به بالا با دو رقم اعشار
    rounded_value = math.ceil(byte_count * 100) / 100
    
    return f"{rounded_value:.2f} {power_labels[n]}B"
    
async def build_snapshot(tg_id: int) -> Dict:
    """
    Builds a comprehensive snapshot of user data per panel.
    Returns a dict with panel_id as key and panel data as value.
    """
    panels_snapshot = {}

    try:
        scoped_inbounds = await _get_scope_inbounds_by_panel(tg_id)

        if not scoped_inbounds:
            logging.warning(f"User {tg_id} has no valid panels or inbounds")
            return panels_snapshot

        now = time.time()

        # scoped_inbounds is a dict: {panel_id: [inbound_id1, inbound_id2, ...]}
        for panel_id, panel_inbound_ids in scoped_inbounds.items():
            # Get panel name from database
            async with aiosqlite.connect("data.db") as db:
                cur = await db.execute("SELECT panel_name FROM panels WHERE panel_id = ?", (panel_id,))
                row = await cur.fetchone()
                panel_name = row[0] if row else f"Panel {panel_id}"

            # Initialize snapshot for this panel
            snapshot = {
                "panel_name": panel_name,
                "counts": {"users": 0, "online": 0, "expiring": 0, "expired": 0},
                "lists": {"online": [], "expiring": [], "expired": []},
                "usage": {"used": 0, "capacity": 0, "remaining": 0, "unlimited": False},
                "timestamp": int(time.time())
            }

            processed_emails = set()
            total_inbound_used = 0
            total_inbound_capacity = 0
            has_unlimited = False

            try:
                api = await get_panel_api(panel_id)
                if not api:
                    logging.warning(f"Could not get API for panel {panel_id}, skipping...")
                    continue

                all_inbounds = api.inbounds()
                if not all_inbounds or not isinstance(all_inbounds, list):
                    logging.warning(f"Panel {panel_id}: No valid inbounds data")
                    continue

                online_clients_emails = set(api.online_clients())
                
                # Filter inbounds for this panel
                panel_inbound_set = set(panel_inbound_ids)
                filtered_inbounds = [
                    ib for ib in all_inbounds
                    if isinstance(ib, dict) and 'id' in ib and ib['id'] in panel_inbound_set
                ]
                
                for inbound in filtered_inbounds:
                    inbound_id = inbound.get('id')
                    if not inbound_id:
                        continue

                    # Extract clients from inbound
                    clients = _extract_clients_from_inbound(inbound)

                    if not clients:
                        logging.debug(f"Inbound {inbound_id}: No clients found")
                        continue
                        
                    # ✅ Inbound-level usage
                    ib_up = int(inbound.get("up", 0) or 0)
                    ib_down = int(inbound.get("down", 0) or 0)
                    ib_total = int(inbound.get("total", 0) or 0)

                    total_inbound_used += (ib_up + ib_down)
                    if ib_total == 0:
                        has_unlimited = True
                    else:
                        total_inbound_capacity += ib_total

                    # Process each client
                    for client in clients:
                        try:
                            email = client.get('email', '').strip()
                            if not email or email in processed_emails:
                                continue

                            processed_emails.add(email)
                            snapshot["counts"]["users"] += 1

                            # Online status
                            enable = client.get('enable', True)
                            if enable and email in online_clients_emails:
                                snapshot["counts"]["online"] += 1
                                if email not in snapshot["lists"]["online"]:
                                    snapshot["lists"]["online"].append(email)

                            # Expiration status
                            is_expiring, is_expired = _calc_status_for_client(client, now)

                            if is_expired:
                                snapshot["counts"]["expired"] += 1
                                expired_entry = f"{email}"
                                if expired_entry not in snapshot["lists"]["expired"]:
                                    snapshot["lists"]["expired"].append(expired_entry)
                            elif is_expiring:
                                snapshot["counts"]["expiring"] += 1
                                expiring_entry = f"{email}"
                                if expiring_entry not in snapshot["lists"]["expiring"]:
                                    snapshot["lists"]["expiring"].append(expiring_entry)

                        except Exception as e:
                            logging.warning(f"Error processing client {client.get('email', 'unknown')}: {e}")
                            continue

            except Exception as e:
                log_error(e)
                logging.error(f"Error processing panel {panel_id} for user {tg_id}: {e}")
                continue

            # ✅ Calculate final usage for this panel
            if has_unlimited:
                snapshot["usage"]["capacity"] = 0
                snapshot["usage"]["unlimited"] = True
                snapshot["usage"]["remaining"] = 0
                snapshot["usage"]["used"] = total_inbound_used
            else:
                snapshot["usage"]["used"] = total_inbound_used
                snapshot["usage"]["capacity"] = total_inbound_capacity
                snapshot["usage"]["remaining"] = max(total_inbound_capacity - total_inbound_used, 0)

            panels_snapshot[panel_id] = snapshot

    except Exception as e:
        log_error(e)
        logging.error(f"Error in build_snapshot for user {tg_id}: {e}")

    return panels_snapshot

# ============ Online/Expiring/Expired with Panel Selection ============

# --- Online Users ---
@dp.message(Command("online"))
async def online_cmd(m: Message):
    """نمایش پنل‌ها برای مشاهده کاربران آنلاین"""
    await show_panel_selection_for_status(m, "online")

@dp.message(F.text == "🟢 کاربران آنلاین")
async def btn_online(m: Message):
    await show_panel_selection_for_status(m, "online")


# --- Expiring Users ---
@dp.message(Command("expiring"))
async def expiring_cmd(m: Message):
    """نمایش پنل‌ها برای مشاهده کاربران رو به انقضا"""
    await show_panel_selection_for_status(m, "expiring")

@dp.message(F.text == "⏳ رو به انقضا")
async def btn_expiring(m: Message):
    await show_panel_selection_for_status(m, "expiring")


# --- Expired Users ---
@dp.message(Command("expired"))
async def expired_cmd(m: Message):
    """نمایش پنل‌ها برای مشاهده کاربران منقضی‌شده"""
    await show_panel_selection_for_status(m, "expired")

@dp.message(F.text == "🚫 منقضی‌شده")
async def btn_expired(m: Message):
    await show_panel_selection_for_status(m, "expired")


# --- Helper Function: Show Panel Selection ---
async def show_panel_selection_for_status(m: Message, status_type: str):
    """
    نمایش لیست پنل‌ها برای انتخاب
    status_type: 'online', 'expiring', 'expired'
    """
    panels_snap = await build_snapshot(m.from_user.id)
    
    if not panels_snap:
        await m.answer("ℹ️ هیچ داده‌ای برای نمایش وجود ندارد.")
        return

    # ایموجی و عنوان بر اساس نوع
    status_info = {
        "online": {"emoji": "🟢", "title": "کاربران آنلاین"},
        "expiring": {"emoji": "⏳", "title": "کاربران رو به انقضا"},
        "expired": {"emoji": "🚫", "title": "کاربران منقضی‌شده"}
    }
    
    emoji = status_info[status_type]["emoji"]
    title = status_info[status_type]["title"]

    # ساخت دکمه‌های انتخاب پنل
    buttons = []
    for panel_id, snapshot in panels_snap.items():
        panel_name = snapshot["panel_name"]
        count = snapshot["counts"].get(status_type, 0)
        
        if count > 0:  # فقط پنل‌هایی که کاربر دارند
            buttons.append([InlineKeyboardButton(
                text=f"🏢 {safe_text(panel_name)} ({count})",
                callback_data=f"status_panel:{status_type}:{panel_id}"
            )])
    
    if not buttons:
        await m.answer(f"ℹ️ هیچ کاربر {title} یافت نشد.")
        return

    # دکمه بازگشت
    buttons.append([InlineKeyboardButton(text="🏠 بازگشت به منوی اصلی", callback_data="back_to_main")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await m.answer(
        f"{emoji} <b>انتخاب پنل برای مشاهده {title}</b>\n\n"
        "پنل مورد نظر خود را از لیست زیر انتخاب نمایید...",
        reply_markup=kb,
        parse_mode="HTML"
    )


# --- Callback: Show Users by Panel and Status ---
@dp.callback_query(F.data.startswith("status_panel:"))
async def show_users_by_panel_status(query: CallbackQuery):
    """
    نمایش کاربران یک پنل خاص با وضعیت مشخص
    Format: status_panel:TYPE:PANEL_ID
    """
    try:
        parts = query.data.split(":")
        status_type = parts[1]  # online, expiring, expired
        panel_id = int(parts[2])
    except (IndexError, ValueError):
        await query.answer("❌ خطا در پردازش درخواست", show_alert=True)
        return

    # ایموجی و عنوان
    status_info = {
        "online": {"emoji": "🟢", "title": "کاربران آنلاین"},
        "expiring": {"emoji": "⏳", "title": "کاربران رو به انقضا"},
        "expired": {"emoji": "🚫", "title": "کاربران منقضی‌شده"}
    }
    
    emoji = status_info[status_type]["emoji"]
    title = status_info[status_type]["title"]

    # دریافت اطلاعات
    panels_snap = await build_snapshot(query.from_user.id)
    
    if panel_id not in panels_snap:
        await query.message.edit_text("ℹ️ اطلاعات پنل یافت نشد.")
        await query.answer()
        return

    snapshot = panels_snap[panel_id]
    panel_name = snapshot["panel_name"]
    user_list = snapshot["lists"].get(status_type, [])
    
    if not user_list:
        await query.message.edit_text(
            f"ℹ️ هیچ کاربر {title} در پنل <b>{safe_text(panel_name)}</b> یافت نشد.",
            parse_mode="HTML"
        )
        await query.answer()
        return

    # فرمت پیام
    header = f"{emoji} <b>{title}</b>\n\n   🏢 <b>پنل =</b> {safe_text(panel_name)}\n\n"
    msg = format_list(header, user_list)
    msg += f"\n\n<b>بروزرسانی در </b>{now_shamsi_str()}"

    # دکمه‌های شیشه‌ای
    buttons = []
    
    # ردیف اول: انتخاب پنل‌های دیگر (شیشه‌ای)
    panel_buttons = []
    for pid, snap in panels_snap.items():
        count = snap["counts"].get(status_type, 0)
        if count > 0:
            panel_buttons.append(InlineKeyboardButton(
                text="🔘" if pid == panel_id else "⚪️",
                callback_data=f"status_panel:{status_type}:{pid}"
            ))
    
    # تقسیم به چند ردیف اگر زیاد بودند (حداکثر 4 دکمه در هر ردیف)
    for i in range(0, len(panel_buttons), 4):
        buttons.append(panel_buttons[i:i+4])

    # ردیف دوم: بروزرسانی
    buttons.append([InlineKeyboardButton(
        text="♻️ بروزرسانی به آخرین وضعیت",
        callback_data=f"refresh_status:{status_type}:{panel_id}"
    )])

    # ردیف سوم: بازگشت
    buttons.append([InlineKeyboardButton(
        text="⬅️ بازگشت به لیست پنل‌ها",
        callback_data=f"back_to_panel_list:{status_type}"
    )])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await query.message.edit_text(msg, reply_markup=kb, parse_mode="HTML")
    await query.answer()


# --- Callback: Refresh Status ---
@dp.callback_query(F.data.startswith("refresh_status:"))
async def refresh_status(query: CallbackQuery):
    """
    بروزرسانی لیست کاربران با وضعیت مشخص
    Format: refresh_status:TYPE:PANEL_ID
    """
    try:
        parts = query.data.split(":")
        status_type = parts[1]
        panel_id = int(parts[2])
    except (IndexError, ValueError):
        await query.answer("❌ خطا در پردازش درخواست", show_alert=True)
        return

    # استفاده مجدد از تابع نمایش
    await show_users_by_panel_status(query)
    await query.answer("✅ بروزرسانی شد", show_alert=False)


# --- Callback: Back to Panel List ---
@dp.callback_query(F.data.startswith("back_to_panel_list:"))
async def back_to_panel_list(query: CallbackQuery):
    """
    بازگشت به لیست پنل‌ها
    Format: back_to_panel_list:TYPE
    """
    try:
        status_type = query.data.split(":")[1]
    except IndexError:
        await query.answer("❌ خطا در پردازش درخواست", show_alert=True)
        return

    # ساخت مجدد لیست پنل‌ها
    panels_snap = await build_snapshot(query.from_user.id)
    
    if not panels_snap:
        await query.message.edit_text("ℹ️ هیچ داده‌ای برای نمایش وجود ندارد.")
        await query.answer()
        return

    status_info = {
        "online": {"emoji": "🟢", "title": "کاربران آنلاین"},
        "expiring": {"emoji": "⏳", "title": "کاربران رو به انقضا"},
        "expired": {"emoji": "🚫", "title": "کاربران منقضی‌شده"}
    }
    
    emoji = status_info[status_type]["emoji"]
    title = status_info[status_type]["title"]

    buttons = []
    for panel_id, snapshot in panels_snap.items():
        panel_name = snapshot["panel_name"]
        count = snapshot["counts"].get(status_type, 0)
        
        if count > 0:
            buttons.append([InlineKeyboardButton(
                text=f"🏢 {safe_text(panel_name)} ({count})",
                callback_data=f"status_panel:{status_type}:{panel_id}"
            )])
    
    if not buttons:
        await query.message.edit_text(f"ℹ️ هیچ کاربر {title} یافت نشد.")
        await query.answer()
        return

    buttons.append([InlineKeyboardButton(text="🏠 بازگشت به منوی اصلی", callback_data="back_to_main")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await query.message.edit_text(
        f"{emoji} <b>انتخاب پنل برای مشاهده {title}</b>\n\n"
        "پنل مورد نظر را از لیست زیر انتخاب نمایید...",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await query.answer()


# --- Callback: Back to Main Menu ---
@dp.callback_query(F.data == "back_to_main")
async def back_to_main(query: CallbackQuery):
    """بازگشت به منوی اصلی"""
    await query.message.delete()
    await query.message.answer(
        "🏠 به منوی اصلی بازگشتید.",
        reply_markup=get_main_kb(query.from_user.id)
    )
    await query.answer()

def format_panel_report(panel_name: str, counts: Dict[str, int], usage: Dict, is_superadmin: bool = False) -> str:
    """Format report for a single panel"""
    used_str = format_bytes(usage.get("used", 0))

    if usage.get("unlimited", False):
        remaining_str = "نامحدود"
        capacity_line = ""
    else:
        remaining_str = format_bytes(usage.get("remaining", 0))
        capacity_line = f"💾 <b>حجم باقی‌مانده:</b> [ {remaining_str} ]\n"

    if is_superadmin:
        header = f"📊 <b>گزارشات مربوط به پنل - [ {safe_text(panel_name)} ]</b>\n\n"
    else:
        header = f"📊 <b>گزارشات مربوط به حساب نمایندگی</b>\n🏷 <b>نام پنل =</b> [ {safe_text(panel_name)} ]\n\n"

    return (
        header +
        f"📈 <b>مصرف کل=</b> [ {used_str} ]\n" +
        capacity_line +
        f"👥 <b>کل کاربران =</b> [ {counts.get('users', 0)} ]\n"
        f"🟢 <b>کاربران آنلاین =</b> [ {counts.get('online', 0)} ]\n"
        f"⏳ <b>رو به انقضا =</b> [ {counts.get('expiring', 0)} ]\n"
        f"🚫 <b>منقضی شده =</b> [ {counts.get('expired', 0)} ]"
    )

def format_main_report(counts: Dict[str,int], usage: Dict) -> str:
    used_str = format_bytes(usage.get("used", 0))

    if usage.get("unlimited", False):
        remaining_str = "نامحدود"
    else:
        remaining_str = format_bytes(usage.get("remaining", 0))

    return (
        "📊 <b>گزارش نهایی از وضعیت فعلی شما :</b>\n\n"
        f"📈 <b>مصرف کل =</b> [ {used_str} ]\n"
        f"💾 <b>حجم باقی‌مانده =</b> [ {remaining_str} ]\n\n"
        f"👥 <b>کل کاربران =</b> [ {counts.get('users',0)} ]\n"
        f"🟢 <b>کاربران آنلاین =</b> [ {counts.get('online',0)} ]\n"
        f"⏳ <b>رو به انقضا =</b> [ {counts.get('expiring',0)} ]\n"
        f"🚫 <b>منقضی شده =</b> [ {counts.get('expired',0)} ]"
    )

def format_list(header_title: str, items: List[str]) -> str:
    msg = f"{header_title} [ {len(items)} ]\n\n"
    if items:
        msg += "\n".join([f"👤 - [ <code>{safe_text(u)}</code> ]" for u in items])
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
        return

    is_new = await ensure_user_and_check_new(m.from_user.id)
    kb = get_main_kb(m.from_user.id)
    await m.answer("👋 به ربات گزارش‌دهی X-UI خوش آمدید!", reply_markup=kb)

    if is_new:
        u = m.from_user
        fullname = (u.first_name or "") + ((" " + u.last_name) if u.last_name else "")
        username = f"@{u.username}" if u.username else "N/A"
        uid = u.id
        date_str = now_shamsi_str()
        txt = (
            f"👤 <b>یک کاربر جدید</b> با مشخصات زیر، عضو ربات شد...!\n\n"
            f"📛 <b>نام =</b> {safe_text(fullname)}\n"
            f"🆔 <b>یوزرنیم =</b> {username}\n"
            f"🔢 <b>آیدی =</b> [ <code>{uid}</code> ]\n"
            f"📅 <b>عضویت در =</b> {date_str}"
        )

        for admin_id in SUPERADMINS:
            try:
                await bot.send_message(admin_id, txt, parse_mode="HTML")
            except Exception as e:
                log_error(e)

@dp.message(Command("report"))
async def report_cmd(m: Message):
    panels_snap = await build_snapshot(m.from_user.id)
    
    if not panels_snap:
        await m.answer("ℹ️ هیچ داده‌ای برای نمایش وجود ندارد.\n\n🔍 ممکن است:\n• هنوز اینبندی به شما اختصاص داده نشده باشد\n• یا اینباندهای اختصاص‌یافته خالی باشند")
        return

    is_superadmin = m.from_user.id in SUPERADMINS
    timestamp = now_shamsi_str()
    
    # Send separate report for each panel
    for panel_id, snapshot in panels_snap.items():
        if snapshot["counts"]["users"] == 0:
            continue
            
        msg = format_panel_report(
            snapshot["panel_name"],
            snapshot["counts"],
            snapshot["usage"],
            is_superadmin
        ) + f"\n\n<b>بروزرسانی در</b> {timestamp}"
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(
                text="♻️ بروزرسانی به آخرین وضعیت",
                callback_data=f"refresh_report:{panel_id}"
            )]]
        )
        await m.answer(msg, reply_markup=kb, parse_mode="HTML")
        await asyncio.sleep(0.3)  # Avoid rate limit

@dp.callback_query(F.data.startswith("refresh_report:"))
async def refresh_report(query: CallbackQuery):
    try:
        panel_id = int(query.data.split(":")[1])
    except (IndexError, ValueError):
        await query.answer("❌ خطا در شناسایی پنل", show_alert=True)
        return
    
    panels_snap = await build_snapshot(query.from_user.id)
    
    if panel_id not in panels_snap:
        await query.message.edit_text("ℹ️ هیچ داده‌ای برای نمایش وجود ندارد.")
        await query.answer()
        return
    
    snapshot = panels_snap[panel_id]
    
    if snapshot["counts"]["users"] == 0:
        await query.message.edit_text("ℹ️ هیچ داده‌ای برای نمایش وجود ندارد.")
        await query.answer()
        return

    is_superadmin = query.from_user.id in SUPERADMINS
    new_msg = format_panel_report(
        snapshot["panel_name"],
        snapshot["counts"],
        snapshot["usage"],
        is_superadmin
    ) + f"\n\nبروزرسانی در {now_shamsi_str()}"
    
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(
            text="♻️ بروزرسانی به آخرین وضعیت",
            callback_data=f"refresh_report:{panel_id}"
        )]]
    )
    
    if query.message.text != new_msg:
        await query.message.edit_text(new_msg, reply_markup=kb, parse_mode="HTML")
        await query.answer("✅ بروزرسانی شد", show_alert=False)
    else:
        await query.answer("ℹ️ بدون تغییر", show_alert=False)

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

# ---------------- Full Reports & Change Notifications ----------------

def _format_expiring_msg_super_with_panel(name: str, panel_name: str) -> str:
    return (
        "📢 <b>مدیر محترم ... </b>\n\n"
        "⏳ اشتراک با مشخصات زیر، <b>[ بزودی ]</b> منقضی خواهد شد ... \n\n"
        f"🏢 <b>پنل =</b> [ {safe_text(panel_name)} ]\n"
        f"👥 <b>کاربر =</b> [ <code>{safe_text(name)}</code> ]\n\n"
        "+ <b>درصورت تمایل ، نسبت به شارژ مجدد از داخل پنل کاربری خود اقدام کنید </b>"
    )

def _format_expired_msg_super_with_panel(name: str, panel_name: str) -> str:
    return (
        "📢 <b>مدیر محترم ... </b>\n\n"
        "🚫 اشتراک با مشخصات زیر ، <b>[ منقضی ]</b> گردیده است ... \n\n"
        f"🏢 <b>پنل =</b> [ {safe_text(panel_name)} ]\n"
        f"👥 <b>کاربر =</b> [ <code>{safe_text(name)}</code> ]\n\n"
        "+ <b>درصورت تمایل ، نسبت به شارژ مجدد از داخل پنل کاربری خود اقدام کنید </b>"
    )

def _format_expiring_msg_reseller_with_panel(name: str, panel_name: str) -> str:
    return (
        "📢 <b>نماینده محترم ... </b>\n\n"
        "⏳ اشتراک با مشخصات زیر، <b>[ بزودی ]</b> منقضی خواهد شد ... \n\n"
        f"🏢 <b>پنل =</b> [ {safe_text(panel_name)} ]\n"
        f"👥 <b>کاربر =</b> [ <code>{safe_text(name)}</code> ]\n\n"
        "+ <b>درصورت تمایل ، نسبت به شارژ مجدد کاربر خود اقدام کنید </b>"
    )

def _format_expired_msg_reseller_with_panel(name: str, panel_name: str) -> str:
    return (
        "📢 <b>نماینده محترم ... </b>\n\n"
        "🚫 اشتراک با مشخصات زیر ، <b>[ منقضی ]</b> گردیده است ... \n\n"
        f"🏢 <b>پنل =</b> [ {safe_text(panel_name)} ]\n"
        f"👥 <b>کاربر =</b> [ <code>{safe_text(name)}</code> ]\n\n"
        "+ <b>درصورت تمایل ، نسبت به شارژ مجدد کاربر خود اقدام کنید </b>"
    )

async def send_full_reports():
    """Sends daily full reports to resellers and superadmins - one message per panel."""
    try:
        users_to_report = set(SUPERADMINS)

        async with aiosqlite.connect("data.db") as db:
            cur = await db.execute("SELECT DISTINCT telegram_id FROM reseller_inbounds")
            rows = await cur.fetchall()
            for (tg_id,) in rows:
                users_to_report.add(tg_id)

        for tg_id in users_to_report:
            try:
                panels_snap = await build_snapshot(tg_id)

                if not panels_snap:
                    logging.info(f"Skipping report for {tg_id}: No panels found")
                    continue

                is_superadmin = tg_id in SUPERADMINS
                timestamp = now_shamsi_str()

                # Send one message per panel
                for panel_id, snapshot in panels_snap.items():
                    if snapshot["counts"]["users"] == 0:
                        continue

                    report = format_panel_report(
                        snapshot["panel_name"],
                        snapshot["counts"],
                        snapshot["usage"],
                        is_superadmin
                    ) + f"\n\nبروزرسانی در {timestamp}"
                    
                    kb = InlineKeyboardMarkup(
                        inline_keyboard=[[InlineKeyboardButton(
                            text="♻️ بروزرسانی به آخرین وضعیت",
                            callback_data=f"refresh_report:{panel_id}"
                        )]]
                    )

                    await bot.send_message(tg_id, report, reply_markup=kb, parse_mode="HTML")
                    await asyncio.sleep(0.5)  # Rate limit

                # Update last report in DB (store all panels data)
                async with aiosqlite.connect("data.db") as db:
                    await db.execute(
                        "INSERT OR REPLACE INTO last_reports(telegram_id, last_json, last_full_report) VALUES (?, ?, ?)",
                        (tg_id, json.dumps(panels_snap), int(time.time()))
                    )
                    await db.commit()

            except TelegramForbiddenError:
                logging.warning(f"❌ User {tg_id} has blocked the bot")
            except Exception as e:
                log_error(e)
                logging.error(f"Failed to send report to {tg_id}: {e}")

    except Exception as e:
        log_error(e)
        logging.error(f"Error in send_full_reports: {e}")

    logging.info("✅ Daily Reports Completed.")

async def check_for_changes():
    """
    Periodically checks for changes in user statuses (expiring/expired).
    Sends notifications if new users are detected in those categories.
    """
    logging.info("🔍 Checking for Changes in user Statuses...")

    try:
        users_to_check = set(SUPERADMINS)

        async with aiosqlite.connect("data.db") as db:
            cur = await db.execute("SELECT DISTINCT telegram_id FROM reseller_inbounds")
            rows = await cur.fetchall()
            for (tg_id,) in rows:
                users_to_check.add(tg_id)

        for tg_id in users_to_check:
            try:
                is_super = tg_id in SUPERADMINS

                # ✅ Build current snapshot (per panel)
                current_panels_snap = await build_snapshot(tg_id)
                
                # ✅ Check if snapshot is empty
                if not current_panels_snap:
                    logging.info(f"User {tg_id}: No panels or data, skipping change detection")
                    continue

                # Load previous snapshot
                async with aiosqlite.connect("data.db") as db:
                    cur = await db.execute(
                        "SELECT last_json FROM last_reports WHERE telegram_id=?",
                        (tg_id,)
                    )
                    row = await cur.fetchone()

                if not row or not row[0]:
                    # First time - store current snapshot
                    async with aiosqlite.connect("data.db") as db:
                        await db.execute(
                            "INSERT OR REPLACE INTO last_reports(telegram_id, last_json, last_full_report) VALUES (?, ?, ?)",
                            (tg_id, json.dumps(current_panels_snap), int(time.time()))
                        )
                        await db.commit()
                    logging.info(f"User {tg_id} = First SnapShot stored")
                    continue

                try:
                    prev_panels_snap = json.loads(row[0])
                except (json.JSONDecodeError, TypeError):
                    prev_panels_snap = {}

                # ✅ Compare per panel
                for panel_id, current_snap in current_panels_snap.items():
                    panel_id_str = str(panel_id)
                    
                    # Check if we have counts in current snapshot
                    if "counts" not in current_snap or "lists" not in current_snap:
                        logging.warning(f"User {tg_id}, Panel {panel_id}: Invalid snapshot structure")
                        continue
                    
                    prev_snap = prev_panels_snap.get(panel_id_str, {})
                    
                    # If no previous data for this panel, skip notifications
                    if not prev_snap or "lists" not in prev_snap:
                        continue

                    current_expiring = set(current_snap["lists"].get("expiring", []))
                    current_expired = set(current_snap["lists"].get("expired", []))
                    
                    prev_expiring = set(prev_snap["lists"].get("expiring", []))
                    prev_expired = set(prev_snap["lists"].get("expired", []))

                    # Find newly expiring and expired users
                    newly_expiring = current_expiring - prev_expiring
                    newly_expired = current_expired - prev_expired

                    panel_name = current_snap.get("panel_name", f"Panel {panel_id}")

                    # Send notifications for newly expiring users
                    if newly_expiring:
                        for name in newly_expiring:
                            if is_super:
                                msg = _format_expiring_msg_super_with_panel(name, panel_name)
                            else:
                                msg = _format_expiring_msg_reseller_with_panel(name, panel_name)
                            try:
                                await bot.send_message(tg_id, msg, parse_mode="HTML")
                                await asyncio.sleep(0.3)
                            except TelegramForbiddenError:
                                logging.warning(f"⚠️ کاربر {tg_id} ربات را بلاک کرده است.")
                                break
                            except Exception as e:
                                log_error(e)

                    # Send notifications for newly expired users
                    if newly_expired:
                        for name in newly_expired:
                            if is_super:
                                msg = _format_expired_msg_super_with_panel(name, panel_name)
                            else:
                                msg = _format_expired_msg_reseller_with_panel(name, panel_name)
                            try:
                                await bot.send_message(tg_id, msg, parse_mode="HTML")
                                await asyncio.sleep(0.3)
                            except TelegramForbiddenError:
                                logging.warning(f"⚠️ کاربر {tg_id} ربات را بلاک کرده است.")
                                break
                            except Exception as e:
                                log_error(e)

                # Update the database with current snapshot (all panels)
                async with aiosqlite.connect("data.db") as db:
                    await db.execute(
                        "INSERT OR REPLACE INTO last_reports(telegram_id, last_json, last_full_report) VALUES (?, ?, ?)",
                        (tg_id, json.dumps(current_panels_snap), int(time.time()))
                    )
                    await db.commit()

                await asyncio.sleep(0.5)

            except Exception as e:
                log_error(e)
                logging.error(f"  ❌ خطا در بررسی {tg_id}: {e}")
                continue

    except Exception as e:
        log_error(e)
        logging.error(f"Error in check_for_changes: {e}")

    logging.info("✅ The entire Panel was Successfully reviewed.")

# ---------------- Cancel Action ----------------
@dp.callback_query(F.data == "cancel_action")
async def cancel_action(c: CallbackQuery):
    if c.from_user.id in current_action:
        del current_action[c.from_user.id]
    await c.message.edit_text("❌ عملیات لغو شد.", reply_markup=get_main_kb(c.from_user.id))
    await c.answer()

@dp.callback_query(F.data == "back_to_main_menu_superadmin")
async def back_to_main_menu_superadmin(c: CallbackQuery):
    if c.from_user.id not in SUPERADMINS: return
    if c.from_user.id in current_action:
        del current_action[c.from_user.id]
    await c.message.edit_text("🏠 به منوی اصلی بازگشتید.", reply_markup=get_main_kb(c.from_user.id))
    await c.answer()

# ---------------- Main ----------------
async def main():
    await ensure_db()

    # 🕒 Daily report scheduled dynamically by .env
    scheduler.add_job(
        send_full_reports,
        'cron',
        hour=DAILY_REPORT_HOUR,
        minute=DAILY_REPORT_MINUTE,
        timezone=ZoneInfo("Asia/Tehran"),
        id='daily_report',
        replace_existing=True
    )

    # 🔁 Change detection dynamically by .env
    scheduler.add_job(
        check_for_changes,
        'interval',
        minutes=CHANGE_CHECK_INTERVAL_MINUTES,
        timezone=ZoneInfo("Asia/Tehran"),
        id='change_detection',
        replace_existing=True
    )

    scheduler.start()

    # 📋 Log the dynamic cron configuration
    logging.info("✅ Schedulers initialized from .env configuration:")
    logging.info(f"⏰ DAILY_REPORT_HOUR = {DAILY_REPORT_HOUR}")
    logging.info(f"⏰ DAILY_REPORT_MINUTE = {DAILY_REPORT_MINUTE}")
    logging.info(f"🔁 CHANGE_CHECK_INTERVAL_MINUTES = {CHANGE_CHECK_INTERVAL_MINUTES}")

    logging.info("Bot has Started Successfully")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Bot has Stopped by User")
    except Exception as e:
        log_error(e)
        logging.error(f"Fatal error: {e}")
