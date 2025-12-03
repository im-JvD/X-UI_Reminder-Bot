"""
Panel management handlers (superadmin only).
"""
import logging
import aiosqlite
from typing import Dict, Any, Tuple

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery

from ..config.settings import SUPERADMINS
from ..database.connection import DatabaseManager
from ..database.repositories.panel_repository import PanelRepository
from ..api.client import PanelAPI
from ..keyboards.inline_keyboards import (
    get_panel_management_kb,
    get_panel_selection_kb,
    get_cancel_kb
)
from ..utils.text_helpers import safe_text
from ..utils.logging_helpers import log_error

logger = logging.getLogger(__name__)
router = Router()

current_action: Dict[int, Tuple[str, Any]] = {}


@router.message(F.text == "🏢 مدیریت پنل‌ها")
async def manage_panels_menu(message: Message):
    """Show panel management menu (superadmin only)."""
    if message.from_user.id not in SUPERADMINS:
        await message.answer("⛔️ این بخش فقط برای سوپرادمین در دسترس است.")
        return

    await message.answer(
        "🏢 <b>مدیریت پنل‌ها</b>\nگزینه مورد نظر را انتخاب کنید:",
        reply_markup=get_panel_management_kb(),
        parse_mode="HTML"
    )

# ============ Add Panel ============

@router.callback_query(F.data == "add_panel")
async def add_panel_callback(query: CallbackQuery):
    """Start panel addition process."""
    if query.from_user.id not in SUPERADMINS:
        return
    
    admin_id = query.from_user.id
    current_action[admin_id] = ("get_panel_name", {})
    
    await query.message.edit_text(
        "📝 برای افزودن، <b>نام پنل جدید</b> را وارد کنید...\n\n"
        "مثال = <b>🇩🇪 - Germany</b>",
        reply_markup=get_cancel_kb("panel"),
        parse_mode="HTML"
    )
    await query.answer()


@router.message(
    F.text & ~F.command(),
    lambda m: m.from_user.id in SUPERADMINS and 
    current_action.get(m.from_user.id, (None, None))[0] == "get_panel_name"
)
async def handle_panel_name(message: Message):
    """Handle panel name input."""
    admin_id = message.from_user.id
    panel_name = message.text.strip()

    if len(panel_name) < 2:
        await message.answer("❌ نام پنل باید حداقل 2 کاراکتر باشد.")
        return

    current_action[admin_id] = ("get_panel_base_url", {"panel_name": panel_name})
    
    await message.answer(
        f"✅ نام پنل '<b>{safe_text(panel_name)}</b>' ثبت شد.\n\n"
        "🌐 حالا <b>آدرس کامل</b> پنل را وارد کنید...\n\n"
        "مثال = <b>https://panel.example.com</b>",
        parse_mode="HTML"
    )


@router.message(
    F.text & ~F.command(),
    lambda m: m.from_user.id in SUPERADMINS and 
    current_action.get(m.from_user.id, (None, None))[0] == "get_panel_base_url"
)
async def handle_panel_base_url(message: Message):
    """Handle panel base URL input."""
    admin_id = message.from_user.id
    base_url = message.text.strip().rstrip("/")

    if not base_url.startswith(('http://', 'https://')):
        await message.answer("❌ آدرس باید با http:// یا https:// شروع شود.")
        return

    data = current_action[admin_id][1]
    data["base_url"] = base_url
    current_action[admin_id] = ("get_panel_web_path", data)

    await message.answer(
        f"✅ آدرس کامل '<b>{safe_text(base_url)}</b>' ثبت شد.\n\n"
        "🔄 حالا مسیر <b>WebPath</b>  ( اختیاری ) را وارد کنید...\n\n"
        "مثال = <b>/panel</b>\n"
        "اگر ندارید، فقط <b>[ / ]</b>  را به تنهایی ارسال نمایید !",
        parse_mode="HTML"
    )


@router.message(
    F.text & ~F.command(),
    lambda m: m.from_user.id in SUPERADMINS and 
    current_action.get(m.from_user.id, (None, None))[0] == "get_panel_web_path"
)
async def handle_panel_web_path(message: Message):
    """Handle panel web path input."""
    admin_id = message.from_user.id
    web_path = message.text.strip().rstrip("/")

    data = current_action[admin_id][1]
    data["web_base_path"] = web_path if web_path != "/" else ""
    current_action[admin_id] = ("get_panel_username", data)

    await message.answer(
        f"✅ مسیر <b>WebPath</b> ثبت شد.\n\n"
        f"👤 حالا <b>نام کاربری پنل</b> را وارد کنید...",
        parse_mode="HTML"
    )


