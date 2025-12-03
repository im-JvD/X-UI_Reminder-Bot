"""
Scheduler configuration and setup.
"""
import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot

from .daily_report import send_full_reports
from .change_detection import check_for_changes
from ..config.settings import (
    DAILY_REPORT_HOUR,
    DAILY_REPORT_MINUTE,
    CHANGE_CHECK_INTERVAL_MINUTES
)

logger = logging.getLogger(__name__)

def setup_schedulers(scheduler: AsyncIOScheduler, bot: Bot):
    """
    Configure and add all scheduled jobs.

    Args:
        scheduler: APScheduler instance
        bot: Aiogram Bot instance
    """
    
    scheduler.add_job(
        send_full_reports,
        'cron',
        hour=DAILY_REPORT_HOUR,
        minute=DAILY_REPORT_MINUTE,
        timezone=ZoneInfo("Asia/Tehran"),
        id='daily_report',
        replace_existing=True,
        args=[bot]
    )
    
    scheduler.add_job(
        check_for_changes,
        'interval',
        minutes=CHANGE_CHECK_INTERVAL_MINUTES,
        timezone=ZoneInfo("Asia/Tehran"),
        id='change_detection',
        replace_existing=True,
        args=[bot]
    )
    
    logger.info("✅ Schedulers initialized from .env configuration:")
    logger.info(f"🕰 DAILY_REPORT_HOUR = {DAILY_REPORT_HOUR}")
    logger.info(f"🕰 DAILY_REPORT_MINUTE = {DAILY_REPORT_MINUTE}")
    logger.info(f"🔄 CHANGE_CHECK_INTERVAL_MINUTES = {CHANGE_CHECK_INTERVAL_MINUTES}")
