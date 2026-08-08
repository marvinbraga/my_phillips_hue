"""Service-layer tests for light registry CRUD + bridge sync (in-memory fake repo)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import pytest

from marvin_hue.domain.lights import (
    LightConflictError,
    LightNotFoundError,
    LightValidationError,
    RegisteredLight,
)
from marvin_hue.services.light_registry import LightRegistryService, _UNSET


class FakeRepo:
    def __init__(self) -> None:
        self._items: dict[str, RegisteredLight] = {}

    async def create(self, light: RegisteredLight) -> RegisteredLight:
        for existing in self._items.values():
            if existing.deleted_at is None and existing.name == light.name:
                raise LightValidationError(f"name already exists: {light.name}")
        self._items[light.id] = light
        return light

    async def get_by_id(
        self, light_id: str, *, include_deleted: bool = False
    ) -> RegisteredLight:
        light = self._items.get(light_id)
        if light is None:
            raise LightNotFoundError(light_id)
        if light.deleted_at is not None and not include_deleted:
            raise LightNotFoundError(light_id)
        return light

    async def get_by_name(
        self, name: str, *, include_deleted: bool = False
    ) -> Optional[RegisteredLight]:
        candidates = [
            light
            for light in self._items.values()
            if light.name == name
            and (include_deleted or light.deleted_at is None)
        ]
        if not candidates:
            return None
        candidates.sort(
            key=lambda x: (x.deleted_at is None, x.updated_at), reverse=True
        )
        return candidates[0]

    async def get_by_bridge_light_id(
        self, bridge_light_id: str, *, include_deleted: bool = False
    ) -> Optional[RegisteredLight]:
        candidates = [
            light
            for light in self._items.values()
            if light.bridge_light_id == bridge_light_id
            and (include_deleted or light.deleted_at is None)
        ]
        if not candidates:
            return None
        candidates.sort(
            key=lambda x: (x.deleted_at is None, x.updated_at), reverse=True
        )
        return candidates[0]

    async def list_all(self, *, include_deleted: bool = False) -> list[RegisteredLight]:
        out = []
        for light in self._items.values():
            if light.deleted_at is not None and not include_deleted:
                continue
            out.append(light)
        return sorted(out, key=lambda x: x.name.lower())

    async def update(self, light: RegisteredLight) -> RegisteredLight:
        if light.id not in self._items:
            raise LightNotFoundError(light.id)
        # Enforce unique active name like SQLite partial unique index
        for existing in self._items.values():
            if (
                existing.id != light.id
                and existing.deleted_at is None
                and light.deleted_at is None
                and existing.name == light.name
            ):
                raise LightValidationError(f"name already exists: {light.name}")
        self._items[light.id] = light
        return light

    async def soft_delete(self, light_id: str) -> RegisteredLight:
        light = await self.get_by_id(light_id, include_deleted=False)
        light.deleted_at = datetime.now(timezone.utc)
        return await self.update(light)

    async def close(self) -> None:
        return None


class FakeBridge:
    def __init__(self, lights: list[dict]):
        self._lights = lights
        self.refresh_calls = 0

    def list_bridge_lights(self) -> list[dict]:
        return list(self._lights)

    def refresh_lights(self) -> None:
        self.refresh_calls += 1


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_generates_uuid_and_persists():
    svc = LightRegistryService(FakeRepo())
    created = await svc.create_light(name="Lâmpada 1", nickname="Mesa")
    assert created.id
    assert created.name == "Lâmpada 1"
    assert created.nickname == "Mesa"
    listed = await svc.list_lights()
    assert len(listed) == 1


@pytest.mark.asyncio
async def test_update_partial_metadata():
    svc = LightRegistryService(FakeRepo())
    created = await svc.create_light(name="Hue Iris")
    updated = await svc.update_light(
        created.id, nickname="Iris", room="Sala", enabled_for_app=False
    )
    assert updated.nickname == "Iris"
    assert updated.room == "Sala"
    assert updated.enabled_for_app is False
    assert updated.name == "Hue Iris"


@pytest.mark.asyncio
async def test_update_clears_nullable_with_none():
    svc = LightRegistryService(FakeRepo())
    created = await svc.create_light(name="ClearMe", nickname="Nick", notes="n")
    updated = await svc.update_light(
        created.id, nickname=None, notes=None, eye_safety_limit_pct=None
    )
    # Explicit None clears; unset fields stay
    assert updated.nickname is None
    assert updated.notes is None
    assert updated.name == "ClearMe"


@pytest.mark.asyncio
async def test_update_unset_does_not_clear():
    svc = LightRegistryService(FakeRepo())
    created = await svc.create_light(name="Keep", nickname="Nick")
    updated = await svc.update_light(created.id, room="Sala")
    assert updated.nickname == "Nick"
    assert updated.room == "Sala"


@pytest.mark.asyncio
async def test_delete_soft():
    svc = LightRegistryService(FakeRepo())
    created = await svc.create_light(name="Fita Led")
    await svc.delete_light(created.id)
    with pytest.raises(LightNotFoundError):
        await svc.get_light(created.id)
    all_rows = await svc.list_lights(include_deleted=True)
    assert len(all_rows) == 1
    assert all_rows[0].is_deleted


@pytest.mark.asyncio
async def test_create_duplicate_name_fails():
    svc = LightRegistryService(FakeRepo())
    await svc.create_light(name="X")
    with pytest.raises(LightConflictError):
        await svc.create_light(name="X")


@pytest.mark.asyncio
async def test_update_name_conflict_raises():
    svc = LightRegistryService(FakeRepo())
    a = await svc.create_light(name="A")
    await svc.create_light(name="B")
    with pytest.raises(LightConflictError):
        await svc.update_light(a.id, name="B")


@pytest.mark.asyncio
async def test_get_light_missing_raises():
    svc = LightRegistryService(FakeRepo())
    with pytest.raises(LightNotFoundError):
        await svc.get_light(str(uuid4()))


@pytest.mark.asyncio
async def test_unset_sentinel_is_unique_object():
    assert _UNSET is not None
    assert _UNSET is not False


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_creates_new_lights():
    repo = FakeRepo()
    bridge = FakeBridge(
        [
            {"name": "Lâmpada 1", "bridge_light_id": "uid-1"},
            {"name": "Hue Play 1", "bridge_light_id": "uid-5"},
        ]
    )
    svc = LightRegistryService(repo, bridge=bridge)
    result = await svc.sync_from_bridge()
    assert result["created"] == 2
    assert result["total_bridge"] == 2
    names = {x.name for x in await svc.list_lights()}
    assert names == {"Lâmpada 1", "Hue Play 1"}


@pytest.mark.asyncio
async def test_sync_updates_bridge_id_and_is_idempotent():
    repo = FakeRepo()
    svc = LightRegistryService(
        repo, bridge=FakeBridge([{"name": "A", "bridge_light_id": "1"}])
    )
    await svc.sync_from_bridge()
    result2 = await svc.sync_from_bridge()
    assert result2["created"] == 0
    assert result2["unchanged"] == 1

    svc2 = LightRegistryService(
        repo, bridge=FakeBridge([{"name": "A", "bridge_light_id": "99"}])
    )
    result3 = await svc2.sync_from_bridge()
    assert result3["updated"] == 1
    light = await svc2.list_lights()
    assert light[0].bridge_light_id == "99"


@pytest.mark.asyncio
async def test_sync_does_not_revive_soft_deleted_by_default():
    repo = FakeRepo()
    svc = LightRegistryService(
        repo, bridge=FakeBridge([{"name": "Ghost", "bridge_light_id": "g1"}])
    )
    await svc.sync_from_bridge()
    light = (await svc.list_lights())[0]
    await svc.delete_light(light.id)

    result = await svc.sync_from_bridge()
    assert result["created"] == 0
    assert result["updated"] == 0
    assert result["skipped_deleted"] == 1
    active = await svc.list_lights(include_deleted=False)
    assert active == []
    deleted = await svc.list_lights(include_deleted=True)
    assert len(deleted) == 1
    assert deleted[0].is_deleted


@pytest.mark.asyncio
async def test_sync_reactivate_deleted_true_revives():
    repo = FakeRepo()
    svc = LightRegistryService(
        repo, bridge=FakeBridge([{"name": "Ghost", "bridge_light_id": "g1"}])
    )
    await svc.sync_from_bridge()
    light = (await svc.list_lights())[0]
    await svc.delete_light(light.id)

    result = await svc.sync_from_bridge(reactivate_deleted=True)
    assert result["updated"] == 1
    active = await svc.list_lights(include_deleted=False)
    assert len(active) == 1
    assert active[0].id == light.id
    assert active[0].deleted_at is None


@pytest.mark.asyncio
async def test_soft_delete_create_same_name_then_sync_attaches_bridge_id():
    repo = FakeRepo()
    svc = LightRegistryService(repo, bridge=None)
    first = await svc.create_light(name="Reuse", bridge_light_id="old-uid")
    await svc.delete_light(first.id)
    second = await svc.create_light(name="Reuse", bridge_light_id=None)
    svc._bridge = FakeBridge(
        [{"name": "Reuse", "bridge_light_id": "old-uid"}]
    )
    result = await svc.sync_from_bridge()
    # Attaches to active row by name; does not revive deleted
    assert result["updated"] == 1 or result["unchanged"] == 1 or result["created"] == 0
    active = await svc.get_light(second.id)
    assert active.bridge_light_id == "old-uid"
    assert active.deleted_at is None
    still_deleted = await svc.get_light(first.id, include_deleted=True)
    assert still_deleted.is_deleted


@pytest.mark.asyncio
async def test_sync_rename_on_bridge_matches_by_bridge_id():
    repo = FakeRepo()
    svc = LightRegistryService(
        repo, bridge=FakeBridge([{"name": "OldName", "bridge_light_id": "stable"}])
    )
    await svc.sync_from_bridge()
    svc._bridge = FakeBridge(
        [{"name": "NewName", "bridge_light_id": "stable"}]
    )
    result = await svc.sync_from_bridge()
    assert result["updated"] == 1
    lights = await svc.list_lights()
    assert len(lights) == 1
    assert lights[0].name == "NewName"
    assert lights[0].bridge_light_id == "stable"


@pytest.mark.asyncio
async def test_refresh_and_sync_calls_refresh():
    bridge = FakeBridge([{"name": "A", "bridge_light_id": "1"}])
    svc = LightRegistryService(FakeRepo(), bridge=bridge)
    await svc.refresh_and_sync()
    assert bridge.refresh_calls == 1


@pytest.mark.asyncio
async def test_sync_without_bridge_raises():
    svc = LightRegistryService(FakeRepo(), bridge=None)
    with pytest.raises(LightValidationError):
        await svc.sync_from_bridge()


@pytest.mark.asyncio
async def test_refresh_and_sync_without_bridge_raises():
    svc = LightRegistryService(FakeRepo(), bridge=None)
    with pytest.raises(LightValidationError):
        await svc.refresh_and_sync()


@pytest.mark.asyncio
async def test_refresh_failure_maps_to_validation_error():
    class BrokenBridge(FakeBridge):
        def refresh_lights(self) -> None:
            raise RuntimeError("bridge offline secret")

    svc = LightRegistryService(
        FakeRepo(), bridge=BrokenBridge([{"name": "A", "bridge_light_id": "1"}])
    )
    with pytest.raises(LightValidationError, match="Unable to refresh"):
        await svc.refresh_and_sync()