@router.message(
    F.text & ~F.command(),
    lambda m: m.from_user.id in SUPERADMINS and 
    current_action.get(m.from_user.id, (None, None))[0] == "get_panel_username"
)
async def handle_panel_username(message: Message):
    """Handle panel username input."""
    admin_id = message.from_user.id
    username = message.text.strip()

    if len(username) < 3:
        await message.answer("❌ نام کاربری باید حداقل 3 کاراکتر باشد.")
        return

    data = current_action[admin_id][1]
    data["username"] = username
    current_action[admin_id] = ("get_panel_password", data)

    await message.answer(
        f"✅ نام کاربری '<b>{safe_text(username)}</b>' ثبت شد.\n\n"
        "🔐 حالا <b>رمز عبور پنل</b> را وارد کنید...",
        parse_mode="HTML"
    )

@router.message(
    F.text & ~F.command(),
    lambda m: m.from_user.id in SUPERADMINS and
    current_action.get(m.from_user.id, (None, None))[0] == "get_panel_password"
)
async def handle_panel_password(message: Message):
    """Handle panel password input and complete panel addition."""
    admin_id = message.from_user.id
    password = message.text.strip()

    if len(password) < 4:
        await message.answer("❌ رمز عبور باید حداقل 4 کاراکتر باشد.")
        return

    data = current_action[admin_id][1]
    data["password"] = password

    try:
        
        db_manager = DatabaseManager("data.db")
        async with db_manager.get_connection() as db:
            panel_repo = PanelRepository("data.db")
            await panel_repo.add_panel(
                data["panel_name"],
                data["base_url"],
                data["web_base_path"],
                data["username"],
                data["password"]
            )
            
        async with PanelAPI(
            data["username"],
            data["password"],
            data["base_url"],
            data["web_base_path"]
        ) as api:
            login_success = await api.login()

        if login_success:
            await message.answer(
                f"✅ <b>پنل با موفقیت اضافه شد!</b>\n\n"
                f"🖥 <b>نام =</b> {safe_text(data['panel_name'])}\n"
                f"🌐 <b>آدرس =</b> {safe_text(data['base_url'])}\n"
                f"👤 <b>نام کاربری =</b> {safe_text(data['username'])}\n"
                f"✅ <b>وضعیت تست اتصال به پنل =</b> موفق",
                reply_markup=get_panel_management_kb(),
                parse_mode="HTML"
            )
        else:
            await message.answer(
                f"⚠️ <b>پنل اضافه شد اما اتصال ناموفق است!</b>\n\n"
                f"لطفاً اطلاعات ورودی را بررسی کنید.\n"
                f"🖥 <b>نام =</b> {safe_text(data['panel_name'])}\n"
                f"🌐 <b>آدرس =</b> {safe_text(data['base_url'])}",
                reply_markup=get_panel_management_kb(),
                parse_mode="HTML"
            )

    except Exception as e:
        log_error(e)
        await message.answer(
            f"❌ خطا در اضافه کردن پنل:\n<code>{str(e)}</code>",
            reply_markup=get_panel_management_kb(),
            parse_mode="HTML"
        )

    del current_action[admin_id]


# ============ List Panels ============

@router.callback_query(F.data == "list_panels")
async def list_panels_callback(query: CallbackQuery):
    """Show list of all panels."""
    if query.from_user.id not in SUPERADMINS:
        return

    try:
        panel_repo = PanelRepository("data.db")
        panels = await panel_repo.get_all_panels()

        if not panels:
            await query.message.edit_text(
                "ℹ️ هیچ پنلی در سیستم ثبت نشده است.",
                reply_markup=get_panel_management_kb()
            )
            await query.answer()
            return

        msg = "📋 <b>لیست پنل‌های ثبت‌شده</b>\n\n"
        for panel in panels:
            msg += f"🆔 <b>شناسه پنل =</b> <code>{panel[0]}</code>\n"
            msg += f"🖥 <b>نام پنل =</b> {safe_text(panel[1])}\n"
            msg += f"🌐 <b>آدرس =</b> {safe_text(panel[2])}\n\n"

        await query.message.edit_text(msg, reply_markup=get_panel_management_kb(), parse_mode="HTML")
        await query.answer()

    except Exception as e:
        log_error(e)
        await query.answer("❌ خطا در دریافت لیست پنل‌ها", show_alert=True)


# ============ Delete Panel ============

