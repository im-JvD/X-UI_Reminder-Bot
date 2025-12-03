"""
Reseller management handlers (superadmin only).
Handles adding, editing, and deleting reseller assignments to panels and inbounds.
"""
import logging
from typing import Dict, Any, Tuple

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from ..config.settings import SUPERADMINS
from ..database.connection import DatabaseManager
from ..database.repositories.reseller_repository import ResellerRepository
from ..database.repositories.panel_repository import PanelRepository
from ..database.repositories.user_repository import UserRepository
from ..api.client import PanelAPI
from ..keyboards.inline_keyboards import (
    get_reseller_management_kb,
    get_panel_selection_kb,
    get_cancel_kb
)
from ..utils.text_helpers import safe_text
from ..utils.logging_helpers import log_error

logger = logging.getLogger(__name__)
router = Router()

current_action: Dict[int, Tuple[str, Any]] = {}

async def send_reseller_notification(
    bot,
    reseller_id: int,
    notification_type: str,
    panel_name: str,
    inbounds: list
):
    """
    Send notification to reseller about changes.
    
    Args:
        bot: Bot instance
        reseller_id: Reseller's telegram ID
        notification_type: 'add', 'edit', or 'delete'
        panel_name: Panel name
        inbounds: List of inbound IDs
    """
    try:
        if notification_type == "add":
            message = (
                f"✅ <b>شما به عنوان نماینده فروش اضافه شدید!</b>\n\n"
                f"🖥 <b>پنل:</b> {safe_text(panel_name)}\n"
                f"📡 <b>اینباندهای اختصاصی:</b> {', '.join(map(str, inbounds))}\n\n"
                f"🎯 از این پس می‌توانید گزارش‌های این اینباندها را مشاهده کنید."
            )
        elif notification_type == "edit":
            message = (
                f"🔄 <b>اینباندهای نمایندگی شما ویرایش شد!</b>\n\n"
                f"🖥 <b>پنل:</b> {safe_text(panel_name)}\n"
                f"📡 <b>اینباندهای جدید:</b> {', '.join(map(str, inbounds))}\n\n"
                f"ℹ️ از این پس فقط گزارش این اینباندها را دریافت خواهید کرد."
            )
        elif notification_type == "delete":
            message = (
                f"🚫 <b>نمایندگی شما حذف شد!</b>\n\n"
                f"🖥 <b>پنل:</b> {safe_text(panel_name)}\n"
                f"📡 <b>اینباندهای حذف شده:</b> {', '.join(map(str, inbounds))}\n\n"
                f"⚠️ دیگر دسترسی به گزارش این اینباندها را ندارید."
            )
        else:
            return

        await bot.send_message(
            reseller_id,
            message,
            parse_mode="HTML"
        )
        logger.info(f"✅ Notification sent to reseller {reseller_id} ({notification_type})")

    except Exception as e:
        logger.error(f"❌ Failed to send notification to reseller {reseller_id}: {e}")

@router.message(F.text == "🧑‍💼 نمایندگان فروش")
async def manage_resellers_menu(message: Message):
    """Show reseller management menu (superadmin only)."""
    if message.from_user.id not in SUPERADMINS:
        await message.answer("⛔️ این بخش فقط برای سوپرادمین در دسترس است.")
        return

    await message.answer(
        "👥🔧 <b>مدیریت نماینده‌های فروش</b>\nگزینه مورد نظر را انتخاب کنید:",
        reply_markup=get_reseller_management_kb(),
        parse_mode="HTML"
    )

# ============ Add Reseller ============

@router.callback_query(F.data == "add_reseller")
async def add_reseller_callback(query: CallbackQuery):
    """Start reseller addition - first select panel."""
    if query.from_user.id not in SUPERADMINS:
        return

    try:
        panel_repo = PanelRepository("data.db")
        panels = await panel_repo.get_panels_with_names()

        if not panels:
            await query.answer("❌ ابتدا باید حداقل یک پنل اضافه کنید.", show_alert=True)
            return

        kb = get_panel_selection_kb(panels, "add", "back_to_resellers_menu")

        await query.message.edit_text(
            "پنل منتخب این نمایندگی رو از لیست زیر انتخاب نمایید.",
            reply_markup=kb
        )
        await query.answer()

    except Exception as e:
        log_error(e)
        await query.answer("❌ خطا در دریافت لیست پنل‌ها", show_alert=True)

# ============ Edit Reseller ============

