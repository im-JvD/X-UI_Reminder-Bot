"""
Handlers for viewing user status lists (online/expiring/expired).
"""
import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from ..services.snapshot_builder import build_snapshot
from ..services.report_formatter import format_list
from ..utils.date_helpers import now_shamsi_str
from ..utils.text_helpers import safe_text
from ..utils.logging_helpers import log_error

logger = logging.getLogger(__name__)
router = Router()

STATUS_INFO = {
    "online": {"emoji": "🟢", "title": "کاربران آنلاین"},
    "expiring": {"emoji": "⏳", "title": "کاربران رو به انقضا"},
    "expired": {"emoji": "🔴", "title": "کاربران منقضی‌شده"}
}


@router.message(Command("online"))
@router.message(F.text == "🟢 کاربران آنلاین")
async def online_cmd(message: Message):
    """Show panel selection for online users."""
    await show_panel_selection_for_status(message, "online")


@router.message(Command("expiring"))
@router.message(F.text == "⏰ رو به انقضا")
async def expiring_cmd(message: Message):
    """Show panel selection for expiring users."""
    await show_panel_selection_for_status(message, "expiring")


@router.message(Command("expired"))
@router.message(F.text == "🔴 منقضی‌شده")
async def expired_cmd(message: Message):
    """Show panel selection for expired users."""
    await show_panel_selection_for_status(message, "expired")


async def show_panel_selection_for_status(message: Message, status_type: str):
    """
    Show panel selection for a specific status type.
    
    Args:
        message: User's message
        status_type: 'online', 'expiring', or 'expired'
    """
    try:
        panels_snap = await build_snapshot(message.from_user.id)

        if not panels_snap:
            await message.answer("ℹ️ هیچ داده‌ای برای نمایش وجود ندارد.")
            return

        emoji = STATUS_INFO[status_type]["emoji"]
        title = STATUS_INFO[status_type]["title"]
        
        buttons = []
        for panel_id, snapshot in panels_snap.items():
            panel_name = snapshot["panel_name"]
            count = snapshot["counts"].get(status_type, 0)

            if count > 0:
                buttons.append([InlineKeyboardButton(
                    text=f"🖥 {safe_text(panel_name)} ({count})",
                    callback_data=f"status_panel:{status_type}:{panel_id}"
                )])

        if not buttons:
            await message.answer(f"ℹ️ هیچ کاربر {title} یافت نشد.")
            return
            
        buttons.append([InlineKeyboardButton(
            text="🔙 بازگشت به منوی اصلی",
            callback_data="back_to_main"
        )])

        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        await message.answer(
            f"{emoji} <b>انتخاب پنل برای مشاهده {title}</b>\n\n"
            "پنل مورد نظر خود را از لیست زیر انتخاب نمایید...",
            reply_markup=kb,
            parse_mode="HTML"
        )

    except Exception as e:
        log_error(e)
        logger.error(f"Error showing panel selection: {e}")


@router.callback_query(F.data.startswith("status_panel:"))
async def show_users_by_panel_status(query: CallbackQuery):
    """
    Show users for a specific panel and status.
    Format: status_panel:TYPE:PANEL_ID
    """
    try:
        parts = query.data.split(":")
        status_type = parts[1]
        panel_id = int(parts[2])
    except (IndexError, ValueError):
        await query.answer("❌ خطا در پردازش درخواست", show_alert=True)
        return

    try:
        emoji = STATUS_INFO[status_type]["emoji"]
        title = STATUS_INFO[status_type]["title"]
        
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
            
        header = f"{emoji} <b>{title}</b>\n\n   🖥 <b>پنل =</b> {safe_text(panel_name)}\n\n"
        msg = format_list(header, user_list)
        msg += f"\n\n<b>بروزرسانی در </b>{now_shamsi_str()}"
        
        buttons = []
        
        panel_buttons = []
        for pid, snap in panels_snap.items():
            count = snap["counts"].get(status_type, 0)
            if count > 0:
                panel_buttons.append(InlineKeyboardButton(
                    text="🔘" if pid == panel_id else "⚪️",
                    callback_data=f"status_panel:{status_type}:{pid}"
                ))
                
        for i in range(0, len(panel_buttons), 4):
            buttons.append(panel_buttons[i:i+4])
            
        buttons.append([InlineKeyboardButton(
            text="↻️ بروزرسانی به آخرین وضعیت",
            callback_data=f"refresh_status:{status_type}:{panel_id}"
        )])


        buttons.append([InlineKeyboardButton(
            text="⬅️ بازگشت به لیست پنل‌ها",
            callback_data=f"back_to_panel_list:{status_type}"
        )])

        kb = InlineKeyboardMarkup(inline_keyboard=buttons)

        await query.message.edit_text(msg, reply_markup=kb, parse_mode="HTML")
        await query.answer()

    except Exception as e:
        log_error(e)
        logger.error(f"Error showing users by status: {e}")
        await query.answer("❌ خطا در نمایش اطلاعات", show_alert=True)


@router.callback_query(F.data.startswith("refresh_status:"))
async def refresh_status(query: CallbackQuery):
    """Refresh status list."""
    await show_users_by_panel_status(query)
    await query.answer("✅ بروزرسانی شد", show_alert=False)


@router.callback_query(F.data.startswith("back_to_panel_list:"))
async def back_to_panel_list(query: CallbackQuery):
    """Go back to panel selection list."""
    try:
        status_type = query.data.split(":")[1]
    except IndexError:
        await query.answer("❌ خطا در پردازش درخواست", show_alert=True)
        return

    try:
        panels_snap = await build_snapshot(query.from_user.id)

        if not panels_snap:
            await query.message.edit_text("ℹ️ هیچ داده‌ای برای نمایش وجود ندارد.")
            await query.answer()
            return

        emoji = STATUS_INFO[status_type]["emoji"]
        title = STATUS_INFO[status_type]["title"]

        buttons = []
        for panel_id, snapshot in panels_snap.items():
            panel_name = snapshot["panel_name"]
            count = snapshot["counts"].get(status_type, 0)

            if count > 0:
                buttons.append([InlineKeyboardButton(
                    text=f"🖥 {safe_text(panel_name)} ({count})",
                    callback_data=f"status_panel:{status_type}:{panel_id}"
                )])

        if not buttons:
            await query.message.edit_text(f"ℹ️ هیچ کاربر {title} یافت نشد.")
            await query.answer()
            return

        buttons.append([InlineKeyboardButton(
            text="🔙 بازگشت به منوی اصلی",
            callback_data="back_to_main"
        )])

        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        await query.message.edit_text(
            f"{emoji} <b>انتخاب پنل برای مشاهده {title}</b>\n\n"
            "پنل مورد نظر را از لیست زیر انتخاب نمایید...",
            reply_markup=kb,
            parse_mode="HTML"
        )
        await query.answer()

    except Exception as e:
        log_error(e)
        logger.error(f"Error going back to panel list: {e}")


@router.callback_query(F.data == "back_to_main")
async def back_to_main(query: CallbackQuery):
    """Return to main menu."""
    from ..keyboards.main_keyboards import get_main_kb
    
    await query.message.delete()
    await query.message.answer(
        "🔙 به منوی اصلی بازگشتید.",
        reply_markup=get_main_kb(query.from_user.id)
    )
    await query.answer()
