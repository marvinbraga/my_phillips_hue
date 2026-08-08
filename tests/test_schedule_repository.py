"""Tests for SqliteScheduleRepository."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from marvin_hue.domain.schedules import (
    Schedule,
    ScheduleNotFoundError,
    ScheduleValidationError,
)
from marvin_hue.persistence.schedule_repository import SqliteScheduleRepository
from marvin_hue.persistence.schema import init_db


@pytest.fixture
async def repo(tmp_path):
    path = str(tmp_path / "schedules.sqlite")
    await init_db(path)
    r = await SqliteScheduleRepository.open(path)
    yield r
    await r.close()


def _make_schedule(**kwargs) -> Schedule:
    defaults = dict(
        id=str(uuid4()),
        name="Morning",
        time_hhmm="07:30",
        days_of_week="0,1,2,3,4",
        action_type="apply_config",
        action_payload={"config_name": "Concentration"},
        enabled=True,
    )
    defaults.update(kwargs)
    return Schedule(**defaults)


@pytest.mark.asyncio
async def test_create_and_get_by_id(repo):
    sched = await repo.create(_make_schedule())
    found = await repo.get_by_id(sched.id)
    assert found.name == "Morning"
    assert found.time_hhmm == "07:30"
    assert found.days_of_week == "0,1,2,3,4"
    assert found.weekdays == "0,1,2,3,4"
    assert found.action_type == "apply_config"
    assert found.action_payload == {"config_name": "Concentration"}
    assert found.enabled is True
    assert found.last_run_at is None


@pytest.mark.asyncio
async def test_get_missing(repo):
    with pytest.raises(ScheduleNotFoundError):
        await repo.get_by_id("00000000-0000-0000-0000-000000000000")


@pytest.mark.asyncio
async def test_list_all_and_enabled(repo):
    a = await repo.create(_make_schedule(name="A", enabled=True, time_hhmm="08:00"))
    b = await repo.create(_make_schedule(name="B", enabled=False, time_hhmm="09:00"))
    all_rows = await repo.list_all()
    assert {s.name for s in all_rows} == {"A", "B"}
    enabled = await repo.list_enabled()
    assert {s.name for s in enabled} == {"A"}
    assert enabled[0].id == a.id
    assert b.enabled is False


@pytest.mark.asyncio
async def test_update(repo):
    sched = await repo.create(_make_schedule(name="Old"))
    sched.name = "New"
    sched.enabled = False
    sched.time_hhmm = "22:15"
    sched.days_of_week = "5,6"
    sched.action_type = "power_off"
    sched.action_payload = {}
    updated = await repo.update(sched)
    assert updated.name == "New"
    assert updated.enabled is False
    assert updated.time_hhmm == "22:15"
    assert updated.days_of_week == "5,6"
    assert updated.action_type == "power_off"


@pytest.mark.asyncio
async def test_delete(repo):
    sched = await repo.create(_make_schedule())
    await repo.delete(sched.id)
    with pytest.raises(ScheduleNotFoundError):
        await repo.get_by_id(sched.id)


@pytest.mark.asyncio
async def test_delete_missing(repo):
    with pytest.raises(ScheduleNotFoundError):
        await repo.delete("00000000-0000-0000-0000-000000000000")


@pytest.mark.asyncio
async def test_mark_last_run(repo):
    sched = await repo.create(_make_schedule())
    when = datetime(2026, 8, 8, 7, 30, tzinfo=timezone.utc)
    updated = await repo.mark_last_run(sched.id, when)
    assert updated.last_run_at is not None
    assert updated.last_run_at == when


@pytest.mark.asyncio
async def test_action_type_aliases_normalized():
    s = Schedule(
        id="x",
        name="On",
        time_hhmm="06:00",
        action_type="turn_on",
    )
    assert s.action_type == "power_on"
    s2 = Schedule(
        id="y",
        name="Off",
        time_hhmm="23:00",
        action_type="turn_off",
    )
    assert s2.action_type == "power_off"


@pytest.mark.asyncio
async def test_apply_group_action(repo):
    sched = await repo.create(
        _make_schedule(
            name="Group night",
            action_type="apply_group",
            action_payload={"group_id": "g-1", "config_name": "Cyberpunk"},
        )
    )
    found = await repo.get_by_id(sched.id)
    assert found.action_type == "apply_group"
    assert found.action_payload["group_id"] == "g-1"


@pytest.mark.asyncio
async def test_domain_validation_time_and_days():
    with pytest.raises(ScheduleValidationError):
        Schedule(id="x", name="Bad", time_hhmm="25:00", action_type="power_on")
    with pytest.raises(ScheduleValidationError):
        Schedule(
            id="x",
            name="Bad",
            time_hhmm="10:00",
            action_type="power_on",
            days_of_week="0,9",
        )
    with pytest.raises(ScheduleValidationError):
        Schedule(id="x", name="Bad", time_hhmm="10:00", action_type="explode")


@pytest.mark.asyncio
async def test_allows_weekday():
    s = Schedule(
        id="x",
        name="Weekdays",
        time_hhmm="09:00",
        action_type="power_on",
        days_of_week="0,1,2,3,4",
    )
    assert s.allows_weekday(0) is True
    assert s.allows_weekday(5) is False
    every = Schedule(
        id="y",
        name="Every",
        time_hhmm="09:00",
        action_type="power_on",
        days_of_week="",
    )
    assert every.allows_weekday(6) is True
