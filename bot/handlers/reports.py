"""
Report generation handlers.
"""
import asyncio
import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from ..config.settings import SUPERADMINS
from ..services.snapshot_builder import build_snapshot
from ..services.report_formatter import format_panel_report
from ..utils.date_helpers import now_shamsi_str
from ..keyboards.inline_keyboards import get_refresh_report_kb
from ..utils.logging_helpers import log_error
from ..database.repositories.panel_repository import PanelRepository
from ..database.repositories.report_repository import ReportRepository
logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("report"))
@router.message(F.text == "📊 گزارش کلی")
async def report_cmd(message: Message):
    """Handle report command - send reports for all panels."""
    try:
        panels_snap = await build_snapshot(message.from_user.id)

        if not panels_snap:
            await message.answer(
                "ℹ️ هیچ داده‌ای برای نمایش وجود ندارد.\n\n"
                "🔍 ممکن است:\n"
                "• هنوز اینباندی به شما اختصاص داده نشده باشد\n"
                "• یا اینباندهای اختصاص‌یافته خالی باشند"
            )
            return

        is_superadmin = message.from_user.id in SUPERADMINS
        timestamp = now_shamsi_str()
        
        for panel_id, snapshot in panels_snap.items():
            if snapshot["counts"]["users"] == 0:
                continue

            msg = format_panel_report(
                snapshot["panel_name"],
                snapshot["counts"],
                snapshot["usage"],
                is_superadmin
            ) + f"\n\n<b>بروزرسانی در</b> {timestamp}"

            kb = get_refresh_report_kb(panel_id)
            
            await message.answer(msg, reply_markup=kb, parse_mode="HTML")
            await asyncio.sleep(0.3)

    except Exception as e:
        log_error(e)
        logger.error(f"Error in report command: {e}")


@router.callback_query(F.data.startswith("refresh_report:"))
async def refresh_report(query: CallbackQuery):
    """Handle report refresh callback."""
    try:
        panel_id = int(query.data.split(":")[1])
    except (IndexError, ValueError):
        await query.answer("❌ خطا در شناسایی پنل", show_alert=True)
        return

    try:
        panels_snap = await build_snapshot(query.from_user.id)

        if panel_id not in panels_snap:
            await query.message.edit_text(
                "ℹ️ هیچ داده‌ای برای نمایش وجود ندارد."
            )
            await query.answer()
            return

        snapshot = panels_snap[panel_id]

        if snapshot["counts"]["users"] == 0:
            await query.message.edit_text(
                "ℹ️ هیچ داده‌ای برای نمایش وجود ندارد."
            )
            await query.answer()
            return

        is_superadmin = query.from_user.id in SUPERADMINS
        new_msg = format_panel_report(
            snapshot["panel_name"],
            snapshot["counts"],
            snapshot["usage"],
            is_superadmin
        ) + f"\n\n<b>بروزرسانی در</b> {now_shamsi_str()}"

        kb = get_refresh_report_kb(panel_id)

        if query.message.text != new_msg:
            await query.message.edit_text(new_msg, reply_markup=kb, parse_mode="HTML")
            await query.answer("✅ بروزرسانی شد", show_alert=False)
        else:
            await query.answer("ℹ️ بدون تغییر", show_alert=False)

    except Exception as e:
        log_error(e)
        logger.error(f"Error refreshing report: {e}")
        await query.answer("❌ خطا در بروزرسانی", show_alert=True)
