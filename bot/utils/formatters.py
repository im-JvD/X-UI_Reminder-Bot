"""
Data formatting utilities.
"""
import math
from typing import Dict, List


def format_bytes(bytes_value: int) -> str:
    """
    Convert bytes to human-readable format (KB, MB, GB, TB).
    
    Args:
        bytes_value: Size in bytes
        
    Returns:
        Formatted string (e.g., "1.5 GB", "512 MB")
    """
    if bytes_value == 0:
        return "0 B"
        
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    
    k = 1024.0
    magnitude = int(math.floor(math.log(bytes_value, k)))
    
    if magnitude >= len(units):
        magnitude = len(units) - 1
        
    value = bytes_value / math.pow(k, magnitude)
    
    if magnitude == 0:
        return f"{int(value)} {units[magnitude]}"
    elif value >= 100:
        return f"{math.ceil(value)} {units[magnitude]}"
    elif value >= 10:
        return f"{value:.1f} {units[magnitude]}"
    else:
        return f"{value:.2f} {units[magnitude]}"


def format_list_items(items: List[str], prefix: str = "📌") -> str:
    """Format a list of items with prefix"""
    if not items:
        return ""
    return "\n".join([f"{prefix} - [ <code>{item}</code> ]" for item in items])


def format_user_count(count: int, label: str) -> str:
    """Format user count with label"""
    return f"<b>{label} =</b> [ {count} ]"


def format_panel_summary(
    panel_name: str,
    counts: Dict[str, int],
    usage: Dict[str, int]
) -> str:
    """Format panel summary for display"""
    used = format_bytes(usage.get("used", 0))
    
    if usage.get("unlimited", False):
        capacity = "نامحدود"
    else:
        capacity = format_bytes(usage.get("remaining", 0))
    
    return (
        f"🔹 <b>{panel_name}</b>\n"
        f"   💾 مصرف: {used}\n"
        f"   📦 باقیمانده: {capacity}\n"
        f"   👥 کاربران: {counts.get('users', 0)}\n"
        f"   🟢 آنلاین: {counts.get('online', 0)}\n"
    )
