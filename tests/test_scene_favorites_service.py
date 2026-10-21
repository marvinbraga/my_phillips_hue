"""Tests for SceneFavoritesService (orphans hidden, unknown scenes rejected)."""

import pytest

from marvin_hue.basics import LightConfig
from marvin_hue.persistence.favorites_repository import SqliteSceneFavoritesRepository
from marvin_hue.persistence.schema import init_db
from marvin_hue.services.scene_favorites import (
    FavoriteConfigNotFoundError,
    SceneFavoritesService,
)


class _FakeManager:
    def __init__(self, names: list[str]) -> None:
        self.names = list(names)

    def get_config(self, name: str) -> LightConfig | None:
        if name in self.names:
            return LightConfig(name=name, settings=[], description="")
        return None


@pytest.fixture
async def env(tmp_path):
    db_path = str(tmp_path / "favorites_service.sqlite")
    await init_db(db_path)
    repo = await SqliteSceneFavoritesRepository.open(db_path)
    manager = _FakeManager(["relax", "concentration", "Pôr do sol"])
    svc = SceneFavoritesService(repo, lambda: manager)
    yield svc, repo, manager
    await svc.aclose()


async def test_list_existing_empty(env):
    svc, _repo, _manager = env
    assert await svc.list_existing() == []


async def test_add_and_list_sorted(env):
    svc, _repo, _manager = env
    await svc.add("relax")
    await svc.add("concentration")
    await svc.add("Pôr do sol")
    assert await svc.list_existing() == ["Pôr do sol", "concentration", "relax"]


async def test_add_unknown_scene_raises(env):
    svc, repo, _manager = env
    with pytest.raises(FavoriteConfigNotFoundError):
        await svc.add("does-not-exist")
    assert await repo.list_names() == []


async def test_add_is_idempotent(env):
    svc, _repo, _manager = env
    await svc.add("relax")
    await svc.add("relax")
    assert await svc.list_existing() == ["relax"]


async def test_remove_is_idempotent(env):
    svc, _repo, _manager = env
    await svc.add("relax")
    await svc.remove("relax")
    await svc.remove("relax")
    await svc.remove("does-not-exist")
    assert await svc.list_existing() == []


async def test_orphans_hidden_but_kept(env):
    """D4: favorito de cena removida fica no banco, mas não aparece no GET."""
    svc, repo, manager = env
    await svc.add("relax")
    await svc.add("concentration")

    manager.names.remove("relax")
    assert await svc.list_existing() == ["concentration"]
    assert await repo.list_names() == ["concentration", "relax"]

    manager.names.append("relax")
    assert await svc.list_existing() == ["concentration", "relax"]


async def test_manager_lookup_called_each_time(tmp_path):
    db_path = str(tmp_path / "lookup.sqlite")
    await init_db(db_path)
    repo = await SqliteSceneFavoritesRepository.open(db_path)
    current = {"manager": _FakeManager(["a"])}
    svc = SceneFavoritesService(repo, lambda: current["manager"])
    try:
        await svc.add("a")
        current["manager"] = _FakeManager(["b"])
        assert await svc.list_existing() == []
        await svc.add("b")
        assert await svc.list_existing() == ["b"]
    finally:
        await svc.aclose()
