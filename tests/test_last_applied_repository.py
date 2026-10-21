"""Tests for SqliteLastAppliedSceneRepository (single-row table, v6)."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite
import pytest

from marvin_hue.domain.last_applied_scene import LastAppliedScene
from marvin_hue.persistence.last_applied_repository import (
    LastAppliedSceneRepository,
    SqliteLastAppliedSceneRepository,
)
from marvin_hue.persistence.schema import init_db


@pytest.fixture
async def db_path(tmp_path):
    path = str(tmp_path / "last_applied.sqlite")
    await init_db(path)
    return path


@pytest.fixture
async def repo(db_path):
    repository = await SqliteLastAppliedSceneRepository.open(db_path)
    yield repository
    await repository.close()


async def _row_count(db_path: str) -> int:
    async with aiosqlite.connect(db_path) as conn:
        async with conn.execute("SELECT COUNT(*) FROM last_applied_scene") as cur:
            row = await cur.fetchone()
    assert row is not None
    return int(row[0])


async def test_satisfies_protocol(repo):
    assert isinstance(repo, LastAppliedSceneRepository)


async def test_get_empty_returns_none(repo):
    assert await repo.get() is None


async def test_record_then_get(repo):
    before = datetime.now(timezone.utc)
    recorded = await repo.record("relax", "apply")
    got = await repo.get()

    assert isinstance(got, LastAppliedScene)
    assert got == recorded
    assert got.config_name == "relax"
    assert got.source == "apply"
    assert got.applied_at.tzinfo is not None
    assert got.applied_at >= before


async def test_record_twice_keeps_single_row_with_latest(repo, db_path):
    await repo.record("relax", "apply")
    await repo.record("Pôr do sol", "schedule")

    got = await repo.get()
    assert got is not None
    assert got.config_name == "Pôr do sol"
    assert got.source == "schedule"
    assert await _row_count(db_path) == 1


async def test_clear_nulls_name_and_keeps_row(repo, db_path):
    await repo.record("relax", "apply")
    await repo.clear("lights_off")

    got = await repo.get()
    assert got is not None
    assert got.config_name is None
    assert got.source == "lights_off"
    assert await _row_count(db_path) == 1


async def test_clear_on_empty_table_creates_cleared_row(repo):
    await repo.clear("undo")
    got = await repo.get()
    assert got is not None
    assert got.config_name is None
    assert got.source == "undo"


async def test_record_after_clear(repo):
    await repo.clear("undo")
    await repo.record("relax", "chat")
    got = await repo.get()
    assert got is not None
    assert got.config_name == "relax"
    assert got.source == "chat"


async def test_persists_across_connections(db_path):
    first = await SqliteLastAppliedSceneRepository.open(db_path)
    await first.record("relax", "group")
    await first.close()

    second = await SqliteLastAppliedSceneRepository.open(db_path)
    try:
        got = await second.get()
    finally:
        await second.close()
    assert got is not None
    assert got.config_name == "relax"
    assert got.source == "group"


async def test_close_is_idempotent(db_path):
    repository = await SqliteLastAppliedSceneRepository.open(db_path)
    await repository.close()
    await repository.close()
