"""
Database schema definitions and initialization.
"""
import aiosqlite
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class DatabaseSchema:
    """Database schema manager"""
    
    SCHEMA_SQL = """
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
    """
    
    @staticmethod
    async def initialize(db_path: str) -> None:
        """Initialize database schema"""
        async with aiosqlite.connect(db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            await db.executescript(DatabaseSchema.SCHEMA_SQL)
            await db.commit()
            logger.info("Database schema checked and ensured.")


async def get_db_connection(db_path: str) -> aiosqlite.Connection:
    """Get database connection with foreign keys enabled"""
    conn = await aiosqlite.connect(db_path)
    await conn.execute("PRAGMA foreign_keys = ON")
    return conn