@router.callback_query(F.data == "edit_reseller")
async def edit_reseller_callback(query: CallbackQuery):
    """Start reseller editing - first select panel."""
    if query.from_user.id not in SUPERADMINS:
        return

    try:
        panel_repo = PanelRepository("data.db")
        panels = await panel_repo.get_panels_with_names()

        if not panels:
            await query.answer("❌ هیچ پنلی برای ویرایش وجود ندارد.", show_alert=True)
            return

        kb = get_panel_selection_kb(panels, "edit", "back_to_resellers_menu")

        await query.message.edit_text(
            "پنل مورد نظر را برای ویرایش انتخاب کنید:",
            reply_markup=kb
        )
        await query.answer()

    except Exception as e:
        log_error(e)
        await query.answer("❌ خطا در دریافت لیست پنل‌ها", show_alert=True)

# ============ Delete Reseller ============

@router.callback_query(F.data == "delete_reseller")
async def delete_reseller_callback(query: CallbackQuery):
    """Start reseller deletion - first select panel."""
    if query.from_user.id not in SUPERADMINS:
        return

    try:
        panel_repo = PanelRepository("data.db")
        panels = await panel_repo.get_panels_with_names()

        if not panels:
            await query.answer("❌ هیچ پنلی وجود ندارد.", show_alert=True)
            return

        kb = get_panel_selection_kb(panels, "delete", "back_to_resellers_menu")

        await query.message.edit_text(
            "پنل مورد نظر را برای حذف نماینده انتخاب کنید:",
            reply_markup=kb
        )
        await query.answer()

    except Exception as e:
        log_error(e)
        await query.answer("❌ خطا در دریافت لیست پنل‌ها", show_alert=True)

# ============ List Resellers ============

@router.callback_query(F.data == "list_resellers")
async def list_resellers_callback(query: CallbackQuery):
    """Show all resellers and their assignments."""
    if query.from_user.id not in SUPERADMINS:
        return

    try:
        reseller_repo = ResellerRepository("data.db")
        panel_repo = PanelRepository("data.db")

        resellers = await reseller_repo.get_all_resellers()

        if not resellers:
            await query.message.edit_text(
                "ℹ️ هیچ نماینده‌ای در سیستم ثبت نشده است.",
                reply_markup=get_reseller_management_kb()
            )
            await query.answer()
            return

        grouped = {}
        for assignment in resellers:
            tg_id = assignment['telegram_id']
            if tg_id not in grouped:
                grouped[tg_id] = []
            grouped[tg_id].append(assignment)

        msg = "📋 <b>لیست نماینده‌های فروش</b>\n\n"

        for tg_id, assignments in grouped.items():
            msg += f"🆔 <b>شناسه تلگرام =</b> [ <code>{tg_id}</code> ]\n"

            panels_dict = {}
            for asg in assignments:
                panel_id = asg['panel_id']
                if panel_id not in panels_dict:
                    panels_dict[panel_id] = {
                        'panel_name': asg.get('panel_name', f'Panel {panel_id}'),
                        'inbounds': []
                    }
                panels_dict[panel_id]['inbounds'].append(asg['inbound_id'])

            for panel_id, data in panels_dict.items():
                msg += f"   <b>• پنل = [</b> {safe_text(data['panel_name'])} <b>] | اینباند = [</b> {', '.join(map(str, data['inbounds']))} <b>]</b>\n"

            msg += "\n"

        await query.message.edit_text(msg, reply_markup=get_reseller_management_kb(), parse_mode="HTML")
        await query.answer()

    except Exception as e:
        log_error(e)
        await query.answer("❌ خطا در دریافت لیست نماینده‌ها", show_alert=True)

# ============ Panel Selection for Reseller Operations ============

@router.callback_query(F.data.startswith("select_panel_for_reseller:"))
async def select_panel_for_reseller_callback(query: CallbackQuery):
    """Handle panel selection for reseller operations."""
    if query.from_user.id not in SUPERADMINS:
        return

    try:
        _, action_type, panel_id_str = query.data.split(":")
        panel_id = int(panel_id_str)
    except (ValueError, IndexError):
        await query.answer("❌ داده نامعتبر.", show_alert=True)
        return

    admin_id = query.from_user.id
    data_to_store = {'panel_id': panel_id}

    if action_type == "add":
        current_action[admin_id] = ("get_reseller_id_for_add", data_to_store)
        prompt_message = (
            "🆔 حالا <b>شناسه تلگرام کاربری</b> که می‌خواهید به این پنل به عنوان "
            "<b>( نمایندگی فروش )</b> اضافه شود را ارسال کنید..."
        )
    elif action_type == "edit":
        current_action[admin_id] = ("get_reseller_id_for_edit", data_to_store)
        prompt_message = (
            "🆔 حالا <b>شناسه تلگرام نمایندگی فروشی</b> که می‌خواهید "
            "<b>اینباندهای او را در این پنل</b> ویرایش کنید، ارسال کنید..."
        )
    elif action_type == "delete":
        current_action[admin_id] = ("get_reseller_id_for_delete", data_to_store)
        prompt_message = (
            "🆔 <b>شناسه تلگرام نمایندگی فروشی</b> که می‌خواهید "
            "<b>از این پنل حذف شود</b> را ارسال کنید..."
        )
    else:
        return

    await query.message.edit_text(
        prompt_message, 
        parse_mode="HTML", 
        reply_markup=get_cancel_kb("reseller")
    )
    await query.answer()

