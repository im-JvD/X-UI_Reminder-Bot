"""
Report repository for database operations.
"""
import aiosqlite
import json
import time
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class ReportRepository:
    """Repository for report-related database operations"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
    
    async def get_last_snapshot(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Get last saved snapshot for a user"""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT last_json FROM last_reports WHERE telegram_id=?",
                (telegram_id,)
            )
            row = await cur.fetchone()
            
            if not row or not row[0]:
                return None
            
            try:
                return json.loads(row[0])
            except (json.JSONDecodeError, TypeError):
                logger.warning(f"Failed to decode snapshot for user {telegram_id}")
                return None
    
    async def save_snapshot(
        self,
        telegram_id: int,
        snapshot: Dict[str, Any]
    ) -> None:
        """Save current snapshot for a user"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO last_reports(telegram_id, last_json, last_full_report) VALUES (?, ?, ?)",
                (telegram_id, json.dumps(snapshot), int(time.time()))
            )
            await db.commit()
    
    async def get_last_report_time(self, telegram_id: int) -> Optional[int]:
        """Get timestamp of last full report"""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT last_full_report FROM last_reports WHERE telegram_id=?",
                (telegram_id,)
            )
            row = await cur.fetchone()
            return row[0] if row else None
    
    async def update_report_time(self, telegram_id: int) -> None:
        """Update last report timestamp"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE last_reports SET last_full_report=? WHERE telegram_id=?",
                (int(time.time()), telegram_id)
            )
            await db.commit()
