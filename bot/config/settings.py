"""
Configuration management - loads and validates environment variables
"""
import os
import sys
from pathlib import Path
from typing import Set
from dotenv import load_dotenv

env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# ============================================
# Bot Configuration
# ============================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    print("❌ Error: BOT_TOKEN is required in .env file!")
    sys.exit(1)

REQUIRED_CHANNEL_ID = os.getenv("REQUIRED_CHANNEL_ID", "").strip()

SUPERADMINS_STR = os.getenv("SUPERADMINS", "")
SUPERADMINS: Set[int] = set()

if SUPERADMINS_STR:
    try:
        SUPERADMINS = {int(x.strip()) for x in SUPERADMINS_STR.split(",") if x.strip()}
    except ValueError:
        print("❌ Error: SUPERADMINS must be comma-separated integers!")
        sys.exit(1)

if not SUPERADMINS:
    print("❌ Error: At least one SUPERADMIN is required!")
    sys.exit(1)

# ============================================
# Notification Thresholds
# ============================================

try:
    EXPIRING_DAYS_THRESHOLD = int(os.getenv("EXPIRING_DAYS_THRESHOLD", "1"))
    EXPIRING_GB_THRESHOLD = int(os.getenv("EXPIRING_GB_THRESHOLD", "1"))
except ValueError:
    print("❌ Error: Threshold values must be integers!")
    sys.exit(1)
    
EXPIRING_SECONDS_THRESHOLD = EXPIRING_DAYS_THRESHOLD * 24 * 3600
EXPIRING_BYTES_THRESHOLD = EXPIRING_GB_THRESHOLD * (1024**3)

# ============================================
# Scheduler Configuration
# ============================================

try:
    DAILY_REPORT_HOUR = int(os.getenv("DAILY_REPORT_HOUR", "0"))
    DAILY_REPORT_MINUTE = int(os.getenv("DAILY_REPORT_MINUTE", "0"))
    CHANGE_CHECK_INTERVAL_MINUTES = int(os.getenv("CHANGE_CHECK_INTERVAL_MINUTES", "8"))
except ValueError:
    print("❌ Error: Scheduler values must be integers!")
    sys.exit(1)
    
if not (0 <= DAILY_REPORT_HOUR <= 23):
    print(f"⚠️  Warning: Invalid DAILY_REPORT_HOUR ({DAILY_REPORT_HOUR}), using 0")
    DAILY_REPORT_HOUR = 0

if not (0 <= DAILY_REPORT_MINUTE <= 59):
    print(f"⚠️  Warning: Invalid DAILY_REPORT_MINUTE ({DAILY_REPORT_MINUTE}), using 0")
    DAILY_REPORT_MINUTE = 0

if CHANGE_CHECK_INTERVAL_MINUTES < 1:
    print(f"⚠️  Warning: Invalid CHANGE_CHECK_INTERVAL_MINUTES ({CHANGE_CHECK_INTERVAL_MINUTES}), using 8")
    CHANGE_CHECK_INTERVAL_MINUTES = 8

# ============================================
# Database Configuration
# ============================================

DATABASE_PATH = os.getenv("DATABASE_PATH", "data.db")

# ============================================
# Timezone
# ============================================

TIMEZONE = "Asia/Tehran"

# ============================================
# Export all settings
# ============================================

__all__ = [
    'BOT_TOKEN',
    'REQUIRED_CHANNEL_ID',
    'SUPERADMINS',
    'EXPIRING_DAYS_THRESHOLD',
    'EXPIRING_GB_THRESHOLD',
    'EXPIRING_SECONDS_THRESHOLD',
    'EXPIRING_BYTES_THRESHOLD',
    'DAILY_REPORT_HOUR',
    'DAILY_REPORT_MINUTE',
    'CHANGE_CHECK_INTERVAL_MINUTES',
    'DATABASE_PATH',
    'TIMEZONE'
]
