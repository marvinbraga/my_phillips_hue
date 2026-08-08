"""API tests for audio mirror mode and mutual exclusion with screen mirror."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from marvin_hue.audio_mirror import AUDIO_MIRROR_PROFILES, AudioMirror
from marvin_hue.screen_mirror import ScreenMirror


def test_api_list_profiles_includes_audio(fastapi_test_client: TestClient) -> None:
    response = fastapi_test_client.get("/mirror/profiles")
    assert response.status_code == 200
    body = response.json()
    assert set(body["profiles"].keys()) == {"cinema", "fps", "ambient"}
    assert set(body["audio_profiles"].keys()) == {"party", "chill", "pulse"}
    assert body["audio_profiles"]["party"]["fps"] == AUDIO_MIRROR_PROFILES["party"]["fps"]


def test_api_start_audio_mode(fastapi_test_client: TestClient) -> None:
    from marvin_hue.api import dependencies

    audio = MagicMock(spec=AudioMirror)
    running = {"v": False}

    def _start(**_kwargs):
        running["v"] = True
        return True

    audio.is_running.side_effect = lambda: running["v"]
    audio.start.side_effect = _start
    audio.get_status.return_value = {
        "running": True,
        "mode": "audio",
        "fps": 30,
        "brightness": 220,
        "active_profile": "party",
        "colors": {},
        "bass": 0.0,
        "mid": 0.0,
        "treble": 0.0,
    }
    screen = MagicMock(spec=ScreenMirror)
    screen.is_running.return_value = False
    screen.get_status.return_value = {"running": False, "colors": {}}

    orig_a = dependencies._audio_mirror
    orig_s = dependencies._screen_mirror
    dependencies.set_audio_mirror(audio)
    dependencies.set_screen_mirror(screen)
    try:
        response = fastapi_test_client.post(
            "/mirror/start",
            json={"mode": "audio", "profile": "party"},
        )
        assert response.status_code == 200
        audio.start.assert_called_once_with(
            fps=None, brightness=None, profile="party"
        )
        data = response.json()
        assert data["status"]["mode"] == "audio"
        assert "música" in data["message"].lower() or "musica" in data["message"].lower()
    finally:
        dependencies.set_audio_mirror(orig_a)
        dependencies.set_screen_mirror(orig_s)


def test_api_start_audio_wrong_profile_rejected(
    fastapi_test_client: TestClient,
) -> None:
    response = fastapi_test_client.post(
        "/mirror/start",
        json={"mode": "audio", "profile": "cinema"},
    )
    # cinema is valid pydantic (pattern includes it) but route rejects for audio
    assert response.status_code == 400
    assert "audio" in response.json()["detail"].lower()


def test_api_start_screen_wrong_audio_profile_rejected(
    fastapi_test_client: TestClient,
) -> None:
    response = fastapi_test_client.post(
        "/mirror/start",
        json={"mode": "screen", "profile": "party"},
    )
    assert response.status_code == 400


def test_mutual_exclusion_audio_stops_screen(
    fastapi_test_client: TestClient,
) -> None:
    from marvin_hue.api import dependencies

    screen = MagicMock(spec=ScreenMirror)
    screen.is_running.return_value = True
    screen.get_status.return_value = {"running": False, "colors": {}}

    audio = MagicMock(spec=AudioMirror)
    audio.is_running.return_value = False
    audio.get_status.return_value = {
        "running": True,
        "mode": "audio",
        "fps": 30,
        "brightness": 200,
        "colors": {},
        "bass": 0.2,
        "mid": 0.1,
        "treble": 0.05,
    }

    orig_a = dependencies._audio_mirror
    orig_s = dependencies._screen_mirror
    dependencies.set_audio_mirror(audio)
    dependencies.set_screen_mirror(screen)
    try:
        response = fastapi_test_client.post(
            "/mirror/start", json={"mode": "audio", "profile": "chill"}
        )
        assert response.status_code == 200
        screen.stop.assert_called_once()
        audio.start.assert_called_once()
    finally:
        dependencies.set_audio_mirror(orig_a)
        dependencies.set_screen_mirror(orig_s)


def test_mutual_exclusion_screen_stops_audio(
    fastapi_test_client: TestClient,
) -> None:
    from marvin_hue.api import dependencies

    audio = MagicMock(spec=AudioMirror)
    audio.is_running.return_value = True
    audio.get_status.return_value = {"running": False, "mode": "audio", "colors": {}}

    screen = MagicMock(spec=ScreenMirror)
    screen.is_running.return_value = False
    screen.get_status.return_value = {
        "running": True,
        "fps": 25,
        "brightness": 200,
        "colors": {},
    }

    orig_a = dependencies._audio_mirror
    orig_s = dependencies._screen_mirror
    dependencies.set_audio_mirror(audio)
    dependencies.set_screen_mirror(screen)
    try:
        response = fastapi_test_client.post(
            "/mirror/start", json={"mode": "screen", "profile": "cinema"}
        )
        assert response.status_code == 200
        audio.stop.assert_called_once()
        screen.start.assert_called_once()
    finally:
        dependencies.set_audio_mirror(orig_a)
        dependencies.set_screen_mirror(orig_s)


def test_stop_audio_when_running(fastapi_test_client: TestClient) -> None:
    from marvin_hue.api import dependencies

    audio = MagicMock(spec=AudioMirror)
    audio.is_running.return_value = True
    screen = MagicMock(spec=ScreenMirror)
    screen.is_running.return_value = False

    history = MagicMock()
    history.snapshot = MagicMock(return_value=None)

    # snapshot is async in real service
    async def _snap(*_a, **_k):
        return None

    history.snapshot = _snap

    orig_a = dependencies._audio_mirror
    orig_s = dependencies._screen_mirror
    orig_h = dependencies._scene_history_service
    dependencies.set_audio_mirror(audio)
    dependencies.set_screen_mirror(screen)
    dependencies.set_scene_history_service(history)
    try:
        response = fastapi_test_client.post("/mirror/stop")
        assert response.status_code == 200
        audio.stop.assert_called_once()
        screen.stop.assert_not_called()
    finally:
        dependencies.set_audio_mirror(orig_a)
        dependencies.set_screen_mirror(orig_s)
        dependencies.set_scene_history_service(orig_h)


def test_status_includes_mode_and_spectrum(fastapi_test_client: TestClient) -> None:
    from marvin_hue.api import dependencies

    audio = MagicMock(spec=AudioMirror)
    audio.is_running.return_value = True
    audio.get_status.return_value = {
        "running": True,
        "mode": "audio",
        "fps": 30,
        "brightness": 200,
        "colors": {},
        "bass": 0.8,
        "mid": 0.4,
        "treble": 0.2,
        "active_profile": "pulse",
    }
    screen = MagicMock(spec=ScreenMirror)
    screen.is_running.return_value = False
    screen.get_status.return_value = {"running": False, "colors": {}}

    orig_a = dependencies._audio_mirror
    orig_s = dependencies._screen_mirror
    dependencies.set_audio_mirror(audio)
    dependencies.set_screen_mirror(screen)
    try:
        response = fastapi_test_client.get("/mirror/status")
        assert response.status_code == 200
        body = response.json()
        assert body["mode"] == "audio"
        assert body["running"] is True
        assert body["bass"] == 0.8
        assert body["mid"] == 0.4
        assert body["treble"] == 0.2
    finally:
        dependencies.set_audio_mirror(orig_a)
        dependencies.set_screen_mirror(orig_s)


def test_start_audio_device_error_returns_503(
    fastapi_test_client: TestClient,
) -> None:
    from marvin_hue.api import dependencies

    audio = MagicMock(spec=AudioMirror)
    audio.is_running.return_value = False
    audio.start.side_effect = RuntimeError(
        "Nenhum dispositivo de áudio encontrado. No Linux..."
    )
    screen = MagicMock(spec=ScreenMirror)
    screen.is_running.return_value = False
    screen.get_status.return_value = {"running": False, "colors": {}}

    orig_a = dependencies._audio_mirror
    orig_s = dependencies._screen_mirror
    dependencies.set_audio_mirror(audio)
    dependencies.set_screen_mirror(screen)
    try:
        response = fastapi_test_client.post(
            "/mirror/start", json={"mode": "audio"}
        )
        assert response.status_code == 503
        assert "dispositivo" in response.json()["detail"].lower()
    finally:
        dependencies.set_audio_mirror(orig_a)
        dependencies.set_screen_mirror(orig_s)


def test_invalid_mode_rejected(fastapi_test_client: TestClient) -> None:
    response = fastapi_test_client.post(
        "/mirror/start", json={"mode": "karaoke"}
    )
    assert response.status_code == 422


def test_audio_settings_apply_profile(fastapi_test_client: TestClient) -> None:
    from marvin_hue.api import dependencies

    audio = MagicMock(spec=AudioMirror)
    audio.is_running.return_value = True
    audio.get_status.return_value = {
        "running": True,
        "mode": "audio",
        "fps": 35,
        "brightness": 240,
        "active_profile": "pulse",
        "colors": {},
        "bass": 0.0,
        "mid": 0.0,
        "treble": 0.0,
    }
    screen = MagicMock(spec=ScreenMirror)
    screen.is_running.return_value = False
    screen.get_status.return_value = {"running": False, "colors": {}}

    orig_a = dependencies._audio_mirror
    orig_s = dependencies._screen_mirror
    dependencies.set_audio_mirror(audio)
    dependencies.set_screen_mirror(screen)
    try:
        response = fastapi_test_client.post(
            "/mirror/settings",
            json={"mode": "audio", "profile": "pulse", "energy_gain": 1.5},
        )
        assert response.status_code == 200
        audio.apply_profile.assert_called_once_with("pulse")
        assert audio.energy_gain == 1.5
    finally:
        dependencies.set_audio_mirror(orig_a)
        dependencies.set_screen_mirror(orig_s)
