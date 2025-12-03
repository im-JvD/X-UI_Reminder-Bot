import asyncio
import aiosqlite
import logging

logging.basicConfig(level=logging.INFO)

async def migrate_database():
    """Migrate existing database to new schema"""
    print("🔄 Starting database migration...")
    
    async with aiosqlite.connect("data.db") as db:
        
        await db.execute("PRAGMA foreign_keys = ON")
        
        await db.executescript("""
        -- Panels table
        CREATE TABLE IF NOT EXISTS panels (
            panel_id INTEGER PRIMARY KEY AUTOINCREMENT,
            panel_name TEXT UNIQUE NOT NULL,
            base_url TEXT NOT NULL,
            web_base_path TEXT,
            username TEXT NOT NULL,
            password TEXT NOT NULL
        );

        -- Users table
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            role TEXT NOT NULL DEFAULT 'user'
        );

        -- Reseller inbounds mapping
        CREATE TABLE IF NOT EXISTS reseller_inbounds (
            telegram_id INTEGER NOT NULL,
            panel_id INTEGER NOT NULL,
            inbound_id INTEGER NOT NULL,
            PRIMARY KEY (telegram_id, panel_id, inbound_id),
            FOREIGN KEY (panel_id) REFERENCES panels (panel_id) ON DELETE CASCADE
        );

        -- Keep existing last_reports table
        CREATE TABLE IF NOT EXISTS last_reports (
            telegram_id INTEGER PRIMARY KEY,
            last_json TEXT,
            last_full_report INTEGER
        );
        """)
        
        await db.commit()
        print("✅ Database migration completed successfully!")
        
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = await cursor.fetchall()
        print("\n📋 Current tables in database:")
        for table in tables:
            print(f"  - {table[0]}")
            
            count_cursor = await db.execute(f"SELECT COUNT(*) FROM {table[0]}")
            count = await count_cursor.fetchone()
            print(f"    → {count[0]} rows")

if __name__ == "__main__":
    asyncio.run(migrate_database())
