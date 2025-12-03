"""
Main keyboard layouts for bot.
"""
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton
)


def get_main_kb(is_superadmin: bool = False) -> ReplyKeyboardMarkup:
    """
    Get main keyboard based on user role.
    
    Args:
        is_superadmin: Whether user is superadmin
        
    Returns:
        ReplyKeyboardMarkup with appropriate buttons
    """
    if is_superadmin:
        keyboard = [
            [KeyboardButton(text="📊 گزارش کلی")],
            [
                KeyboardButton(text="🔴 منقضی‌شده"),
                KeyboardButton(text="⏰ رو به انقضا"),
                KeyboardButton(text="🟢 کاربران آنلاین")
            ],
            [
                KeyboardButton(text="🧑‍💼 نمایندگان فروش"),
                KeyboardButton(text="🏢 مدیریت پنل‌ها")
            ]
        ]
    else:
        keyboard = [
            [KeyboardButton(text="📊 گزارش کلی")],
            [
                KeyboardButton(text="🔴 منقضی‌شده"),
                KeyboardButton(text="⏰ رو به انقضا"),
                KeyboardButton(text="🟢 کاربران آنلاین")
            ]
        ]
    
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        input_field_placeholder="گزینه مورد نظر را انتخاب کنید ..."
    )


