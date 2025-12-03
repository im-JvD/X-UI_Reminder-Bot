"""
Change detection scheduler service.
"""
import asyncio
import logging
from typing import Set

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

from ..database.repositories.reseller_repository import ResellerRepository
from ..database.repositories.report_repository import ReportRepository
from ..services.snapshot_builder import build_snapshot
from ..services.report_formatter import (
    format_expiring_notification,
    format_expired_notification
)
from ..config.settings import SUPERADMINS

logger = logging.getLogger(__name__)

async def check_for_changes(bot: Bot):
    """
    Check for changes in user statuses and send notifications.

    Args:
        bot: Aiogram Bot instance
    """
    logger.info("🔍 Checking for Changes in user Statuses...")

    try:
        users_to_check: Set[int] = set(SUPERADMINS)
        reseller_repo = ResellerRepository("data.db")
        reseller_ids = await reseller_repo.get_all_reseller_ids()
        users_to_check.update(reseller_ids)

        for telegram_id in users_to_check:
            try:
                is_superadmin = telegram_id in SUPERADMINS
                
                current_snap = await build_snapshot(telegram_id)

                if not current_snap:
                    logger.info(f"User {telegram_id}: No panels found, skipping")
                    continue
                    
                report_repo = ReportRepository("data.db")
                last_snap = await report_repo.get_last_snapshot(telegram_id)

                if not last_snap:
                    
                    await report_repo.save_snapshot(telegram_id, current_snap)
                    logger.info(f"User {telegram_id}: First snapshot saved")
                    continue
                    
                for panel_id, current_panel in current_snap.items():
                    panel_id_str = str(panel_id)
                    panel_name = current_panel.get("panel_name", f"Panel {panel_id}")
                    
                    current_lists = current_panel.get("lists", {})
                    current_expiring = set(current_lists.get("expiring", []))
                    current_expired = set(current_lists.get("expired", []))
                    
                    prev_panel = last_snap.get(panel_id_str, {})
                    prev_lists = prev_panel.get("lists", {})
                    prev_expiring = set(prev_lists.get("expiring", []))
                    prev_expired = set(prev_lists.get("expired", []))
                    
                    new_expiring = current_expiring - prev_expiring
                    new_expired = current_expired - prev_expired
                    
                    for email in new_expiring:
                        try:
                            msg = format_expiring_notification(
                                email,
                                panel_name,
                                is_superadmin
                            )
                            await bot.send_message(telegram_id, msg, parse_mode="HTML")
                            logger.info(f"📤 Sent expiring notification for {email} to {telegram_id}")
                            await asyncio.sleep(0.3)
                        except TelegramForbiddenError:
                            logger.warning(f"User {telegram_id} blocked the bot")
                            break
                        except Exception as e:
                            logger.error(f"Failed to send expiring notification: {e}")
                            
                    for email in new_expired:
                        try:
                            msg = format_expired_notification(
                                email,
                                panel_name,
                                is_superadmin
                            )
                            await bot.send_message(telegram_id, msg, parse_mode="HTML")
                            logger.info(f"📤 Sent expired notification for {email} to {telegram_id}")
                            await asyncio.sleep(0.3)
                        except TelegramForbiddenError:
                            logger.warning(f"User {telegram_id} blocked the bot")
                            break
                        except Exception as e:
                            logger.error(f"Failed to send expired notification: {e}")
                            
                await report_repo.save_snapshot(telegram_id, current_snap)

            except TelegramForbiddenError:
                logger.warning(f"User {telegram_id} blocked the bot")
            except Exception as e:
                logger.error(f"Error checking {telegram_id}: {e}", exc_info=True)

    except Exception as e:
        logger.error(f"Error in check_for_changes: {e}", exc_info=True)

    logger.info("✅ Change detection completed.")
