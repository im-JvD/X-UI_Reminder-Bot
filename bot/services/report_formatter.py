"""
Report formatting service.
"""
from typing import Dict, List

from ..utils.formatters import format_bytes
from ..utils.text_helpers import safe_text

def format_panel_report(
    panel_name: str,
    counts: Dict[str, int],
    usage: Dict,
    is_superadmin: bool = False
) -> str:
    """
    Format report for a single panel.

    Args:
        panel_name: Name of the panel
        counts: Dict with user counts
        usage: Dict with usage data
        is_superadmin: Whether report is for superadmin

    Returns:
        Formatted report string
    """
    used_str = format_bytes(usage.get("used", 0))

    if usage.get("unlimited", False):
        remaining_str = "نامحدود"
        capacity_line = ""
    else:
        remaining_str = format_bytes(usage.get("remaining", 0))
        capacity_line = f"📦 <b>حجم باقی‌مانده:</b> [ {remaining_str} ]\n"

    if is_superadmin:
        header = f"📊 <b>گزارشات مربوط به پنل - [ {safe_text(panel_name)} ]</b>\n\n"
    else:
        header = (
            f"📊 <b>گزارشات مربوط به حساب نمایندگی</b>\n"
            f"🔷 <b>نام پنل =</b> [ {safe_text(panel_name)} ]\n\n"
        )

    return (
        header +
        f"💾 <b>مصرف کل=</b> [ {used_str} ]\n" +
        capacity_line +
        f"👥 <b>کل کاربران =</b> [ {counts.get('users', 0)} ]\n"
        f"🟢 <b>کاربران آنلاین =</b> [ {counts.get('online', 0)} ]\n"
        f"⏰ <b>رو به انقضا =</b> [ {counts.get('expiring', 0)} ]\n"
        f"🔴 <b>منقضی شده =</b> [ {counts.get('expired', 0)} ]"
    )

def format_main_report(counts: Dict[str, int], usage: Dict) -> str:
    """
    Format main combined report.

    Args:
        counts: Dict with combined user counts
        usage: Dict with combined usage data

    Returns:
        Formatted report string
    """
    used_str = format_bytes(usage.get("used", 0))

    if usage.get("unlimited", False):
        remaining_str = "نامحدود"
    else:
        remaining_str = format_bytes(usage.get("remaining", 0))

    return (
        "📊 <b>گزارش نهایی از وضعیت فعلی شما :</b>\n\n"
        f"💾 <b>مصرف کل =</b> [ {used_str} ]\n"
        f"📦 <b>حجم باقی‌مانده =</b> [ {remaining_str} ]\n\n"
        f"👥 <b>کل کاربران =</b> [ {counts.get('users',0)} ]\n"
        f"🟢 <b>کاربران آنلاین =</b> [ {counts.get('online',0)} ]\n"
        f"⏰ <b>رو به انقضا =</b> [ {counts.get('expiring',0)} ]\n"
        f"🔴 <b>منقضی شده =</b> [ {counts.get('expired',0)} ]"
    )

def format_list(header_title: str, items: List[str]) -> str:
    """
    Format a list of items with header.

    Args:
        header_title: Header text
        items: List of items to format

    Returns:
        Formatted list string
    """
    msg = f"{header_title} [ {len(items)} ]\n\n"
    if items:
        msg += "\n".join([f"👤 - [ <code>{safe_text(u)}</code> ]" for u in items])
    return msg

def format_expiring_notification(
    name: str,
    panel_name: str,
    is_superadmin: bool = False
) -> str:
    """Format notification for expiring user"""
    role = "مدیر محترم" if is_superadmin else "نمایندگی محترم"

    return (
        f"🔔 <b>{role} ... </b>\n\n"
        "⏰ اشتراک با مشخصات زیر  <b>[ بزودی ]</b> منقضی خواهد شد ... \n\n"
        f"🔷 <b>پنل =</b> [ {safe_text(panel_name)} ]\n"
        f"👥 <b>کاربر =</b> [ <code>{safe_text(name)}</code> ]\n\n"
        "+ <b>درصورت تمایل نسبت به تمدید مجدد، از داخل پنل مدیریتی خود اقدام نمایید.</b>"
    )

def format_expired_notification(
    name: str,
    panel_name: str,
    is_superadmin: bool = False
) -> str:
    """Format notification for expired user"""
    role = "مدیر محترم" if is_superadmin else "نمایندگی محترم"

    return (
        f"🔔 <b>{role} ... </b>\n\n"
        "🔴 اشتراک با مشخصات زیر  <b>[ منقضی ]</b> گردیده است ... \n\n"
        f"🔷 <b>پنل =</b> [ {safe_text(panel_name)} ]\n"
        f"👥 <b>کاربر =</b> [ <code>{safe_text(name)}</code> ]\n\n"
        "+ <b>درصورت تمایل نسبت به تمدید مجدد، از داخل پنل مدیریتی خود اقدام نمایید.</b>"
    )