@router.callback_query(F.data == "delete_panel")
async def delete_panel_callback(query: CallbackQuery):
    """Show panel selection for deletion."""
    if query.from_user.id not in SUPERADMINS:
        return

    try:
        panel_repo = PanelRepository("data.db")
        panels = await panel_repo.get_panels_with_names()

        if not panels:
            await query.answer("ℹ️ هیچ پنلی برای حذف وجود ندارد.", show_alert=True)
            return

        kb = get_panel_selection_kb(panels, "view_before_delete", "back_to_panels_menu")

        await query.message.edit_text(
            "🗑 <b>حذف پنل</b>\n\n"
            "پنلی که می‌خواهید حذف کنید را <b>از لیست زیر انتخاب نمایید...</b>\n\n"
            "⚠️ <b>توجه:</b> با حذف پنل، تمام نماینده‌های فروش و دسترسی‌های مربوط به این پنل نیز <b>به طور کامل حذف خواهند شد.</b>",
            reply_markup=kb,
            parse_mode="HTML"
        )
        await query.answer()

    except Exception as e:
        log_error(e)
        await query.answer("❌ خطا در دریافت لیست پنل‌ها", show_alert=True)

@router.callback_query(F.data.startswith("select_panel_for_reseller:view_before_delete:"))
async def view_panel_before_delete(query: CallbackQuery):
    """Show panel details and resellers before deletion (Step 2)."""
    if query.from_user.id not in SUPERADMINS:
        return

    try:
        panel_id = int(query.data.split(":")[-1])
    except (IndexError, ValueError):
        await query.answer("❌ شناسه پنل نامعتبر است.", show_alert=True)
        return

    try:
        from ..database.repositories.reseller_repository import ResellerRepository
        
        panel_repo = PanelRepository("data.db")
        reseller_repo = ResellerRepository("data.db")
        
        panel = await panel_repo.get_panel_by_id(panel_id)

        if not panel:
            await query.answer("❌ پنل مورد نظر یافت نشد.", show_alert=True)
            return
            
        all_resellers = await reseller_repo.get_all_resellers()
        panel_resellers = [r for r in all_resellers if r['panel_id'] == panel_id]
        
        msg = f"🏢 <b>اطلاعات پنل</b>\n\n"
        msg += f"🆔 <b>شناسه:</b> <code>{panel['panel_id']}</code>\n"
        msg += f"📛 <b>نام:</b> {safe_text(panel['panel_name'])}\n"
        msg += f"🌐 <b>آدرس:</b> {safe_text(panel['base_url'])}\n"
        msg += f"👤 <b>نام کاربری:</b> <code>{safe_text(panel['username'])}</code>\n\n"

        if panel_resellers:
            
            grouped = {}
            for r in panel_resellers:
                tg_id = r['telegram_id']
                if tg_id not in grouped:
                    grouped[tg_id] = []
                grouped[tg_id].append(r['inbound_id'])

            msg += f"👥 <b>نمایندگان فروش ({len(grouped)} نفر):</b>\n"
            for tg_id, inbounds in grouped.items():
                msg += f"  • <code>{tg_id}</code> → اینباندها: {', '.join(map(str, inbounds))}\n"
            msg += "\n"
        else:
            msg += "ℹ️ <b>هیچ نماینده‌ای برای این پنل ثبت نشده است.</b>\n\n"

        msg += "⚠️ <b>آیا مطمئن هستید که می‌خواهید این پنل و تمام نمایندگان آن را حذف کنید؟</b>"

        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ بله، حذف شود",
                    callback_data=f"confirm_delete_panel:{panel_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ انصراف",
                    callback_data="back_to_panels_menu"
                )
            ]
        ])

        await query.message.edit_text(msg, reply_markup=kb, parse_mode="HTML")
        await query.answer()

    except Exception as e:
        log_error(e)
        await query.answer("❌ خطا در دریافت اطلاعات پنل", show_alert=True)

