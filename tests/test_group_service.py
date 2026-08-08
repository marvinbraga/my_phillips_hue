"""Unit tests for GroupService."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from marvin_hue.basics import LightConfig, LightSetting
from marvin_hue.colors import Color
from marvin_hue.domain.groups import GroupConflictError, GroupNotFoundError
from marvin_hue.domain.lights import RegisteredLight
from marvin_hue.persistence.group_repository import SqliteGroupRepository
from marvin_hue.persistence.light_repository import SqliteLightRegistryRepository
from marvin_hue.persistence.schema import init_db
from marvin_hue.services.group_service import GroupService


@pytest.fixture
async def group_svc(tmp_path):
    path = str(tmp_path / "g.sqlite")
    await init_db(path)
    lights = await SqliteLightRegistryRepository.open(path)
    groups = await SqliteGroupRepository.open(path)
    svc = GroupService(groups)
    yield svc, lights
    await svc.aclose()
    await lights.close()


async def _seed_light(lights, name: str) -> RegisteredLight:
    return await lights.create(
        RegisteredLight(id=str(uuid4()), name=name, bridge_light_id=f"b-{name}")
    )


@pytest.mark.asyncio
async def test_create_list_get(group_svc):
    svc, lights = group_svc
    l1 = await _seed_light(lights, "Hue Iris")
    g = await svc.create_group(name="Sala", room="Living", light_ids=[l1.id])
    assert g.name == "Sala"
    assert g.light_ids == [l1.id]
    listed = await svc.list_groups()
    assert any(x.id == g.id for x in listed)
    got = await svc.get_group(g.id)
    assert got.name == "Sala"


@pytest.mark.asyncio
async def test_duplicate_name_conflict(group_svc):
    svc, _ = group_svc
    await svc.create_group(name="Dup")
    with pytest.raises(GroupConflictError):
        await svc.create_group(name="Dup")


@pytest.mark.asyncio
async def test_set_power_calls_hue(group_svc):
    svc, lights = group_svc
    l1 = await _seed_light(lights, "Lâmpada 1")
    l2 = await _seed_light(lights, "Lâmpada 2")
    g = await svc.create_group(name="Desk", light_ids=[l1.id, l2.id])
    hue = MagicMock()
    hue.turn_on.return_value = True
    hue.turn_off.return_value = True
    result = await svc.set_power(g.id, on=True, hue=hue)
    assert set(result["affected"]) == {"Lâmpada 1", "Lâmpada 2"}
    assert hue.turn_on.call_count == 2


@pytest.mark.asyncio
async def test_apply_config_filters_members(group_svc):
    svc, lights = group_svc
    l1 = await _seed_light(lights, "Lâmpada 1")
    await _seed_light(lights, "Hue Iris")
    g = await svc.create_group(name="Only1", light_ids=[l1.id])
    config = LightConfig(
        name="test",
        settings=[
            LightSetting("Lâmpada 1", Color(255, 0, 0, 200)),
            LightSetting("Hue Iris", Color(0, 255, 0, 200)),
            LightSetting("Other", Color(0, 0, 255, 200)),
        ],
    )
    hue = MagicMock()
    result = await svc.apply_config(g.id, config, hue, transition_time_secs=1)
    assert result["applied_lights"] == ["Lâmpada 1"]
    hue.apply_light_config.assert_called_once()
    applied_cfg = hue.apply_light_config.call_args[0][0]
    assert [s.light_name for s in applied_cfg.settings] == ["Lâmpada 1"]


@pytest.mark.asyncio
async def test_delete_soft(group_svc):
    svc, _ = group_svc
    g = await svc.create_group(name="Temp")
    deleted = await svc.delete_group(g.id)
    assert deleted.deleted_at is not None
    with pytest.raises(GroupNotFoundError):
        await svc.get_group(g.id)
