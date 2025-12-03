"""
Inline keyboard layouts.
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Tuple


def get_panel_management_kb():
    """Get panel management keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ افزودن پنل جدید", callback_data="add_panel")],
            [InlineKeyboardButton(text="🗑 حذف پنل", callback_data="delete_panel")],
            [InlineKeyboardButton(text="📋 لیست پنل‌ها", callback_data="list_panels")],
            [InlineKeyboardButton(text="🔙 بازگشت به منوی اصلی", callback_data="back_to_main")]
        ]
    )


def get_reseller_management_kb() -> InlineKeyboardMarkup:
    """Get reseller management inline keyboard."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ افزودن نماینده جدید", callback_data="add_reseller")],
        [InlineKeyboardButton(text="✏️ ویرایش نماینده", callback_data="edit_reseller")],
        [InlineKeyboardButton(text="❌ حذف نماینده", callback_data="delete_reseller")],
        [InlineKeyboardButton(text="📋 لیست نماینده‌ها", callback_data="list_resellers")],
        [InlineKeyboardButton(text="🔙 بازگشت به منوی اصلی", callback_data="back_to_main")]
    ])

def get_cancel_kb(context: str = "general") -> InlineKeyboardMarkup:
    """
    Simple cancel keyboard with context-specific callback.
    
    Args:
        context: Context identifier (e.g., 'panel', 'reseller', 'general')
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="❌ لغو عملیات", 
            callback_data=f"cancel_action:{context}"
        )]
    ])



def get_back_to_main_kb(for_superadmin: bool = False) -> InlineKeyboardMarkup:
    """Back to main menu keyboard"""
    callback = "back_to_main_menu_superadmin" if for_superadmin else "back_to_main"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 بازگشت به منوی اصلی", callback_data=callback)]
    ])


def get_panel_selection_kb(
    panels: List[Tuple[int, str]],
    action: str,
    back_callback: str = "back_to_main"
) -> InlineKeyboardMarkup:
    """
    Create panel selection keyboard.

    Args:
        panels: List of (panel_id, panel_name) tuples
        action: Action type (e.g., 'add', 'edit', 'delete')
        back_callback: Callback data for back button
    """
    buttons = []
    for panel_id, panel_name in panels:
        buttons.append([InlineKeyboardButton(
            text=f"🔷 {panel_name}",
            callback_data=f"select_panel_for_reseller:{action}:{panel_id}"
        )])
        
    buttons.append([InlineKeyboardButton(
        text="⬅️ بازگشت",
        callback_data=back_callback
    )])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_refresh_report_kb(panel_id: int) -> InlineKeyboardMarkup:
    """Keyboard with refresh button for reports"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="↻️ بروزرسانی به آخرین وضعیت",
            callback_data=f"refresh_report:{panel_id}"
        )]
    ])


def get_pagination_kb(
    current_page: int,
    total_pages: int,
    callback_prefix: str
) -> InlineKeyboardMarkup:
    """
    Create pagination keyboard.
    
    Args:
        current_page: Current page number (0-indexed)
        total_pages: Total number of pages
        callback_prefix: Prefix for callback data
    """
    buttons = []
    
    if current_page > 0:
        buttons.append(InlineKeyboardButton(
            text="◀️ قبلی",
            callback_data=f"{callback_prefix}:{current_page - 1}"
        ))
        
    buttons.append(InlineKeyboardButton(
        text=f"📄 {current_page + 1}/{total_pages}",
        callback_data="noop"
    ))
    
    if current_page < total_pages - 1:
        buttons.append(InlineKeyboardButton(
            text="بعدی ▶️",
            callback_data=f"{callback_prefix}:{current_page + 1}"
        ))
    
    return InlineKeyboardMarkup(inline_keyboard=[buttons])
