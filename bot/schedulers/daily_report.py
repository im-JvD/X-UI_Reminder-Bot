"""
Daily report scheduler service.
"""
import asyncio
import logging
from typing import Set

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from ..database.repositories.reseller_repository import ResellerRepository
from ..database.repositories.report_repository import ReportRepository
from ..services.snapshot_builder import build_snapshot
from ..services.report_formatter import format_panel_report
from ..config.settings import SUPERADMINS
from ..utils.date_helpers import now_shamsi_str

logger = logging.getLogger(__name__)

async def send_full_reports(bot: Bot):
    """
    Send daily full reports to resellers and superadmins - one message per panel.

    Args:
        bot: Aiogram Bot instance
    """
    try:
        users_to_report: Set[int] = set(SUPERADMINS)
        reseller_repo = ResellerRepository("data.db")
        reseller_ids = await reseller_repo.get_all_reseller_ids()
        users_to_report.update(reseller_ids)

        for telegram_id in users_to_report:
            try:
                panels_snap = await build_snapshot(telegram_id)

                if not panels_snap:
                    logger.info(f"Skipping report for {telegram_id}: No panels found")
                    continue

                is_superadmin = telegram_id in SUPERADMINS
                timestamp = now_shamsi_str()
                
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
                            text="🔄 بروزرسانی به آخرین وضعیت",
                            callback_data=f"refresh_report:{panel_id}"
                        )]]
                    )

                    await bot.send_message(
                        telegram_id,
                        report,
                        reply_markup=kb,
                        parse_mode="HTML"
                    )
                    await asyncio.sleep(0.5)
                    
                report_repo = ReportRepository("data.db")
                await report_repo.save_snapshot(telegram_id, panels_snap)
                await report_repo.update_report_time(telegram_id)

            except TelegramForbiddenError:
                logger.warning(f"❌ User {telegram_id} has blocked the bot")
            except Exception as e:
                logger.error(f"Failed to send report to {telegram_id}: {e}")

    except Exception as e:
        logger.error(f"Error in send_full_reports: {e}", exc_info=True)

    logger.info("✅ Daily Reports Completed.")
