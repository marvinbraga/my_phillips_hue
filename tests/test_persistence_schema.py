"""Tests for SQLite schema initialization (lights registry)."""

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
