"""Health mirror block reflects the active mirror (screen or audio) — issue #19."""

from __future__ import annotations

from pathlib import Path
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


async def test_both_mirrors_running_audio_wins() -> None:
    block = await _mirror_block(
        screen_mirror=_screen(running=True, fps=25, profile="cinema"),
        audio_mirror=_audio(running=True, fps=30, profile="party"),
    )
    assert block["mode"] == "audio"
    assert block["fps"] == 30
    assert block["profile"] == "party"


async def test_no_mirror_running_reports_stopped() -> None:
    block = await _mirror_block(
        screen_mirror=_screen(running=False, fps=25, profile="cinema"),
        audio_mirror=_audio(running=False, profile="party"),
    )
    # fps/perfil configurados não aparecem enquanto nada está rodando.
    assert block == {
        "running": False,
        "mode": None,
        "fps": None,
        "profile": None,
        "audio": None,
    }


async def test_audio_status_not_running_falls_back_to_screen() -> None:
    """``running`` vem do status lido (corrida entre is_running e get_status)."""
    audio = _audio(running=True)
    audio.get_status.return_value = {**audio.get_status.return_value, "running": False}
    block = await _mirror_block(
        screen_mirror=_screen(running=True, fps=25), audio_mirror=audio
    )
    assert block["mode"] == "screen"
    assert block["audio"] is None


async def test_without_audio_mirror_keeps_screen_behaviour() -> None:
    block = await _mirror_block(screen_mirror=_screen(running=True, fps=12))
    assert block["running"] is True
    assert block["mode"] == "screen"
    assert block["fps"] == 12


_STOPPED = {"running": False, "mode": None, "fps": None, "profile": None, "audio": None}


def _break_screen_status(screen: Mock, audio: Mock) -> None:
    screen.get_status.side_effect = RuntimeError("boom")


def _break_audio_probe(screen: Mock, audio: Mock) -> None:
    audio.is_running.side_effect = RuntimeError("boom")


def _break_audio_status(screen: Mock, audio: Mock) -> None:
    audio.is_running.return_value = True
    audio.get_status.side_effect = RuntimeError("boom")


def _break_screen_probe(screen: Mock, audio: Mock) -> None:
    screen.is_running.side_effect = RuntimeError("boom")


@pytest.mark.parametrize(
    ("breaker", "screen_running", "expected_mode"),
    [
        (_break_screen_status, True, None),
        (_break_audio_probe, True, "screen"),
        (_break_audio_status, True, "screen"),
        (_break_screen_probe, True, "screen"),
    ],
    ids=["screen-status", "audio-is-running", "audio-status", "screen-is-running"],
)
async def test_mirror_probe_failures_degrade(breaker, screen_running, expected_mode) -> None:
    screen = _screen(running=screen_running, fps=25)
    audio = _audio(running=False)
    breaker(screen, audio)
    block = await _mirror_block(screen_mirror=screen, audio_mirror=audio)
    if expected_mode is None:
        assert block == _STOPPED
    else:
        # Um erro no áudio não esconde um espelhamento de tela rodando.
        assert block["mode"] == expected_mode
        assert block["running"] is True
        assert block["fps"] == 25


def test_api_health_reports_audio_mirror(fastapi_test_client, mock_audio_mirror) -> None:
    mock_audio_mirror.is_running.return_value = True
    mock_audio_mirror.get_status.return_value = {
        **mock_audio_mirror.get_status.return_value,
        "running": True,
        "active_profile": "party",
        "bass": 0.5,
        "mid": 0.25,
        "treble": 0.125,
        "beat": 1.0,
        "config_name": "relax",
    }
    response = fastapi_test_client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["mirror"] == {
        "running": True,
        "mode": "audio",
        "fps": 30,
        "profile": "party",
        "audio": {
            "bass": 0.5,
            "mid": 0.25,
            "treble": 0.125,
            "beat": 1.0,
            "config_name": "relax",
        },
    }


def test_health_page_js_shows_mirror_mode() -> None:
    """A página Saúde mostra o modo (Tela/Música) e o template força recarregar o JS."""
    root = Path(__file__).resolve().parent.parent
    js = (root / "web/static/health.js").read_text(encoding="utf-8")
    template = (root / "web/templates/health.html").read_text(encoding="utf-8")
    assert "mirror.mode" in js
    assert "'Tela'" in js and "'Música'" in js
    assert '/static/health.js?v=mirror-mode-1"' in template