# ============ Handle Reseller ID for Add ============

@router.message(
    F.text & ~F.command(),
    lambda m: m.from_user.id in SUPERADMINS and
    current_action.get(m.from_user.id, (None, None))[0] == "get_reseller_id_for_add"
)
async def handle_reseller_id_for_add(message: Message):
    """Handle reseller ID input for adding."""
    admin_id = message.from_user.id

    try:
        reseller_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ لطفاً یک شماره معتبر وارد کنید.")
        return

    try:
        user_repo = UserRepository("data.db")
        await user_repo.ensure_user(reseller_id)
    except Exception as e:
        log_error(e)
        await message.answer("❌ خطا در ثبت کاربر.")
        return

    data = current_action[admin_id][1]
    data['reseller_id'] = reseller_id
    current_action[admin_id] = ("assign_inbound_for_add", data)

    await message.answer(
        f"✅ کاربر با شناسه [ <code>{reseller_id}</code> ] برای افزودن به عنوان نمایندگی فروش انتخاب شد.\n"
        f"در این مرحله <b>شناسه اینباندهایی</b> که می‌خواهید به <b>این کاربر اختصاص دهید</b>، را ارسال کنید...\n"
        f"می‌توانید شناسه اینباند ها را با [ , ] از هم جدا کنید !\n"
        f"مثال = <b>1, 2, 3, ...</b>",
        parse_mode="HTML"
    )

@router.message(
    F.text & ~F.command(),
    lambda m: m.from_user.id in SUPERADMINS and
    current_action.get(m.from_user.id, (None, None))[0] == "assign_inbound_for_add"
)
async def handle_inbound_for_add(message: Message):
    """Handle inbound assignment for adding reseller."""
    admin_id = message.from_user.id
    inbound_text = message.text.strip()

    try:
        inbound_ids = [int(x.strip()) for x in inbound_text.split(",") if x.strip().isdigit()]

        if not inbound_ids:
            await message.answer("❌ هیچ شناسه اینباند معتبری یافت نشد.")
            return

        data = current_action[admin_id][1]
        panel_id = data['panel_id']
        reseller_id = data['reseller_id']

        panel_repo = PanelRepository("data.db")
        panel = await panel_repo.get_panel_by_id(panel_id)

        if not panel:
            await message.answer("❌ پنل مورد نظر یافت نشد.")
            del current_action[admin_id]
            return

        async with PanelAPI(
            panel['username'],
            panel['password'],
            panel['base_url'],
            panel.get('web_base_path', '')
        ) as api:
            await api.login()
            all_inbounds = await api.inbounds()

        if not all_inbounds or not isinstance(all_inbounds, list):
            await message.answer("❌ خطا در دریافت اینباندهای پنل.")
            del current_action[admin_id]
            return

        available_inbound_ids = [
            ib['id'] for ib in all_inbounds
            if isinstance(ib, dict) and 'id' in ib
        ]

        valid_inbounds = [iid for iid in inbound_ids if iid in available_inbound_ids]
        invalid_inbounds = [iid for iid in inbound_ids if iid not in available_inbound_ids]

        if not valid_inbounds:
            await message.answer(
                f"❌ هیچ‌کدام از شناسه‌های واردشده معتبر نیست.\n"
                f"اینباندهای موجود در پنل: {', '.join(map(str, available_inbound_ids))}"
            )
            return

        reseller_repo = ResellerRepository("data.db")
        added_count = 0

        for inbound_id in valid_inbounds:
            success = await reseller_repo.assign_inbound(reseller_id, panel_id, inbound_id)
            if success:
                added_count += 1

        msg = f"✅ <b>نمایندگی با موفقیت اضافه شد!</b>\n\n"
        msg += f"🆔 <b>شناسه تلگرام =</b> <code>{reseller_id}</code>\n"
        msg += f"🖥 <b>پنل =</b> {safe_text(panel['panel_name'])}\n"
        msg += f"📡 <b>اینباندهای اضافه شده ({added_count}) =</b> {', '.join(map(str, valid_inbounds))}\n"

        if invalid_inbounds:
            msg += f"\n⚠️ <b>اینباندهای نامعتبر ({len(invalid_inbounds)}) =</b> {', '.join(map(str, invalid_inbounds))}"

        await message.answer(msg, reply_markup=get_reseller_management_kb(), parse_mode="HTML")
        
        await send_reseller_notification(
            message.bot,
            reseller_id,
            "add",
            panel['panel_name'],
            valid_inbounds
        )

    except Exception as e:
        log_error(e)
        await message.answer(
            f"❌ خطا در افزودن نمایندگی:\n<code>{str(e)}</code>",
            reply_markup=get_reseller_management_kb(),
            parse_mode="HTML"
        )

    del current_action[admin_id]

