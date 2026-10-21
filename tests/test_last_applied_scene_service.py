"""Tests for LastAppliedSceneService (orphans and cleared rows read as None)."""

from __future__ import annotations

import pytest

from marvin_hue.basics import LightConfig
from marvin_hue.persistence.last_applied_repository import (
    SqliteLastAppliedSceneRepository,
)
from marvin_hue.persistence.schema import init_db
from marvin_hue.services.last_applied_scene import (
    SOURCE_UNDO,
    LastAppliedSceneService,
    clear_after_undo,
    resolve_last_applied,
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
    db_path = str(tmp_path / "last_applied_service.sqlite")
    await init_db(db_path)
    repo = await SqliteLastAppliedSceneRepository.open(db_path)
    manager = _FakeManager(["relax", "Pôr do sol"])
    svc = LastAppliedSceneService(repo, lambda: manager)
    yield svc, repo, manager
    await svc.aclose()


async def test_get_empty_is_none(env):
    svc, _repo, _manager = env
    assert await svc.get() is None


async def test_record_then_get(env):
    svc, _repo, _manager = env
    await svc.record("Pôr do sol", source="apply")
    got = await svc.get()
    assert got is not None
    assert got.config_name == "Pôr do sol"
    assert got.source == "apply"


async def test_clear_then_get_is_none(env):
    svc, repo, _manager = env
    await svc.record("relax", source="apply")
    await svc.clear(source="lights_off")
    assert await svc.get() is None
    raw = await repo.get()
    assert raw is not None and raw.config_name is None


async def test_orphan_scene_reads_as_none(env):
    svc, repo, manager = env
    await svc.record("relax", source="apply")
    manager.names.remove("relax")
    assert await svc.get() is None
    # The row stays (scene may come back after a setups.json edit)
    raw = await repo.get()
    assert raw is not None and raw.config_name == "relax"


async def test_lookup_is_lazy(env):
    """The manager is resolved on every call (follows backup import swaps)."""
    _svc, repo, _manager = env
    managers = [_FakeManager([]), _FakeManager(["relax"])]
    current = {"m": managers[0]}
    svc = LastAppliedSceneService(repo, lambda: current["m"])
    await svc.record("relax", source="apply")
    assert await svc.get() is None
    current["m"] = managers[1]
    got = await svc.get()
    assert got is not None and got.config_name == "relax"


class _BrokenRepo:
    async def get(self):
        return None

    async def record(self, config_name, source):
        raise RuntimeError("database is locked")

    async def clear(self, source):
        raise RuntimeError("database is locked")

    async def close(self):
        return None


async def test_record_and_clear_are_fail_open():
    svc = LastAppliedSceneService(_BrokenRepo(), lambda: _FakeManager(["relax"]))
    await svc.record("relax", source="apply")  # no exception
    await svc.clear(source="lights_off")  # no exception


async def test_clear_refreshes_applied_at(env):
    svc, repo, _manager = env
    await svc.record("relax", source="apply")
    recorded = await repo.get()
    await svc.clear(source="undo")
    cleared = await repo.get()
    assert recorded is not None and cleared is not None
    assert cleared.applied_at >= recorded.applied_at
    assert cleared.source == "undo"


# --- shared helpers -----------------------------------------------------


class _FakeClear:
    def __init__(self) -> None:
        self.sources: list[str] = []

    async def clear(self, *, source: str) -> None:
        self.sources.append(source)


async def test_clear_after_undo_clears_when_lights_restored():
    fake = _FakeClear()
    await clear_after_undo(fake, {"restored_count": 2})
    assert fake.sources == [SOURCE_UNDO]


@pytest.mark.parametrize("result", [{"restored_count": 0}, {}, {"restored_count": None}])
async def test_clear_after_undo_keeps_record_when_nothing_restored(result):
    fake = _FakeClear()
    await clear_after_undo(fake, result)
    assert fake.sources == []


async def test_clear_after_undo_without_service():
    await clear_after_undo(None, {"restored_count": 3})


def test_resolve_last_applied():
    marker = object()
    assert resolve_last_applied(None) is None
    assert resolve_last_applied(lambda: marker) is marker  # type: ignore[arg-type,return-value]

    def broken():
        raise RuntimeError("not initialized")

    assert resolve_last_applied(broken) is None
