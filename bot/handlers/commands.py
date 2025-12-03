"""
Basic command handlers for the bot.
"""
import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from ..config.settings import REQUIRED_CHANNEL_ID, SUPERADMINS
from ..database.repositories.user_repository import UserRepository
from ..database.connection import DatabaseManager
from ..keyboards.main_keyboards import get_main_kb
from ..utils.date_helpers import now_shamsi_str
from ..utils.text_helpers import safe_text
from ..utils.logging_helpers import log_error
from ..config.settings import DATABASE_PATH

logger = logging.getLogger(__name__)
router = Router()

async def ensure_user_and_check_new(telegram_id: int) -> bool:
    """
    Ensure user exists in database and return if they're new.

    Args:
        telegram_id: User's Telegram ID

    Returns:
        True if user is new, False otherwise
    """
    user_repo = UserRepository(DATABASE_PATH)
    exists = await user_repo.user_exists(telegram_id)

    if exists:
        return False

    await user_repo.ensure_user(telegram_id)
    return True

@router.message(Command("start"))
async def start_cmd(message: Message, bot):
    """Handle /start command."""
    try:
        
        if REQUIRED_CHANNEL_ID:
            try:
                member = await bot.get_chat_member(
                    REQUIRED_CHANNEL_ID,
                    message.from_user.id
                )
                is_member = member.status in ("member", "administrator", "creator")
            except Exception:
                is_member = False
        else:
            is_member = True

        if not is_member:
            await message.answer(
                f"برای استفاده از ربات ابتدا باید عضو کانال {REQUIRED_CHANNEL_ID} شوید."
            )
            return

        is_new = await ensure_user_and_check_new(message.from_user.id)
        
        is_superadmin = message.from_user.id in SUPERADMINS
        kb = get_main_kb(is_superadmin)

        await message.answer(
            "👋 به ربات گزارش‌دهی X-UI خوش آمدید!",
            reply_markup=kb
        )

        if is_new:
            user = message.from_user
            fullname = (user.first_name or "") + (
                (" " + user.last_name) if user.last_name else ""
            )
            username = f"@{user.username}" if user.username else "N/A"
            user_id = user.id
            date_str = now_shamsi_str()

            notification_text = (
                f"👤 <b>یک کاربر جدید</b> با مشخصات زیر عضو ربات شد...!\n\n"
                f"📛 <b>نام =</b> {safe_text(fullname)}\n"
                f"🆔 <b>یوزرنیم =</b> {username}\n"
                f"🔢 <b>آیدی =</b> [ <code>{user_id}</code> ]\n"
                f"📅 <b>عضویت در =</b> {date_str}"
            )

            for admin_id in SUPERADMINS:
                try:
                    await bot.send_message(admin_id, notification_text, parse_mode="HTML")
                except Exception as e:
                    log_error(e)

    except Exception as e:
        log_error(e)
        logger.error(f"Error in start command: {e}")
