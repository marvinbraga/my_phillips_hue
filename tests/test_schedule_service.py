"""Unit tests for ScheduleService tick and execute."""

from datetime import datetime, timezone
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from marvin_hue.basics import LightConfig, LightSetting, LightSetupsManager
from marvin_hue.colors import Color
from marvin_hue.persistence.schedule_repository import SqliteScheduleRepository
from marvin_hue.persistence.schema import init_db
from marvin_hue.services.schedule_service import ScheduleService


@pytest.fixture
async def schedule_svc(tmp_path):
    path = str(tmp_path / "s.sqlite")
    await init_db(path)
    repo = await SqliteScheduleRepository.open(path)

    config = LightConfig(
        name="concentration",
        settings=[LightSetting("Lâmpada 1", Color(255, 244, 229, 254))],
        description="test",
    )
    manager = MagicMock(spec=LightSetupsManager)
    manager.get_config.side_effect = lambda n: config if n == "concentration" else None

    hue = MagicMock()
    hue.turn_on.return_value = True
    hue.turn_off.return_value = True
    hue.get_lights_status.return_value = [
        {"name": "Lâmpada 1", "on": False},
        {"name": "Hue Iris", "on": True},
    ]

    svc = ScheduleService(repo, hue=hue, manager=manager)
    yield svc, hue, manager
    await svc.aclose()


@pytest.mark.asyncio
async def test_create_and_list(schedule_svc):
    svc, _, _ = schedule_svc
    s = await svc.create_schedule(
        name="Morning",
        time_hhmm="07:30",
        action_type="power_on",
        days_of_week="0,1,2,3,4",
    )
    assert s.enabled is True
    listed = await svc.list_schedules()
    assert len(listed) == 1


@pytest.mark.asyncio
async def test_tick_fires_matching_time(schedule_svc):
    svc, hue, _ = schedule_svc
    await svc.create_schedule(
        name="Now",
        time_hhmm="08:15",
        action_type="power_off",
        days_of_week="",  # every day
    )
    local = datetime(2026, 8, 8, 8, 15, 10, tzinfo=ZoneInfo("America/Sao_Paulo"))
    # Saturday=5 in Python for 2026-08-08
    results = await svc.tick(local)
    assert len(results) == 1
    assert results[0]["status"] == "ok"
    assert hue.turn_off.called

    # Second tick same minute must not double-fire
    results2 = await svc.tick(local)
    assert results2 == []


@pytest.mark.asyncio
async def test_tick_skips_wrong_day(schedule_svc):
    svc, hue, _ = schedule_svc
    await svc.create_schedule(
        name="MonOnly",
        time_hhmm="08:15",
        action_type="power_on",
        days_of_week="0",  # Monday only
    )
    # 2026-08-08 is Saturday (5)
    local = datetime(2026, 8, 8, 8, 15, tzinfo=timezone.utc)
    results = await svc.tick(local)
    assert results == []
    assert not hue.turn_on.called


@pytest.mark.asyncio
async def test_execute_apply_config(schedule_svc):
    svc, hue, manager = schedule_svc
    s = await svc.create_schedule(
        name="Cfg",
        time_hhmm="22:00",
        action_type="apply_config",
        action_payload={"config_name": "concentration"},
    )
    detail = await svc.execute(s)
    assert detail["action"] == "apply_config"
    hue.apply_light_config.assert_called_once()
    manager.get_config.assert_called_with("concentration")


@pytest.mark.asyncio
async def test_run_now(schedule_svc):
    svc, hue, _ = schedule_svc
    s = await svc.create_schedule(
        name="Manual",
        time_hhmm="01:00",
        action_type="power_on",
    )
    result = await svc.run_now(s.id)
    assert result["status"] == "ok"
    assert hue.turn_on.called


# --- last applied scene (issue #14) -------------------------------------


class _FakeLastApplied:
    def __init__(self) -> None:
        self.recorded: list[tuple[str, str]] = []
        self.cleared: list[str] = []

    async def record(self, name: str, *, source: str) -> None:
        self.recorded.append((name, source))

    async def clear(self, *, source: str) -> None:
        self.cleared.append(source)


@pytest.fixture
async def schedule_with_last_applied(schedule_svc):
    base, hue, manager = schedule_svc
    fake = _FakeLastApplied()
    svc = ScheduleService(
        base._repo, hue=hue, manager=manager, last_applied_provider=lambda: fake
    )
    return svc, hue, fake


async def _run(svc: ScheduleService, action_type: str, payload: dict) -> dict:
    sched = await svc.create_schedule(
        name=f"LA {action_type}",
        time_hhmm="19:00",
        action_type=action_type,
        action_payload=payload,
    )
    return await svc.execute(sched)


@pytest.mark.asyncio
async def test_apply_config_schedule_records_last_applied(schedule_with_last_applied):
    from marvin_hue.apply_result import ApplyResult

    svc, hue, fake = schedule_with_last_applied
    hue.apply_light_config.return_value = ApplyResult(applied=("Lâmpada 1",), failed=())
    await _run(svc, "apply_config", {"config_name": "concentration"})
    assert fake.recorded == [("concentration", "schedule")]


@pytest.mark.asyncio
async def test_apply_config_schedule_all_failed_does_not_record(
    schedule_with_last_applied,
):
    from marvin_hue.apply_result import ApplyResult

    svc, hue, fake = schedule_with_last_applied
    hue.apply_light_config.return_value = ApplyResult(
        applied=(), failed=(("Lâmpada 1", "timeout"),)
    )
    await _run(svc, "apply_config", {"config_name": "concentration"})
    assert fake.recorded == []


@pytest.mark.asyncio
async def test_whole_house_power_off_clears_last_applied(schedule_with_last_applied):
    svc, _hue, fake = schedule_with_last_applied
    result = await _run(svc, "power_off", {})
    assert result["scope"] == "all"
    assert fake.cleared == ["schedule_off"]


@pytest.mark.asyncio
async def test_power_on_does_not_clear_last_applied(schedule_with_last_applied):
    svc, _hue, fake = schedule_with_last_applied
    await _run(svc, "power_on", {})
    assert fake.cleared == []


@pytest.mark.asyncio
async def test_group_power_off_does_not_clear_last_applied(schedule_with_last_applied):
    svc, hue, fake = schedule_with_last_applied
    group_service = MagicMock()

    async def set_power(group_id, on, hue):
        return {"group_id": group_id, "on": on, "affected": ["Lâmpada 1"]}

    group_service.set_power = set_power
    svc._group_service = group_service
    await _run(svc, "power_off", {"group_id": "g-1"})
    assert fake.cleared == []
