"""Tests for ScheduleRunner loop control."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from marvin_hue.services.schedule_runner import ScheduleRunner


@pytest.mark.asyncio
async def test_runner_start_stop_calls_tick():
    service = MagicMock()
    service.tick = AsyncMock(return_value=[])
    runner = ScheduleRunner(service, poll_seconds=0.05)
    await runner.start()
    assert runner.is_running
    await asyncio.sleep(0.12)
    await runner.stop()
    assert not runner.is_running
    assert service.tick.await_count >= 1


@pytest.mark.asyncio
async def test_runner_double_start_idempotent():
    service = MagicMock()
    service.tick = AsyncMock(return_value=[])
    runner = ScheduleRunner(service, poll_seconds=1.0)
    await runner.start()
    await runner.start()
    await runner.stop()
