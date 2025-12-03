"""
Database connection management.
"""
import aiosqlite
from typing import AsyncContextManager
from contextlib import asynccontextmanager
import logging

logger = logging.getLogger(__name__)

class DatabaseManager:
    """Manage database connections and operations"""

    def __init__(self, db_path: str = "data.db"):
        """
        Initialize database manager.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        logger.info(f"📁 Database path: {db_path}")

    async def __aenter__(self):
        """Enter async context manager"""
        self.conn = await aiosqlite.connect(self.db_path)
        await self.conn.execute("PRAGMA foreign_keys = ON")
        return self.conn

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit async context manager"""
        if self.conn:
            await self.conn.close()

    @asynccontextmanager
    async def get_connection(self) -> AsyncContextManager[aiosqlite.Connection]:
        """Get database connection with foreign keys enabled"""
        conn = await aiosqlite.connect(self.db_path)
        try:
            await conn.execute("PRAGMA foreign_keys = ON")
            yield conn
        finally:
            await conn.close()

    async def init_db(self):
        """Initialize database schema"""
        async with self.get_connection() as conn:
            await conn.executescript("""
            CREATE TABLE IF NOT EXISTS panels (
                panel_id INTEGER PRIMARY KEY AUTOINCREMENT,
                panel_name TEXT UNIQUE NOT NULL,
                base_url TEXT NOT NULL,
                web_base_path TEXT,
                username TEXT NOT NULL,
                password TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                role TEXT NOT NULL DEFAULT 'user'
            );

            CREATE TABLE IF NOT EXISTS reseller_inbounds (
                telegram_id INTEGER NOT NULL,
                panel_id INTEGER NOT NULL,
                inbound_id INTEGER NOT NULL,
                PRIMARY KEY (telegram_id, panel_id, inbound_id),
                FOREIGN KEY (panel_id) REFERENCES panels (panel_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS last_reports (
                telegram_id INTEGER PRIMARY KEY,
                last_json TEXT,
                last_full_report INTEGER
            );
            """)
            await conn.commit()

        logger.info("✅ Database schema initialized")

    async def execute(self, query: str, params: tuple = ()) -> None:
        """Execute a query"""
        async with self.get_connection() as conn:
            await conn.execute(query, params)
            await conn.commit()

    async def fetchone(self, query: str, params: tuple = ()):
        """Fetch one row"""
        async with self.get_connection() as conn:
            cur = await conn.execute(query, params)
            return await cur.fetchone()

    async def fetchall(self, query: str, params: tuple = ()):
        """Fetch all rows"""
        async with self.get_connection() as conn:
            cur = await conn.execute(query, params)
            return await cur.fetchall()