# ============ Handle Reseller ID for Edit ============

@router.message(
    F.text & ~F.command(),
    lambda m: m.from_user.id in SUPERADMINS and
    current_action.get(m.from_user.id, (None, None))[0] == "get_reseller_id_for_edit"
)
async def handle_reseller_id_for_edit(message: Message):
    """Handle reseller ID input for editing."""
    admin_id = message.from_user.id

    try:
        reseller_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ لطفاً یک شماره معتبر وارد کنید.")
        return

    data = current_action[admin_id][1]
    panel_id = data['panel_id']

    try:
        reseller_repo = ResellerRepository("data.db")
        current_inbounds = await reseller_repo.get_reseller_inbounds(reseller_id, panel_id)

        if not current_inbounds:
            await message.answer(
                f"ℹ️ این نماینده در پنل انتخابی هیچ اینباندی ندارد.\n"
                f"از منوی افزودن استفاده کنید."
            )
            del current_action[admin_id]
            return

        data['reseller_id'] = reseller_id
        data['current_inbounds'] = current_inbounds
        current_action[admin_id] = ("assign_inbound_for_edit", data)

        await message.answer(
            f"✅ نماینده با شناسه [ <code>{reseller_id}</code> ] انتخاب شد.\n\n"
            f"📡 <b>اینباندهای فعلی:</b> {', '.join(map(str, current_inbounds))}\n\n"
            f"حالا <b>لیست جدید اینباندها</b> را ارسال کنید (با کاما جدا شوند):\n"
            f"مثال = <b>1, 2, 5</b>",
            parse_mode="HTML"
        )

    except Exception as e:
        log_error(e)
        await message.answer("❌ خطا در بررسی نماینده.")
        del current_action[admin_id]

@router.message(
    F.text & ~F.command(),
    lambda m: m.from_user.id in SUPERADMINS and
    current_action.get(m.from_user.id, (None, None))[0] == "assign_inbound_for_edit"
)
async def handle_inbound_for_edit(message: Message):
    """Handle inbound assignment for editing reseller."""
    admin_id = message.from_user.id
    inbound_text = message.text.strip()

    try:
        new_inbound_ids = [int(x.strip()) for x in inbound_text.split(",") if x.strip().isdigit()]

        if not new_inbound_ids:
            await message.answer("❌ هیچ شناسه اینباند معتبری یافت نشد.")
            return

        data = current_action[admin_id][1]
        panel_id = data['panel_id']
        reseller_id = data['reseller_id']
        current_inbounds = set(data['current_inbounds'])

        panel_repo = PanelRepository("data.db")
        panel = await panel_repo.get_panel_by_id(panel_id)

        if not panel:
            await message.answer("❌ پنل یافت نشد.")
            del current_action[admin_id]
            return

        async with PanelAPI(
            panel['username'],
            panel['password'],
            panel['base_url'],
            panel.get('web_base_path', '')
        ) as api:
            await api.login()
            all_inbounds = await api.inbounds()

        available_inbound_ids = [
            ib['id'] for ib in all_inbounds
            if isinstance(ib, dict) and 'id' in ib
        ]

        valid_new_inbounds = [iid for iid in new_inbound_ids if iid in available_inbound_ids]

        if not valid_new_inbounds:
            await message.answer("❌ هیچ اینباند معتبری در لیست جدید وجود ندارد.")
            return

        reseller_repo = ResellerRepository("data.db")
        await reseller_repo.remove_all_inbounds(reseller_id, panel_id)

        added_count = 0
        for inbound_id in valid_new_inbounds:
            success = await reseller_repo.assign_inbound(reseller_id, panel_id, inbound_id)
            if success:
                added_count += 1

        await message.answer(
            f"✅ <b>اینباندهای نماینده با موفقیت ویرایش شد!</b>\n\n"
            f"🆔 <b>شناسه تلگرام =</b> <code>{reseller_id}</code>\n"
            f"🖥 <b>پنل =</b> {safe_text(panel['panel_name'])}\n"
            f"📡 <b>اینباندهای قبلی =</b> {', '.join(map(str, current_inbounds))}\n"
            f"📡 <b>اینباندهای جدید ({added_count}) =</b> {', '.join(map(str, valid_new_inbounds))}",
            reply_markup=get_reseller_management_kb(),
            parse_mode="HTML"
        )
        
        await send_reseller_notification(
            message.bot,
            reseller_id,
            "edit",
            panel['panel_name'],
            valid_new_inbounds
        )

    except Exception as e:
        log_error(e)
        await message.answer(
            f"❌ خطا در ویرایش:\n<code>{str(e)}</code>",
            reply_markup=get_reseller_management_kb(),
            parse_mode="HTML"
        )

    del current_action[admin_id]

