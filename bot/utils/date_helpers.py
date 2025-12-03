"""
Date and time utilities for Shamsi calendar.
"""
import jdatetime
from datetime import datetime
from zoneinfo import ZoneInfo

def now_shamsi_str() -> str:
    """
    Get current time in Shamsi (Jalali) format with Tehran timezone.

    Returns:
        Formatted string like "1404/09/10 - 14:30"
    """
    try:
        
        now_tehran = datetime.now(ZoneInfo("Asia/Tehran"))
        now_jalali = jdatetime.datetime.fromgregorian(datetime=now_tehran)
        
        return now_jalali.strftime("[ %Y/%m/%d ] - [ %H:%M:%S ]")

    except Exception:
        
        now_greg = datetime.now(ZoneInfo("Asia/Tehran"))
        return now_greg.strftime("%Y/%m/%d - %H:%M")

def get_shamsi_date() -> str:
    """Get current Shamsi date only with Tehran timezone"""
    now = datetime.now(ZoneInfo("Asia/Tehran"))
    shamsi = jdatetime.datetime.fromgregorian(datetime=now)
    return shamsi.strftime("%Y/%m/%d")

def get_shamsi_time() -> str:
    """Get current Tehran time only"""
    now = datetime.now(ZoneInfo("Asia/Tehran"))
    return now.strftime("%H:%M:%S")

def format_timestamp_shamsi(timestamp: int) -> str:
    """Convert Unix timestamp to Shamsi datetime string with Tehran timezone"""
    dt = datetime.fromtimestamp(timestamp, tz=ZoneInfo("Asia/Tehran"))
    shamsi = jdatetime.datetime.fromgregorian(datetime=dt)
    return shamsi.strftime("%Y/%m/%d - %H:%M:%S")
