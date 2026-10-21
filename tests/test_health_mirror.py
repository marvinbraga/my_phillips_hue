"""Health mirror block reflects the active mirror (screen or audio) — issue #19."""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest

from marvin_hue.services.health import collect_health


def _fake_hue() -> Mock:
    hue = Mock()
    hue.bridge.get_light_objects.return_value = []
    hue.bridge.ip = "192.168.1.100"
    hue.get_lights_status.return_value = []
    return hue


def _screen(*, running: bool, fps: int = 25, profile: str | None = None) -> Mock:
    mirror = Mock()
    mirror.is_running.return_value = running
    mirror.get_status.return_value = {
        "running": running,
        "fps": fps,
        "active_profile": profile,
        "colors": {"Hue Play 1": (1, 2, 3)},
    }
    return mirror


def _audio(*, running: bool, fps: int = 30, profile: str | None = None) -> Mock:
    mirror = Mock()
    mirror.is_running.return_value = running
    mirror.get_status.return_value = {
        "running": running,
        "mode": "audio",
        "fps": fps,
        "active_profile": profile,
        "bass": 0.5,
        "mid": 0.25,
        "treble": 0.125,
        "beat": 1.0,
        "spectrum": [0.1, 0.2],
        "colors": {"Hue Play 1": (1, 2, 3)},
        "config_name": "relax",
    }
    return mirror


async def _mirror_block(**kwargs: Any) -> dict[str, Any]:
    payload = await collect_health(
        hue=_fake_hue(),
        chat_agent=None,
        chat_reason="disabled",
        registry=None,
        **kwargs,
    )
    return payload["mirror"]


@pytest.mark.asyncio
async def test_audio_mirror_running_reports_audio_mode() -> None:
    block = await _mirror_block(
        screen_mirror=_screen(running=False),
        audio_mirror=_audio(running=True, fps=30, profile="party"),
    )
    assert block["running"] is True
    assert block["mode"] == "audio"
    assert block["fps"] == 30
    assert block["profile"] == "party"
    assert block["audio"] == {
        "bass": 0.5,
        "mid": 0.25,
        "treble": 0.125,
        "beat": 1.0,
        "config_name": "relax",
    }


@pytest.mark.asyncio
async def test_screen_mirror_running_reports_screen_mode() -> None:
    block = await _mirror_block(
        screen_mirror=_screen(running=True, fps=25, profile="cinema"),
        audio_mirror=_audio(running=False),
    )
    assert block["running"] is True
    assert block["mode"] == "screen"
    assert block["fps"] == 25
    assert block["profile"] == "cinema"
    assert block["audio"] is None


@pytest.mark.asyncio
async def test_no_mirror_running_reports_stopped() -> None:
    block = await _mirror_block(
        screen_mirror=_screen(running=False),
        audio_mirror=_audio(running=False),
    )
    assert block["running"] is False
    assert block["mode"] is None
    assert block["audio"] is None


@pytest.mark.asyncio
async def test_without_audio_mirror_keeps_screen_behaviour() -> None:
    block = await _mirror_block(screen_mirror=_screen(running=True, fps=12))
    assert block["running"] is True
    assert block["mode"] == "screen"
    assert block["fps"] == 12


@pytest.mark.asyncio
async def test_mirror_status_failure_degrades() -> None:
    audio = _audio(running=True)
    audio.get_status.side_effect = RuntimeError("boom")
    block = await _mirror_block(screen_mirror=_screen(running=False), audio_mirror=audio)
    assert block == {
        "running": False,
        "mode": None,
        "fps": None,
        "profile": None,
        "audio": None,
    }


def test_api_health_reports_audio_mirror(fastapi_test_client, mock_audio_mirror) -> None:
    mock_audio_mirror.is_running.return_value = True
    mock_audio_mirror.get_status.return_value = {
        **mock_audio_mirror.get_status.return_value,
        "running": True,
    }
    response = fastapi_test_client.get("/api/health")
    assert response.status_code == 200
    mirror = response.json()["mirror"]
    assert mirror["running"] is True
    assert mirror["mode"] == "audio"
    assert mirror["fps"] == 30
