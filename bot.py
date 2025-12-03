import asyncio
import logging
import os
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

# ============ Configuration ============

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)

file_handler = logging.FileHandler("bot.log", encoding="utf-8")
file_handler.setLevel(logging.ERROR)
file_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)

logging.basicConfig(
    level=logging.INFO,
    handlers=[console_handler, file_handler]
)

logger = logging.getLogger(__name__)

env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

logger.info(f"📁 Loading .env from: {env_path}")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    logger.critical("❌ BOT_TOKEN not found in .env file!")
    raise ValueError("❌ BOT_TOKEN not found in .env file!")

logger.info("✅ BOT_TOKEN loaded successfully")

# ============ Bot & Dispatcher ============
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

logger.info("✅ Bot and Dispatcher initialized")

# ============ Main Function ============
async def main():
    """Initialize and start the bot"""

    logger.info("=" * 60)
    logger.info("🚀 Starting X-UI Reminder Bot v2.0.0")
    logger.info("=" * 60)
    
    logger.info("🗄️  STEP 1: Initializing database...")

    try:
        from bot.database.connection import DatabaseManager

        db_manager = DatabaseManager("data.db")
        await db_manager.init_db()

        logger.info("✅ Database initialized successfully!")
    except Exception as e:
        logger.critical(f"❌ Database initialization failed: {e}", exc_info=True)
        raise
        
    logger.info("🔍 STEP 2: Verifying database schema...")

    try:
        import aiosqlite
        async with aiosqlite.connect("data.db") as db:
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = [row[0] for row in await cursor.fetchall()]

            if not tables:
                logger.error("❌ No tables found in database!")
                raise RuntimeError("Database schema not initialized")

            logger.info(f"📋 Available tables: {', '.join(tables)}")

            expected_tables = {'panels', 'users', 'reseller_inbounds', 'last_reports'}
            missing_tables = expected_tables - set(tables)

            if missing_tables:
                logger.error(f"❌ Missing tables: {', '.join(missing_tables)}")
                raise RuntimeError(f"Missing tables: {missing_tables}")

            logger.info("✅ All required tables exist")
    except Exception as e:
        logger.critical(f"❌ Database verification failed: {e}", exc_info=True)
        raise
        
    logger.info("📝 STEP 3: Registering handlers...")

    try:
        from bot.handlers import (
            commands,
            panel_management,
            reseller_management,
            reports,
            status_lists
        )

        dp.include_router(commands.router)
        logger.info("  ✅ Commands handler registered")

        dp.include_router(panel_management.router)
        logger.info("  ✅ Panel management handler registered")

        dp.include_router(reseller_management.router)
        logger.info("  ✅ Reseller management handler registered")

        dp.include_router(reports.router)
        logger.info("  ✅ Reports handler registered")

        dp.include_router(status_lists.router)
        logger.info("  ✅ Status lists handler registered")

        logger.info("✅ All handlers registered successfully!")
    except Exception as e:
        logger.critical(f"❌ Handler registration failed: {e}", exc_info=True)
        raise
        
    logger.info("⏰ STEP 4: Setting up schedulers...")

    try:
        from bot.config.settings import (
            DAILY_REPORT_HOUR,
            DAILY_REPORT_MINUTE,
            CHANGE_CHECK_INTERVAL_MINUTES
        )
        from bot.schedulers.daily_report import send_full_reports
        from bot.schedulers.change_detection import check_for_changes
        from zoneinfo import ZoneInfo

        logger.info(f"  📅 Daily Report Time: {DAILY_REPORT_HOUR:02d}:{DAILY_REPORT_MINUTE:02d} (Asia/Tehran)")
        logger.info(f"  🔄 Change Check Interval: {CHANGE_CHECK_INTERVAL_MINUTES} minutes")
        
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
        logger.info("  ✅ Daily report scheduler configured")
        
        scheduler.add_job(
            check_for_changes,
            'interval',
            minutes=CHANGE_CHECK_INTERVAL_MINUTES,
            timezone=ZoneInfo("Asia/Tehran"),
            id='change_detection',
            replace_existing=True,
            args=[bot]
        )
        logger.info("  ✅ Change detection scheduler configured")
        
        scheduler.start()
        logger.info("✅ All schedulers started successfully!")

    except Exception as e:
        logger.error(f"⚠️  Scheduler setup failed: {e}", exc_info=True)
        logger.warning("⚠️  Bot will continue without schedulers")
        
    logger.info("=" * 60)
    logger.info("🤖 Bot is now running and listening for messages...")
    logger.info("=" * 60)

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        logger.critical(f"❌ Polling error: {e}", exc_info=True)
        raise
    finally:
        logger.info("🔄 Shutting down bot...")
        
        if scheduler.running:
            scheduler.shutdown(wait=False)
            logger.info("  ✅ Scheduler stopped")
            
        await bot.session.close()
        logger.info("  ✅ Bot session closed")

        logger.info("👋 Bot stopped successfully")

# ============ Entry Point ============
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n👋 Bot stopped by user (Ctrl+C)")
    except Exception as e:
        logger.critical(f"❌ Fatal error: {e}", exc_info=True)
        sys.exit(1)
