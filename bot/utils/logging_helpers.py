"""
Logging utilities.
"""
import time
import traceback
import logging

logger = logging.getLogger(__name__)


def log_error(e: Exception) -> None:
    """
    Log exception to file with timestamp and full traceback.
    """
    try:
        with open("log.txt", "a", encoding="utf-8") as f:
            f.write(f"[{time.ctime()}]\n{traceback.format_exc()}\n")
    except Exception as log_ex:
        logger.error(f"Failed to write to log file: {log_ex}")


def setup_logging(level: int = logging.INFO) -> None:
    """Setup logging configuration"""
    logging.basicConfig(
        level=level,
        format="%(levelname)s: %(message)s"
    )
