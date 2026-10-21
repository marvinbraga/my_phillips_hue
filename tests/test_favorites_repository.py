"""Tests for SqliteSceneFavoritesRepository."""

import asyncio

import aiosqlite
import pytest

from marvin_hue.persistence.favorites_repository import (
    SceneFavoritesRepository,
    SqliteSceneFavoritesRepository,
)
from marvin_hue.persistence.schema import init_db


@pytest.fixture
async def db_path(tmp_path):
    path = str(tmp_path / "favorites.sqlite")
    await init_db(path)
    return path


@pytest.fixture
async def repo(db_path):
    repository = await SqliteSceneFavoritesRepository.open(db_path)
    yield repository
    await repository.close()


async def test_satisfies_protocol(repo):
    assert isinstance(repo, SceneFavoritesRepository)


async def test_list_names_empty(repo):
    assert await repo.list_names() == []


async def test_add_and_list_sorted(repo):
    await repo.add("relax")
    await repo.add("Pôr do sol")
    await repo.add("concentration")
    assert await repo.list_names() == ["Pôr do sol", "concentration", "relax"]


async def _created_at(db_path: str, name: str) -> str:
    async with aiosqlite.connect(db_path) as conn:
        async with conn.execute(
            "SELECT created_at FROM scene_favorites WHERE config_name = ?",
            (name,),
        ) as cur:
            row = await cur.fetchone()
    assert row is not None
    assert row[0]
    return str(row[0])


async def test_add_is_idempotent(repo, db_path):
    await repo.add("relax")
    first = await _created_at(db_path, "relax")
    await asyncio.sleep(0.01)
    await repo.add("relax")
    assert await repo.list_names() == ["relax"]
    assert await _created_at(db_path, "relax") == first


async def test_add_many_inserts_and_ignores_existing(repo, db_path):
    await repo.add("relax")
    original = await _created_at(db_path, "relax")
    await asyncio.sleep(0.01)
    await repo.add_many(["relax", "focus", "focus", "night"])
    assert await repo.list_names() == ["focus", "night", "relax"]
    assert await _created_at(db_path, "relax") == original


async def test_add_many_empty_is_noop(repo):
    await repo.add_many([])
    assert await repo.list_names() == []


async def test_add_many_rolls_back_on_failure(repo):
    await repo.add("kept")
    with pytest.raises(Exception):
        # object() não é bindável no SQLite: falha depois de "a" ser inserido.
        await repo.add_many(["a", object()])  # type: ignore[list-item]
    # Um commit posterior não pode "ressuscitar" a linha parcial.
    await repo.add("b")
    assert await repo.list_names() == ["b", "kept"]


async def test_replace_all_rolls_back_on_failure(repo):
    await repo.add("kept")
    with pytest.raises(Exception):
        await repo.replace_all(["a", object()])  # type: ignore[list-item]
    await repo.add("b")
    assert await repo.list_names() == ["b", "kept"]


async def test_remove_is_idempotent(repo):
    await repo.add("relax")
    await repo.remove("relax")
    await repo.remove("relax")
    await repo.remove("never-added")
    assert await repo.list_names() == []


async def test_replace_all(repo):
    await repo.add("old")
    await repo.add("kept")
    # Duplicatas não quebram (INSERT OR IGNORE); normalização é do serviço.
    await repo.replace_all(["kept", "new", "new"])
    assert await repo.list_names() == ["kept", "new"]


async def test_replace_all_empty_clears(repo):
    await repo.add("a")
    await repo.replace_all([])
    assert await repo.list_names() == []


async def test_persists_across_connections(db_path):
    first = await SqliteSceneFavoritesRepository.open(db_path)
    await first.add("relax")
    await first.close()

    second = await SqliteSceneFavoritesRepository.open(db_path)
    try:
        assert await second.list_names() == ["relax"]
    finally:
        await second.close()


async def test_close_is_idempotent(db_path):
    repository = await SqliteSceneFavoritesRepository.open(db_path)
    await repository.close()
    await repository.close()
