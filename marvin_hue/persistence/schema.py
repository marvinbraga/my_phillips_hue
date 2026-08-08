"""Versioned SQLite schema for the app-owned database.

Database file: settings.app_db_path (default .res/marvin_hue.sqlite).
Never share tables with chat_memory.sqlite.
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite

CURRENT_SCHEMA_VERSION = 4

# Ordered migrations: version -> list of SQL statements
_MIGRATIONS: dict[int, list[str]] = {
    1: [
        """
        CREATE TABLE IF NOT EXISTS lights (
            id TEXT PRIMARY KEY NOT NULL,
            bridge_light_id TEXT,
            name TEXT NOT NULL,
            nickname TEXT,
            room TEXT,
            notes TEXT,
            eye_safety_limit_pct INTEGER,
            enabled_for_app INTEGER NOT NULL DEFAULT 1,
            deleted_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_lights_name_active
        ON lights(name)
        WHERE deleted_at IS NULL
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_lights_bridge_light_id
        ON lights(bridge_light_id)
        WHERE bridge_light_id IS NOT NULL
        """,
    ],
    2: [
        """
        CREATE TABLE IF NOT EXISTS light_groups (
            id TEXT PRIMARY KEY NOT NULL,
            name TEXT NOT NULL,
            room TEXT,
            notes TEXT,
            deleted_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_light_groups_name_active
        ON light_groups(name)
        WHERE deleted_at IS NULL
        """,
        """
        CREATE TABLE IF NOT EXISTS light_group_members (
            group_id TEXT NOT NULL,
            light_id TEXT NOT NULL,
            PRIMARY KEY (group_id, light_id),
            FOREIGN KEY (group_id) REFERENCES light_groups(id),
            FOREIGN KEY (light_id) REFERENCES lights(id)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_group_members_light
        ON light_group_members(light_id)
        """,
    ],
    3: [
        """
        CREATE TABLE IF NOT EXISTS scene_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT,
            source TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_scene_snapshots_created
        ON scene_snapshots(created_at DESC)
        """,
    ],
    4: [
        """
        CREATE TABLE IF NOT EXISTS schedules (
            id TEXT PRIMARY KEY NOT NULL,
            name TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            time_hhmm TEXT NOT NULL,
            days_of_week TEXT NOT NULL DEFAULT '',
            action_type TEXT NOT NULL,
            action_payload_json TEXT NOT NULL DEFAULT '{}',
            last_run_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_schedules_enabled
        ON schedules(enabled)
        WHERE enabled = 1
        """,
    ],
}


async def _applied_versions(conn: aiosqlite.Connection) -> set[int]:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    await conn.commit()
    async with conn.execute("SELECT version FROM schema_version") as cur:
        rows = await cur.fetchall()
    return {int(r[0]) for r in rows}


async def init_db(db_path: str) -> None:
    """Create parent dir, open DB, apply pending migrations, enable WAL."""
    path = Path(db_path)
    if path.parent and str(path.parent) not in ("", "."):
        path.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        # Optional but recommended for concurrent readers (FastAPI + tools)
        await conn.execute("PRAGMA journal_mode=WAL")
        applied = await _applied_versions(conn)
        for version in sorted(_MIGRATIONS.keys()):
            if version in applied:
                continue
            for statement in _MIGRATIONS[version]:
                await conn.execute(statement)
            await conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, datetime('now'))",
                (version,),
            )
            await conn.commit()
