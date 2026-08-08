"""Tests for SqliteGroupRepository."""

from uuid import uuid4

import pytest

from marvin_hue.domain.groups import GroupNotFoundError, GroupValidationError, LightGroup
from marvin_hue.domain.lights import RegisteredLight
from marvin_hue.persistence.group_repository import SqliteGroupRepository
from marvin_hue.persistence.light_repository import SqliteLightRegistryRepository
from marvin_hue.persistence.schema import init_db


@pytest.fixture
async def db_path(tmp_path):
    path = str(tmp_path / "groups.sqlite")
    await init_db(path)
    return path


@pytest.fixture
async def repos(db_path):
    lights = await SqliteLightRegistryRepository.open(db_path)
    groups = await SqliteGroupRepository.open(db_path)
    yield lights, groups
    await groups.close()
    await lights.close()


async def _seed_light(lights_repo, name: str = "Lâmpada 1") -> RegisteredLight:
    return await lights_repo.create(
        RegisteredLight(
            id=str(uuid4()),
            name=name,
            bridge_light_id=f"bid-{name}",
        )
    )


def _make_group(**kwargs) -> LightGroup:
    defaults = dict(
        id=str(uuid4()),
        name="Sala",
        room="Living",
        notes="main",
        light_ids=[],
    )
    defaults.update(kwargs)
    return LightGroup(**defaults)


@pytest.mark.asyncio
async def test_create_and_get_by_id(repos):
    lights, groups = repos
    l1 = await _seed_light(lights, "Hue Iris")
    group = await groups.create(_make_group(name="Iris group", light_ids=[l1.id]))
    found = await groups.get_by_id(group.id)
    assert found.name == "Iris group"
    assert found.room == "Living"
    assert found.light_ids == [l1.id]
    assert found.deleted_at is None


@pytest.mark.asyncio
async def test_get_by_id_missing(repos):
    _, groups = repos
    with pytest.raises(GroupNotFoundError):
        await groups.get_by_id("00000000-0000-0000-0000-000000000000")


@pytest.mark.asyncio
async def test_unique_active_name(repos):
    lights, groups = repos
    await groups.create(_make_group(name="Dup"))
    with pytest.raises(GroupValidationError):
        await groups.create(_make_group(name="Dup"))


@pytest.mark.asyncio
async def test_list_excludes_deleted(repos):
    lights, groups = repos
    a = await groups.create(_make_group(name="A"))
    b = await groups.create(_make_group(name="B"))
    await groups.soft_delete(b.id)
    active = await groups.list_all(include_deleted=False)
    assert {g.name for g in active} == {"A"}
    all_rows = await groups.list_all(include_deleted=True)
    assert {g.name for g in all_rows} == {"A", "B"}


@pytest.mark.asyncio
async def test_set_members_and_list_names(repos):
    lights, groups = repos
    l1 = await _seed_light(lights, "Lâmpada 1")
    l2 = await _seed_light(lights, "Lâmpada 2")
    group = await groups.create(_make_group(name="Pair", light_ids=[]))
    updated = await groups.set_members(group.id, [l1.id, l2.id])
    assert set(updated.light_ids) == {l1.id, l2.id}
    names = await groups.list_member_light_names(group.id)
    assert names == ["Lâmpada 1", "Lâmpada 2"]


@pytest.mark.asyncio
async def test_set_members_invalid_light_id(repos):
    lights, groups = repos
    group = await groups.create(_make_group(name="Empty"))
    with pytest.raises(GroupValidationError):
        await groups.set_members(group.id, ["no-such-light-id"])


@pytest.mark.asyncio
async def test_update_metadata_and_members(repos):
    lights, groups = repos
    l1 = await _seed_light(lights, "Play 1")
    l2 = await _seed_light(lights, "Play 2")
    group = await groups.create(_make_group(name="Old", light_ids=[l1.id]))
    group.name = "New"
    group.room = "Escritório"
    group.light_ids = [l2.id]
    updated = await groups.update(group)
    assert updated.name == "New"
    assert updated.room == "Escritório"
    assert updated.light_ids == [l2.id]


@pytest.mark.asyncio
async def test_soft_delete_hides_group(repos):
    lights, groups = repos
    group = await groups.create(_make_group(name="Gone"))
    await groups.soft_delete(group.id)
    with pytest.raises(GroupNotFoundError):
        await groups.get_by_id(group.id, include_deleted=False)
    found = await groups.get_by_id(group.id, include_deleted=True)
    assert found.is_deleted is True


@pytest.mark.asyncio
async def test_soft_delete_then_reuse_name(repos):
    lights, groups = repos
    first = await groups.create(_make_group(name="Reuse"))
    await groups.soft_delete(first.id)
    second = await groups.create(_make_group(name="Reuse"))
    assert second.id != first.id
    assert second.deleted_at is None


@pytest.mark.asyncio
async def test_list_member_names_skips_soft_deleted_lights(repos):
    lights, groups = repos
    l1 = await _seed_light(lights, "Active")
    l2 = await _seed_light(lights, "Deleted")
    group = await groups.create(_make_group(name="Mix", light_ids=[l1.id, l2.id]))
    await lights.soft_delete(l2.id)
    names = await groups.list_member_light_names(group.id)
    assert names == ["Active"]


@pytest.mark.asyncio
async def test_domain_rejects_empty_name():
    with pytest.raises(GroupValidationError):
        LightGroup(id="x", name="  ")