# ============ Handle Reseller ID for Delete ============

@router.message(
    F.text & ~F.command(),
    lambda m: m.from_user.id in SUPERADMINS and
    current_action.get(m.from_user.id, (None, None))[0] == "get_reseller_id_for_delete"
)
async def handle_reseller_id_for_delete(message: Message):
    """Handle reseller ID input for deletion."""
    admin_id = message.from_user.id

    try:
        reseller_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ لطفاً یک شماره معتبر وارد کنید.")
        return

    data = current_action[admin_id][1]
    panel_id = data['panel_id']

    try:
        reseller_repo = ResellerRepository("data.db")
        panel_repo = PanelRepository("data.db")

        current_inbounds = await reseller_repo.get_reseller_inbounds(reseller_id, panel_id)

        if not current_inbounds:
            await message.answer(
                f"ℹ️ این نماینده در پنل انتخابی هیچ اینباندی ندارد."
            )
            del current_action[admin_id]
            return

        panel = await panel_repo.get_panel_by_id(panel_id)
        await reseller_repo.remove_all_inbounds(reseller_id, panel_id)

        await message.answer(
            f"✅ <b>نماینده با موفقیت حذف شد!</b>\n\n"
            f"🆔 <b>شناسه تلگرام =</b> <code>{reseller_id}</code>\n"
            f"🖥 <b>پنل =</b> {safe_text(panel['panel_name']) if panel else f'Panel {panel_id}'}\n"
            f"📡 <b>اینباندهای حذف شده =</b> {', '.join(map(str, current_inbounds))}",
            reply_markup=get_reseller_management_kb(),
            parse_mode="HTML"
        )
        
        await send_reseller_notification(
            message.bot,
            reseller_id,
            "delete",
            panel['panel_name'] if panel else f'Panel {panel_id}',
            current_inbounds
        )

    except Exception as e:
        log_error(e)
        await message.answer(
            f"❌ خطا در حذف:\n<code>{str(e)}</code>",
            reply_markup=get_reseller_management_kb(),
            parse_mode="HTML"
        )

    del current_action[admin_id]


# ============ Navigation Handlers ============

@router.callback_query(F.data.startswith("cancel_action:reseller"))
async def cancel_action_reseller(query: CallbackQuery):
    """Cancel current action and return to reseller management menu."""
    admin_id = query.from_user.id
    
    if admin_id in current_action:
        del current_action[admin_id]
        
    await query.message.edit_text(
        "❌ عملیات لغو شد.\n\n"
        "👥🔧 <b>مدیریت نماینده‌های فروش</b>\n\n"
        "گزینه مورد نظر را انتخاب کنید:",
        reply_markup=get_reseller_management_kb(),
        parse_mode="HTML"
    )
    await query.answer("✅ عملیات لغو شد")

@router.callback_query(F.data == "back_to_resellers_menu")
async def back_to_resellers_menu(query: CallbackQuery):
    """Return to reseller management menu."""
    if query.from_user.id not in SUPERADMINS:
        return

    admin_id = query.from_user.id
    
    if admin_id in current_action:
        del current_action[admin_id]
        
    await query.message.edit_text(
        "👥🔧 <b>مدیریت نماینده‌های فروش</b>\n\n"
        "گزینه مورد نظر را انتخاب کنید:",
        reply_markup=get_reseller_management_kb(),
        parse_mode="HTML"
    )
    await query.answer()

@router.callback_query(F.data == "back_to_main_menu_superadmin")
async def back_to_main_menu_superadmin_reseller(query: CallbackQuery):
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
async def back_to_main_reseller(query: CallbackQuery):
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
