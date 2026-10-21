"""Tests for SQLite schema initialization (lights, groups, history, schedules)."""

import aiosqlite
import pytest

from marvin_hue.persistence.schema import CURRENT_SCHEMA_VERSION, init_db


@pytest.fixture
async def db_path(tmp_path):
    return str(tmp_path / "marvin_hue_test.sqlite")


@pytest.mark.asyncio
async def test_init_db_creates_schema_version_and_lights(db_path):
    await init_db(db_path)

    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
        assert row is not None
        assert int(row["version"]) == CURRENT_SCHEMA_VERSION

        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='lights'"
        ) as cur:
            assert await cur.fetchone() is not None


@pytest.mark.asyncio
async def test_init_db_is_idempotent(db_path):
    await init_db(db_path)
    await init_db(db_path)

    async with aiosqlite.connect(db_path) as conn:
        async with conn.execute("SELECT COUNT(*) FROM schema_version") as cur:
            count = (await cur.fetchone())[0]
        # one row per applied version
        assert count == CURRENT_SCHEMA_VERSION


@pytest.mark.asyncio
async def test_lights_table_columns(db_path):
    await init_db(db_path)
    async with aiosqlite.connect(db_path) as conn:
        async with conn.execute("PRAGMA table_info(lights)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
    expected = {
        "id",
        "bridge_light_id",
        "name",
        "nickname",
        "room",
        "notes",
        "eye_safety_limit_pct",
        "enabled_for_app",
        "deleted_at",
        "created_at",
        "updated_at",
    }
    assert expected.issubset(cols)


@pytest.mark.asyncio
async def test_init_db_enables_wal(db_path):
    await init_db(db_path)
    async with aiosqlite.connect(db_path) as conn:
        async with conn.execute("PRAGMA journal_mode") as cur:
            mode = (await cur.fetchone())[0]
    assert str(mode).lower() == "wal"


@pytest.mark.asyncio
async def test_schema_version_is_6(db_path):
    await init_db(db_path)
    assert CURRENT_SCHEMA_VERSION == 6
    async with aiosqlite.connect(db_path) as conn:
        async with conn.execute(
            "SELECT version FROM schema_version ORDER BY version"
        ) as cur:
            versions = [int(r[0]) for r in await cur.fetchall()]
    assert versions == [1, 2, 3, 4, 5, 6]


@pytest.mark.asyncio
async def test_v2_light_groups_tables(db_path):
    await init_db(db_path)
    async with aiosqlite.connect(db_path) as conn:
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('light_groups', 'light_group_members')"
        ) as cur:
            names = {r[0] for r in await cur.fetchall()}
        assert names == {"light_groups", "light_group_members"}

        async with conn.execute("PRAGMA table_info(light_groups)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
        assert {
            "id",
            "name",
            "room",
            "notes",
            "deleted_at",
            "created_at",
            "updated_at",
        }.issubset(cols)

        async with conn.execute("PRAGMA table_info(light_group_members)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
        assert {"group_id", "light_id"}.issubset(cols)


@pytest.mark.asyncio
async def test_v3_scene_snapshots_table(db_path):
    await init_db(db_path)
    async with aiosqlite.connect(db_path) as conn:
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='scene_snapshots'"
        ) as cur:
            assert await cur.fetchone() is not None
        async with conn.execute("PRAGMA table_info(scene_snapshots)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
    assert {"id", "label", "source", "payload_json", "created_at"}.issubset(cols)


@pytest.mark.asyncio
async def test_v4_schedules_table(db_path):
    await init_db(db_path)
    async with aiosqlite.connect(db_path) as conn:
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schedules'"
        ) as cur:
            assert await cur.fetchone() is not None
        async with conn.execute("PRAGMA table_info(schedules)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
    expected = {
        "id",
        "name",
        "enabled",
        "time_hhmm",
        "days_of_week",
        "action_type",
        "action_payload_json",
        "last_run_at",
        "created_at",
        "updated_at",
    }
    assert expected.issubset(cols)


@pytest.mark.asyncio
async def test_v5_scene_favorites_table(db_path):
    await init_db(db_path)
    async with aiosqlite.connect(db_path) as conn:
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='scene_favorites'"
        ) as cur:
            assert await cur.fetchone() is not None
        async with conn.execute("PRAGMA table_info(scene_favorites)") as cur:
            rows = await cur.fetchall()
    cols = {row[1]: row for row in rows}
    assert set(cols) == {"config_name", "created_at"}
    # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
    assert cols["config_name"][5] == 1
    assert cols["config_name"][3] == 1
    assert cols["created_at"][3] == 1


@pytest.mark.asyncio
async def test_v6_last_applied_scene_table(db_path):
    await init_db(db_path)
    async with aiosqlite.connect(db_path) as conn:
        async with conn.execute("PRAGMA table_info(last_applied_scene)") as cur:
            rows = await cur.fetchall()
    cols = {row[1]: row for row in rows}
    assert set(cols) == {"id", "config_name", "source", "applied_at"}
    # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
    assert cols["id"][5] == 1
    assert cols["config_name"][3] == 0  # NULL = cleared (lights off / undo)
    assert cols["source"][3] == 1
    assert cols["applied_at"][3] == 1


@pytest.mark.asyncio
async def test_v6_last_applied_scene_is_single_row(db_path):
    await init_db(db_path)
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO last_applied_scene (id, config_name, source, applied_at) "
            "VALUES (1, 'relax', 'apply', '2026-01-01T00:00:00+00:00')"
        )
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                "INSERT INTO last_applied_scene (id, config_name, source, applied_at) "
                "VALUES (2, 'relax', 'apply', '2026-01-01T00:00:00+00:00')"
            )


@pytest.mark.asyncio
async def test_migration_chain_from_v1_only(tmp_path):
    """Simulate a v1 DB then upgrade by re-running init_db with full migrations."""
    db_path = str(tmp_path / "upgrade.sqlite")
    # Create v1-only schema manually
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            """
            CREATE TABLE schema_version (
                version INTEGER PRIMARY KEY NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE lights (
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
            """
        )
        await conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (1, datetime('now'))"
        )
        await conn.commit()

    await init_db(db_path)

    async with aiosqlite.connect(db_path) as conn:
        async with conn.execute("SELECT version FROM schema_version ORDER BY version") as cur:
            versions = [int(r[0]) for r in await cur.fetchall()]
        assert versions == [1, 2, 3, 4, 5, 6]
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('light_groups', 'scene_snapshots', 'schedules', "
            "'scene_favorites', 'last_applied_scene')"
        ) as cur:
            tables = {r[0] for r in await cur.fetchall()}
    assert tables == {
        "light_groups",
        "scene_snapshots",
        "schedules",
        "scene_favorites",
        "last_applied_scene",
    }
