"""Mirror profile resolution: cinema / fps / ambient defaults and API wiring."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from marvin_hue.screen_mirror import MIRROR_PROFILES, ScreenMirror


@pytest.fixture
def mirror() -> ScreenMirror:
    return ScreenMirror(MagicMock(), "unused.json")


@pytest.mark.parametrize("name", ["cinema", "fps", "ambient"])
def test_apply_profile_sets_all_defaults(mirror: ScreenMirror, name: str) -> None:
    expected = MIRROR_PROFILES[name]
    mirror.apply_profile(name)
    assert mirror.active_profile == name
    assert mirror.fps == expected["fps"]
    assert mirror.brightness == expected["brightness"]
    assert mirror.saturation_boost == expected["saturation_boost"]
    assert mirror.smoothing_factor == expected["smoothing_factor"]
    assert mirror.transition_time == expected["transition_time"]


def test_apply_profile_unknown_raises(mirror: ScreenMirror) -> None:
    with pytest.raises(ValueError, match="Unknown profile"):
        mirror.apply_profile("neon")


def test_get_status_includes_profile_fields(mirror: ScreenMirror) -> None:
    mirror.apply_profile("cinema")
    status = mirror.get_status()
    assert status["active_profile"] == "cinema"
    assert status["fps"] == MIRROR_PROFILES["cinema"]["fps"]
    assert status["brightness"] == MIRROR_PROFILES["cinema"]["brightness"]
    assert status["saturation_boost"] == MIRROR_PROFILES["cinema"]["saturation_boost"]
    assert status["smoothing_factor"] == MIRROR_PROFILES["cinema"]["smoothing_factor"]
    assert status["transition_time"] == MIRROR_PROFILES["cinema"]["transition_time"]
    assert status["running"] is False
    assert "colors" in status


def test_start_with_profile_applies_defaults(mirror: ScreenMirror) -> None:
    with patch.object(mirror, "_mirror_loop"):
        ok = mirror.start(profile="ambient")
    assert ok is True
    assert mirror.running is True
    assert mirror.active_profile == "ambient"
    assert mirror.fps == MIRROR_PROFILES["ambient"]["fps"]
    assert mirror.brightness == MIRROR_PROFILES["ambient"]["brightness"]
    mirror.running = False


def test_start_profile_then_explicit_fps_overrides(mirror: ScreenMirror) -> None:
    with patch.object(mirror, "_mirror_loop"):
        mirror.start(profile="cinema", fps=20, brightness=100)
    assert mirror.fps == 20
    assert mirror.brightness == 100
    # Profile still applied for the other knobs
    assert mirror.active_profile == "cinema"
    assert mirror.smoothing_factor == MIRROR_PROFILES["cinema"]["smoothing_factor"]
    mirror.running = False


def test_start_without_profile_keeps_legacy_defaults(mirror: ScreenMirror) -> None:
    with patch.object(mirror, "_mirror_loop"):
        mirror.start()
    assert mirror.fps == 25
    assert mirror.brightness == 200
    assert mirror.active_profile is None
    mirror.running = False


def test_profile_value_matrix() -> None:
    """Regression: exact mapping from Phase F plan."""
    assert MIRROR_PROFILES == {
        "cinema": {
            "fps": 12,
            "brightness": 160,
            "saturation_boost": 1.1,
            "smoothing_factor": 0.35,
            "transition_time": 2,
        },
        "fps": {
            "fps": 30,
            "brightness": 200,
            "saturation_boost": 1.4,
            "smoothing_factor": 0.7,
            "transition_time": 0,
        },
        "ambient": {
            "fps": 8,
            "brightness": 120,
            "saturation_boost": 1.0,
            "smoothing_factor": 0.25,
            "transition_time": 3,
        },
    }


def test_api_list_profiles(fastapi_test_client: TestClient) -> None:
    response = fastapi_test_client.get("/mirror/profiles")
    assert response.status_code == 200
    body = response.json()
    assert set(body["profiles"].keys()) == {"cinema", "fps", "ambient"}
    assert body["profiles"]["cinema"]["fps"] == 12


def test_api_start_with_profile(fastapi_test_client: TestClient) -> None:
    from marvin_hue.api import dependencies

    mock = MagicMock(spec=ScreenMirror)
    mock.is_running.return_value = False
    mock.get_status.return_value = {
        "running": True,
        "fps": 12,
        "brightness": 160,
        "active_profile": "cinema",
        "colors": {},
    }
    original = dependencies._screen_mirror
    dependencies.set_screen_mirror(mock)
    try:
        response = fastapi_test_client.post(
            "/mirror/start", json={"profile": "cinema"}
        )
        assert response.status_code == 200
        mock.start.assert_called_once_with(
            fps=None, brightness=None, profile="cinema"
        )
        assert response.json()["status"]["active_profile"] == "cinema"
    finally:
        dependencies.set_screen_mirror(original)


def test_api_settings_with_profile(fastapi_test_client: TestClient) -> None:
    from marvin_hue.api import dependencies

    mock = MagicMock(spec=ScreenMirror)
    mock.get_status.return_value = {
        "running": False,
        "fps": 30,
        "brightness": 200,
        "active_profile": "fps",
        "colors": {},
    }
    original = dependencies._screen_mirror
    dependencies.set_screen_mirror(mock)
    try:
        response = fastapi_test_client.post(
            "/mirror/settings", json={"profile": "fps"}
        )
        assert response.status_code == 200
        mock.apply_profile.assert_called_once_with("fps")
    finally:
        dependencies.set_screen_mirror(original)


def test_api_post_mirror_profile(fastapi_test_client: TestClient) -> None:
    from marvin_hue.api import dependencies

    mock = MagicMock(spec=ScreenMirror)
    mock.get_status.return_value = {
        "running": False,
        "fps": 8,
        "brightness": 120,
        "active_profile": "ambient",
        "colors": {},
    }
    original = dependencies._screen_mirror
    dependencies.set_screen_mirror(mock)
    try:
        response = fastapi_test_client.post(
            "/mirror/profile", json={"profile": "ambient"}
        )
        assert response.status_code == 200
        mock.apply_profile.assert_called_once_with("ambient")
        assert "ambient" in response.json()["message"]
    finally:
        dependencies.set_screen_mirror(original)


def test_api_invalid_profile_rejected(fastapi_test_client: TestClient) -> None:
    response = fastapi_test_client.post(
        "/mirror/start", json={"profile": "neon"}
    )
    assert response.status_code == 422
