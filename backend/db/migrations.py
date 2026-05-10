import os
import aiosqlite
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


async def init_db(db_path: str) -> None:
    """Initialize the database, creating all tables if they don't exist."""
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    schema = SCHEMA_PATH.read_text()
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(schema)
        # Incremental migrations — safe to run repeatedly (ALTER TABLE IF NOT EXISTS
        # is not supported in SQLite, so we check via pragma first)
        existing_cols = {
            row[1]
            async for row in await db.execute("PRAGMA table_info(investigations)")
        }
        if "investigation_type" not in existing_cols:
            await db.execute(
                "ALTER TABLE investigations ADD COLUMN investigation_type TEXT DEFAULT 'TWEET'"
            )
        if "last_accessed_at" not in existing_cols:
            await db.execute(
                "ALTER TABLE investigations ADD COLUMN last_accessed_at INTEGER"
            )
        if "access_count" not in existing_cols:
            await db.execute(
                "ALTER TABLE investigations ADD COLUMN access_count INTEGER DEFAULT 1"
            )
        if "search_source" not in existing_cols:
            await db.execute(
                "ALTER TABLE investigations ADD COLUMN search_source TEXT DEFAULT 'API'"
            )

        inv_narrative_cols = {
            row[1]
            async for row in await db.execute("PRAGMA table_info(investigation_narratives)")
        }
        if "seq" not in inv_narrative_cols:
            await db.execute(
                "ALTER TABLE investigation_narratives ADD COLUMN seq INTEGER DEFAULT NULL"
            )

        await db.commit()
