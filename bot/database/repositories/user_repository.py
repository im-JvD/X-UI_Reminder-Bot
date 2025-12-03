"""
User repository for database operations.
"""
import aiosqlite
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class UserRepository:
    """Repository for user-related database operations"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
    
    async def ensure_user(self, telegram_id: int) -> bool:
        """
        Ensure user exists in database.
        Returns True if user is new, False if already exists.
        """
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT 1 FROM users WHERE telegram_id=?",
                (telegram_id,)
            )
            row = await cur.fetchone()
            
            if row:
                return False
            
            await db.execute(
                "INSERT INTO users(telegram_id, role) VALUES (?, 'user')",
                (telegram_id,)
            )
            await db.commit()
            return True
    
    async def user_exists(self, telegram_id: int) -> bool:
        """Check if user exists"""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT 1 FROM users WHERE telegram_id=?",
                (telegram_id,)
            )
            return await cur.fetchone() is not None
    
    async def get_user_role(self, telegram_id: int) -> Optional[str]:
        """Get user role"""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT role FROM users WHERE telegram_id=?",
                (telegram_id,)
            )
            row = await cur.fetchone()
            return row[0] if row else None
    
    async def set_user_role(self, telegram_id: int, role: str) -> None:
        """Set user role"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE users SET role=? WHERE telegram_id=?",
                (role, telegram_id)
            )
            await db.commit()
