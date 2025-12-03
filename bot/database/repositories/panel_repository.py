"""
Panel repository for database operations.
"""
import aiosqlite
from typing import Optional, List, Dict, Tuple
import logging

logger = logging.getLogger(__name__)

class PanelRepository:
    """Repository for panel-related database operations"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def add_panel(
        self,
        panel_name: str,
        base_url: str,
        web_base_path: str,
        username: str,
        password: str
    ) -> None:
        """Add a new panel to database"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO panels (panel_name, base_url, web_base_path, username, password)
                VALUES (?, ?, ?, ?, ?)""",
                (panel_name, base_url, web_base_path, username, password)
            )
            await db.commit()

    async def get_panel(self, panel_id: int) -> Optional[Tuple]:
        """Get panel credentials by ID (returns tuple)"""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT base_url, web_base_path, username, password, panel_name FROM panels WHERE panel_id=?",
                (panel_id,)
            )
            return await cur.fetchone()

    async def get_panel_by_id(self, panel_id: int) -> Optional[Dict]:
        """Get panel credentials by ID (returns dictionary)"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT panel_id, panel_name, base_url, web_base_path, username, password FROM panels WHERE panel_id=?",
                (panel_id,)
            )
            row = await cur.fetchone()
            
            if row:
                return {
                    'panel_id': row['panel_id'],
                    'panel_name': row['panel_name'],
                    'base_url': row['base_url'],
                    'web_base_path': row['web_base_path'],
                    'username': row['username'],
                    'password': row['password']
                }
            return None

    async def get_all_panels(self) -> List[Tuple[int, str, str]]:
        """Get all panels (id, name, base_url)"""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("SELECT panel_id, panel_name, base_url FROM panels")
            return await cur.fetchall()

    async def get_panels_with_names(self) -> List[Tuple[int, str]]:
        """Get panel IDs and names"""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("SELECT panel_id, panel_name FROM panels")
            return await cur.fetchall()

    async def delete_panel(self, panel_id: int) -> bool:
        """Delete a panel"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT panel_name FROM panels WHERE panel_id = ?",
                (panel_id,)
            )
            panel = await cursor.fetchone()

            if not panel:
                return False

            await db.execute("DELETE FROM panels WHERE panel_id = ?", (panel_id,))
            await db.commit()
            return True

    async def panel_exists(self, panel_id: int) -> bool:
        """Check if panel exists"""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT 1 FROM panels WHERE panel_id = ?",
                (panel_id,)
            )
            return await cur.fetchone() is not None

    async def get_valid_panel_ids(self) -> set:
        """Get set of all valid panel IDs"""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("SELECT panel_id FROM panels")
            rows = await cur.fetchall()
            return {row[0] for row in rows}