@router.callback_query(F.data.startswith("confirm_delete_panel:"))
async def confirm_delete_panel(query: CallbackQuery):
    """Delete selected panel and notify resellers (Step 3 & 4)."""
    if query.from_user.id not in SUPERADMINS:
        return

    try:
        panel_id = int(query.data.split(":")[1])
    except (IndexError, ValueError):
        await query.answer("❌ شناسه پنل نامعتبر است.", show_alert=True)
        return

    try:
        from ..database.repositories.reseller_repository import ResellerRepository
        
        panel_repo = PanelRepository("data.db")
        reseller_repo = ResellerRepository("data.db")

        panel = await panel_repo.get_panel_by_id(panel_id)

        if not panel:
            await query.answer("❌ پنل مورد نظر یافت نشد.", show_alert=True)
            return
            
        all_resellers = await reseller_repo.get_all_resellers()
        panel_resellers = [r for r in all_resellers if r['panel_id'] == panel_id]
        
        resellers_to_notify = {}
        for r in panel_resellers:
            tg_id = r['telegram_id']
            if tg_id not in resellers_to_notify:
                resellers_to_notify[tg_id] = []
            resellers_to_notify[tg_id].append(r['inbound_id'])
            
        deleted_resellers = 0
        for tg_id in resellers_to_notify.keys():
            await reseller_repo.remove_all_inbounds(tg_id, panel_id)
            deleted_resellers += 1

        success = await panel_repo.delete_panel(panel_id)

        if success:
            
            async with aiosqlite.connect("data.db") as db:
                await db.execute("VACUUM")
                await db.commit()

            msg = f"✅ <b>پنل با موفقیت حذف شد!</b>\n\n"
            msg += f"🏢 <b>نام پنل:</b> {safe_text(panel['panel_name'])}\n"
            msg += f"👥 <b>نمایندگان حذف شده:</b> {deleted_resellers} نفر\n"
            msg += f"🗄 <b>بهینه‌سازی دیتابیس:</b> انجام شد"

            await query.message.edit_text(
                msg,
                reply_markup=get_panel_management_kb(),
                parse_mode="HTML"
            )
            
            from .reseller_management import send_reseller_notification
            
            for tg_id, inbounds in resellers_to_notify.items():
                try:
                    await send_reseller_notification(
                        query.bot,
                        tg_id,
                        "delete",
                        panel['panel_name'],
                        inbounds
                    )
                except Exception as e:
                    logger.error(f"Failed to notify reseller {tg_id}: {e}")

            await query.answer("✅ پنل و تمام داده‌های مرتبط حذف شد.", show_alert=True)
        else:
            await query.answer("❌ خطا در حذف پنل", show_alert=True)

    except Exception as e:
        log_error(e)
        logger.error(f"Error in confirm_delete_panel: {e}")
        await query.answer("❌ خطا در حذف پنل", show_alert=True)


# ============ Navigation Handlers ============

@router.callback_query(F.data.startswith("cancel_action:panel"))
async def cancel_action_panel(query: CallbackQuery):
    """Cancel current action and return to panel management menu."""
    admin_id = query.from_user.id
    
    if admin_id in current_action:
        del current_action[admin_id]
        
    await query.message.edit_text(
        "❌ عملیات لغو شد.\n\n"
        "🏢 <b>مدیریت پنل‌ها</b>\n\n"
        "گزینه مورد نظر را انتخاب کنید:",
        reply_markup=get_panel_management_kb(),
        parse_mode="HTML"
    )
    await query.answer("✅ عملیات لغو شد")

@router.callback_query(F.data == "back_to_panels_menu")
async def back_to_panels_menu(query: CallbackQuery):
    """Return to panel management menu."""
    if query.from_user.id not in SUPERADMINS:
        return

    admin_id = query.from_user.id
    
    if admin_id in current_action:
        del current_action[admin_id]

    await query.message.edit_text(
        "🏢 <b>مدیریت پنل‌ها</b>\n\n"
        "گزینه مورد نظر را انتخاب کنید:",
        reply_markup=get_panel_management_kb(),
        parse_mode="HTML"
    )
    await query.answer()

@router.callback_query(F.data == "back_to_main_menu_superadmin")
async def back_to_main_menu_superadmin(query: CallbackQuery):
    """Return to main menu - send new message instead of editing."""
    from ..keyboards.main_keyboards import get_main_kb

    if query.from_user.id not in SUPERADMINS:
        return

    admin_id = query.from_user.id
    
    if admin_id in current_action:
        del current_action[admin_id]

    is_superadmin = admin_id in SUPERADMINS
    kb = get_main_kb(is_superadmin)
    
    try:
        await query.message.delete()
    except:
        pass

    await query.message.answer(
        "🏠 به منوی اصلی بازگشتید.",
        reply_markup=kb
    )
    await query.answer()

@router.callback_query(F.data == "back_to_main")
async def back_to_main(query: CallbackQuery):
    """Return to main menu - send new message instead of editing."""
    from ..keyboards.main_keyboards import get_main_kb

    admin_id = query.from_user.id
    
    if admin_id in current_action:
        del current_action[admin_id]

    is_superadmin = admin_id in SUPERADMINS
    kb = get_main_kb(is_superadmin)
    
    try:
        await query.message.delete()
    except:
        pass

    await query.message.answer(
        "🏠 به منوی اصلی بازگشتید.",
        reply_markup=kb
    )
    await query.answer()
