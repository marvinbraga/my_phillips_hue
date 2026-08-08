"""Tests for SqliteLightRegistryRepository (create/get/list/update/soft-delete)."""

from uuid import uuid4

import pytest

from marvin_hue.domain.lights import LightNotFoundError, LightValidationError, RegisteredLight
from marvin_hue.persistence.light_repository import SqliteLightRegistryRepository
from marvin_hue.persistence.schema import init_db


@pytest.fixture
async def repo(tmp_path):
    path = str(tmp_path / "lights.sqlite")
    await init_db(path)
    r = await SqliteLightRegistryRepository.open(path)
    yield r
    await r.close()


def _make_light(**kwargs) -> RegisteredLight:
    defaults = dict(
        id=str(uuid4()),
        name="Lâmpada 1",
        nickname="Mesa",
        room="Escritório",
        notes="teste",
        bridge_light_id="00:17:88:01:aa:bb-0b",
        eye_safety_limit_pct=None,
        enabled_for_app=True,
    )
    defaults.update(kwargs)
    return RegisteredLight(**defaults)


@pytest.mark.asyncio
async def test_create_and_get_by_id(repo):
    light = _make_light()
    created = await repo.create(light)
    assert created.id == light.id

    found = await repo.get_by_id(light.id)
    assert found.name == "Lâmpada 1"
    assert found.nickname == "Mesa"
    assert found.bridge_light_id == "00:17:88:01:aa:bb-0b"
    assert found.enabled_for_app is True
    assert found.deleted_at is None


@pytest.mark.asyncio
async def test_get_by_id_missing(repo):
    with pytest.raises(LightNotFoundError):
        await repo.get_by_id("00000000-0000-0000-0000-000000000000")


@pytest.mark.asyncio
async def test_list_excludes_deleted_by_default(repo):
    a = await repo.create(_make_light(name="A", bridge_light_id="id-a"))
    b = await repo.create(_make_light(name="B", bridge_light_id="id-b"))
    await repo.soft_delete(b.id)

    active = await repo.list_all(include_deleted=False)
    names = {x.name for x in active}
    assert names == {"A"}

    all_rows = await repo.list_all(include_deleted=True)
    assert {x.name for x in all_rows} == {"A", "B"}


@pytest.mark.asyncio
async def test_get_by_name_active(repo):
    await repo.create(_make_light(name="Hue Iris", bridge_light_id="id-iris"))
    found = await repo.get_by_name("Hue Iris")
    assert found is not None
    assert found.name == "Hue Iris"


@pytest.mark.asyncio
async def test_get_by_bridge_light_id(repo):
    await repo.create(_make_light(name="Play", bridge_light_id="unique-play"))
    found = await repo.get_by_bridge_light_id("unique-play")
    assert found is not None
    assert found.name == "Play"


@pytest.mark.asyncio
async def test_unique_active_name_raises_domain_error(repo):
    await repo.create(_make_light(name="Dup", bridge_light_id="d1"))
    with pytest.raises(LightValidationError):
        await repo.create(_make_light(name="Dup", bridge_light_id="d2"))


@pytest.mark.asyncio
async def test_update_metadata(repo):
    light = await repo.create(
        _make_light(name="Hue Play 1", nickname=None, bridge_light_id="play-1")
    )
    light.nickname = "Esquerda"
    light.room = "Sala"
    light.eye_safety_limit_pct = 40
    light.enabled_for_app = False
    updated = await repo.update(light)
    assert updated.nickname == "Esquerda"
    assert updated.room == "Sala"
    assert updated.eye_safety_limit_pct == 40
    assert updated.enabled_for_app is False
    assert updated.updated_at >= light.created_at


@pytest.mark.asyncio
async def test_soft_delete_then_get_by_id_hidden(repo):
    light = await repo.create(_make_light(name="Led cima", bridge_light_id="led-top"))
    await repo.soft_delete(light.id)
    with pytest.raises(LightNotFoundError):
        await repo.get_by_id(light.id, include_deleted=False)
    found = await repo.get_by_id(light.id, include_deleted=True)
    assert found.is_deleted is True


@pytest.mark.asyncio
async def test_soft_delete_missing_raises(repo):
    with pytest.raises(LightNotFoundError):
        await repo.soft_delete("00000000-0000-0000-0000-000000000000")


@pytest.mark.asyncio
async def test_soft_delete_then_create_same_name_active(repo):
    first = await repo.create(_make_light(name="Reuse", bridge_light_id="old-id"))
    await repo.soft_delete(first.id)
    second = await repo.create(_make_light(name="Reuse", bridge_light_id=None))
    assert second.deleted_at is None
    assert second.id != first.id
    active = await repo.get_by_name("Reuse", include_deleted=False)
    assert active is not None
    assert active.id == second.id


@pytest.mark.asyncio
async def test_get_by_name_prefers_active_over_deleted(repo):
    deleted = await repo.create(_make_light(name="Prefer", bridge_light_id="p-old"))
    await repo.soft_delete(deleted.id)
    active = await repo.create(_make_light(name="Prefer", bridge_light_id="p-new"))
    found = await repo.get_by_name("Prefer", include_deleted=True)
    assert found is not None
    assert found.id == active.id
    assert found.deleted_at is None


@pytest.mark.asyncio
async def test_get_by_bridge_light_id_prefers_active(repo):
    old = await repo.create(_make_light(name="N1", bridge_light_id="same-bid"))
    await repo.soft_delete(old.id)
    # After soft-delete, bridge_id may still be on deleted row; create another
    # active with different name but same bridge id only if unique index allows
    # (no unique on bridge_id). Prefer active when both exist.
    active = await repo.create(_make_light(name="N2", bridge_light_id="same-bid"))
    found = await repo.get_by_bridge_light_id("same-bid", include_deleted=True)
    assert found is not None
    assert found.id == active.id
