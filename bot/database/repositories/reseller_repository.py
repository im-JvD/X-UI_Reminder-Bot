"""
Reseller repository for database operations.
"""
import aiosqlite
from typing import List, Dict, Set, Optional
import logging

logger = logging.getLogger(__name__)

class ResellerRepository:
    """Repository for reseller-related database operations"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def assign_inbound(
        self,
        telegram_id: int,
        panel_id: int,
        inbound_id: int
    ) -> bool:
        """
        Assign an inbound to a reseller.
        Returns True if successful, False if already exists.
        """
        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute(
                    "INSERT INTO reseller_inbounds (telegram_id, panel_id, inbound_id) VALUES (?, ?, ?)",
                    (telegram_id, panel_id, inbound_id)
                )
                await db.commit()
                logger.info(f"✅ Assigned inbound {inbound_id} to reseller {telegram_id} on panel {panel_id}")
                return True
            except aiosqlite.IntegrityError:
                
                logger.warning(f"⚠️ Inbound {inbound_id} already assigned to reseller {telegram_id} on panel {panel_id}")
                return False
            except Exception as e:
                logger.error(f"❌ Error assigning inbound: {e}")
                return False

    async def get_reseller_inbounds(
        self,
        telegram_id: int,
        panel_id: int
    ) -> List[int]:
        """Get all inbounds for a reseller in a specific panel"""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT inbound_id FROM reseller_inbounds WHERE telegram_id=? AND panel_id=?",
                (telegram_id, panel_id)
            )
            rows = await cur.fetchall()
            return [row[0] for row in rows]

    
    async def get_reseller_inbounds_by_panel(
        self,
        telegram_id: int
    ) -> Dict[int, List[int]]:
        """
        Get all inbounds for a reseller grouped by panel.
        
        Returns:
            Dict mapping panel_id to list of inbound_ids
            Example: {1: [1, 2, 3], 2: [4, 5]}
        """
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT panel_id, inbound_id FROM reseller_inbounds WHERE telegram_id=? ORDER BY panel_id",
                (telegram_id,)
            )
            rows = await cur.fetchall()
            
            result = {}
            for panel_id, inbound_id in rows:
                if panel_id not in result:
                    result[panel_id] = []
                result[panel_id].append(inbound_id)
            
            logger.debug(f"User {telegram_id} has inbounds: {result}")
            return result

    async def get_all_reseller_inbounds(
        self,
        telegram_id: int
    ) -> List[tuple]:
        """Get all inbounds for a reseller across all panels (panel_id, inbound_id)"""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT panel_id, inbound_id FROM reseller_inbounds WHERE telegram_id=?",
                (telegram_id,)
            )
            return await cur.fetchall()

    async def get_reseller_panels(self, telegram_id: int) -> Set[int]:
        """Get all panel IDs assigned to a reseller"""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT DISTINCT panel_id FROM reseller_inbounds WHERE telegram_id=?",
                (telegram_id,)
            )
            rows = await cur.fetchall()
            return {row[0] for row in rows}

    async def remove_all_inbounds(
        self,
        telegram_id: int,
        panel_id: int
    ) -> None:
        """Remove all inbounds for a reseller from a specific panel"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "DELETE FROM reseller_inbounds WHERE telegram_id=? AND panel_id=?",
                (telegram_id, panel_id)
            )
            await db.commit()
            logger.info(f"🗑️ Removed all inbounds for reseller {telegram_id} from panel {panel_id}")

    async def remove_single_inbound(
        self,
        telegram_id: int,
        panel_id: int,
        inbound_id: int
    ) -> bool:
        """Remove a single inbound assignment"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM reseller_inbounds WHERE telegram_id=? AND panel_id=? AND inbound_id=?",
                (telegram_id, panel_id, inbound_id)
            )
            await db.commit()
            return cursor.rowcount > 0

    
    async def update_reseller_inbounds(
        self,
        telegram_id: int,
        panel_id: int,
        inbound_ids: List[int]
    ) -> None:
        """Replace reseller inbounds for a panel"""
        async with aiosqlite.connect(self.db_path) as db:
            
            await db.execute(
                "DELETE FROM reseller_inbounds WHERE telegram_id=? AND panel_id=?",
                (telegram_id, panel_id)
            )
            
            for inbound_id in inbound_ids:
                await db.execute(
                    "INSERT OR IGNORE INTO reseller_inbounds (telegram_id, panel_id, inbound_id) VALUES (?, ?, ?)",
                    (telegram_id, panel_id, inbound_id)
                )

            await db.commit()

    async def get_all_resellers(self) -> List[Dict]:
        """
        Get all resellers with their panel and inbound info.
        Returns list of dicts with keys: telegram_id, panel_id, panel_name, inbound_id
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("""
                SELECT 
                    r.telegram_id, 
                    r.panel_id, 
                    r.inbound_id,
                    p.panel_name
                FROM reseller_inbounds r
                LEFT JOIN panels p ON r.panel_id = p.panel_id
                ORDER BY r.telegram_id, r.panel_id, r.inbound_id
            """)
            rows = await cur.fetchall()
            
            return [
                {
                    'telegram_id': row['telegram_id'],
                    'panel_id': row['panel_id'],
                    'panel_name': row['panel_name'] or f'Panel {row["panel_id"]}',
                    'inbound_id': row['inbound_id']
                }
                for row in rows
            ]

    async def get_all_reseller_ids(self) -> Set[int]:
        """Get all unique reseller telegram IDs"""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("SELECT DISTINCT telegram_id FROM reseller_inbounds")
            rows = await cur.fetchall()
            return {row[0] for row in rows}

    async def reseller_exists_in_panel(
        self,
        telegram_id: int,
        panel_id: int
    ) -> bool:
        """Check if reseller has any inbounds in a panel"""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT COUNT(*) FROM reseller_inbounds WHERE telegram_id=? AND panel_id=?",
                (telegram_id, panel_id)
            )
            count = await cur.fetchone()
            return count[0] > 0 if count else False

    async def get_panels_with_resellers(self) -> List[tuple]:
        """Get panels that have resellers assigned (panel_id, panel_name)"""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("""
                SELECT DISTINCT p.panel_id, p.panel_name
                FROM panels p
                JOIN reseller_inbounds ri ON p.panel_id = ri.panel_id
                ORDER BY p.panel_name
            """)
            return await cur.fetchall()

    
    async def cleanup_orphaned_resellers(self, valid_panel_ids: Set[int]) -> None:
        """Remove reseller assignments for deleted panels"""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT DISTINCT panel_id FROM reseller_inbounds"
            )
            all_panel_ids = {row[0] for row in await cur.fetchall()}

            orphaned = all_panel_ids - valid_panel_ids

            if orphaned:
                placeholders = ','.join('?' * len(orphaned))
                await db.execute(
                    f"DELETE FROM reseller_inbounds WHERE panel_id IN ({placeholders})",
                    tuple(orphaned)
                )
                await db.commit()
                logger.info(f"Cleaned up {len(orphaned)} orphaned panel assignments")