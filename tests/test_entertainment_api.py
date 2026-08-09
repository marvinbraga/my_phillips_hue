"""API tests for entertainment status / areas (no real bridge)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from marvin_hue.entertainment.client import EntertainmentClient
from marvin_hue.entertainment.credentials import EntertainmentCredentials
from marvin_hue.entertainment.models import ChannelInfo, EntertainmentAreaInfo


def test_entertainment_status_disabled_default(fastapi_test_client: TestClient) -> None:
    response = fastapi_test_client.get("/mirror/entertainment/status")
    assert response.status_code == 200
    body = response.json()
    assert "enabled" in body
    assert "ready" in body
    assert "streaming" in body
    assert "areas" in body
    assert "transport" in body


def test_entertainment_areas_empty_when_not_ready(
    fastapi_test_client: TestClient,
) -> None:
    from marvin_hue.api import dependencies

    client = EntertainmentClient(host="10.0.0.1", credentials=None)
    orig = dependencies.get_entertainment_client()
    dependencies.set_entertainment_client(client)
    try:
        response = fastapi_test_client.get("/mirror/entertainment/areas")
        assert response.status_code == 200
        body = response.json()
        assert body["ready"] is False
        assert body["areas"] == []
    finally:
        dependencies.set_entertainment_client(orig)


def test_entertainment_areas_lists_when_ready(fastapi_test_client: TestClient) -> None:
    from marvin_hue.api import dependencies

    client = EntertainmentClient(
        host="10.0.0.1",
        credentials=EntertainmentCredentials("user", "key"),
    )
    client.list_areas = AsyncMock(
        return_value=[
            EntertainmentAreaInfo(
                id="area-1",
                name="Sala",
                channels=(ChannelInfo(0, name="Play 1"),),
            )
        ]
    )
    orig = dependencies.get_entertainment_client()
    dependencies.set_entertainment_client(client)
    try:
        response = fastapi_test_client.get("/mirror/entertainment/areas")
        assert response.status_code == 200
        body = response.json()
        assert body["ready"] is True
        assert body["areas"][0]["id"] == "area-1"
        assert body["areas"][0]["channel_count"] == 1
    finally:
        dependencies.set_entertainment_client(orig)


def test_mirror_status_includes_transport_fields(
    fastapi_test_client: TestClient,
) -> None:
    response = fastapi_test_client.get("/mirror/status")
    assert response.status_code == 200
    body = response.json()
    assert "transport" in body or body.get("running") is False
    assert "entertainment_ready" in body
    assert "entertainment_enabled" in body


def test_profiles_include_intensity(fastapi_test_client: TestClient) -> None:
    response = fastapi_test_client.get("/mirror/profiles")
    assert response.status_code == 200
    body = response.json()
    assert "audio_intensity_profiles" in body
    assert set(body["audio_intensity_profiles"].keys()) == {
        "subtle",
        "moderate",
        "high",
        "extreme",
    }


def test_start_audio_with_rest_preference(fastapi_test_client: TestClient) -> None:
    from marvin_hue.api import dependencies
    from marvin_hue.audio_mirror import AudioMirror
    from marvin_hue.screen_mirror import ScreenMirror

    audio = MagicMock(spec=AudioMirror)
    running = {"v": False}

    def _start(**_kwargs):
        running["v"] = True
        return True

    audio.is_running.side_effect = lambda: running["v"]
    audio.start.side_effect = _start
    audio.load_light_positions.return_value = []
    audio.transition_time = 0
    audio.output_port = MagicMock(transport="rest")
    audio.get_status.return_value = {
        "running": True,
        "mode": "audio",
        "fps": 30,
        "brightness": 200,
        "transport": "rest",
        "colors": {},
        "bass": 0.0,
        "mid": 0.0,
        "treble": 0.0,
        "entertainment_enabled": False,
        "entertainment_area_id": None,
    }
    screen = MagicMock(spec=ScreenMirror)
    screen.is_running.return_value = False
    screen.get_status.return_value = {"running": False, "colors": {}, "transport": "rest"}
    screen.output_port = MagicMock(transport="rest")

    orig_a = dependencies._audio_mirror
    orig_s = dependencies._screen_mirror
    dependencies.set_audio_mirror(audio)
    dependencies.set_screen_mirror(screen)
    try:
        response = fastapi_test_client.post(
            "/mirror/start",
            json={
                "mode": "audio",
                "profile": "party",
                "transport_preference": "rest",
            },
        )
        assert response.status_code == 200
        assert response.json()["status"]["transport"] == "rest"
        audio.set_output_port.assert_called()
        audio.start.assert_called()
    finally:
        dependencies.set_audio_mirror(orig_a)
        dependencies.set_screen_mirror(orig_s)
