"""Unit tests for health schedules block (runner_alive + enabled_count)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from marvin_hue.services.health import collect_health


def _fake_hue() -> Mock:
    hue = Mock()
    hue.bridge.get_light_objects.return_value = []
    hue.bridge.ip = "192.168.1.100"
    hue.get_lights_status.return_value = []
    return hue


def _fake_mirror() -> Mock:
    mirror = Mock()
    mirror.get_status.return_value = {
        "running": False,
        "fps": None,
        "profile": None,
    }
    return mirror


async def _collect(**kwargs):
    return await collect_health(
        hue=_fake_hue(),
        screen_mirror=_fake_mirror(),
        chat_agent=None,
        chat_reason="disabled",
        registry=None,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_collect_health_runner_alive_when_running() -> None:
    payload = await _collect(
        schedule_runner=SimpleNamespace(is_running=True),
        schedule_service=None,
    )
    assert payload["schedules"]["runner_alive"] is True
    assert payload["schedules"]["enabled_count"] == 0


@pytest.mark.asyncio
async def test_collect_health_runner_none_is_not_alive() -> None:
    payload = await _collect(schedule_runner=None, schedule_service=None)
    assert payload["schedules"]["runner_alive"] is False
    assert payload["schedules"]["enabled_count"] == 0


@pytest.mark.asyncio
async def test_collect_health_runner_stopped() -> None:
    payload = await _collect(
        schedule_runner=SimpleNamespace(is_running=False),
        schedule_service=None,
    )
    assert payload["schedules"]["runner_alive"] is False


@pytest.mark.asyncio
async def test_collect_health_enabled_count_from_service() -> None:
    service = Mock()
    service.list_schedules = AsyncMock(
        return_value=[
            SimpleNamespace(enabled=True),
            SimpleNamespace(enabled=False),
            SimpleNamespace(enabled=True),
        ]
    )
    payload = await _collect(
        schedule_runner=None,
        schedule_service=service,
    )
    assert payload["schedules"]["enabled_count"] == 2
    assert payload["schedules"]["runner_alive"] is False


@pytest.mark.asyncio
async def test_collect_health_service_none_enabled_count_zero() -> None:
    payload = await _collect(schedule_runner=None, schedule_service=None)
    assert payload["schedules"]["enabled_count"] == 0


@pytest.mark.asyncio
async def test_collect_health_schedule_list_failure_degrades() -> None:
    service = Mock()
    service.list_schedules = AsyncMock(side_effect=RuntimeError("db down"))
    payload = await _collect(schedule_runner=None, schedule_service=service)
    assert payload["schedules"]["enabled_count"] == 0
    assert payload["schedules"]["runner_alive"] is False
