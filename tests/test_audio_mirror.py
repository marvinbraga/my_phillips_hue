"""Unit tests for audio/music reactive lighting (no real audio hardware)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from marvin_hue.audio_mirror import (
    AUDIO_MIRROR_PROFILES,
    AudioMirror,
    band_color,
    compute_band_energies,
    find_monitor_device,
    position_to_band,
)


# ---------------------------------------------------------------------------
# Pure mapping helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "position,expected",
    [
        ("bottom", "bass"),
        ("bottom-left", "bass"),
        ("bottom-right", "bass"),
        ("left", "mid"),
        ("right", "mid"),
        ("center", "mid"),
        ("ambient", "mid"),
        ("top", "treble"),
        ("top-left", "treble"),
        ("top-right", "treble"),
        ("unknown-slot", "mid"),
        ("none", "mid"),
    ],
)
def test_position_to_band(position: str, expected: str) -> None:
    assert position_to_band(position) == expected


def test_band_color_bass_is_warm() -> None:
    r, g, b = band_color("bass", 1.0)
    assert r > g and r > b  # red/orange dominant


def test_band_color_treble_is_cool() -> None:
    r, g, b = band_color("treble", 1.0)
    assert b > r  # blue/cyan dominant


def test_band_color_energy_scales_brightness() -> None:
    low = band_color("bass", 0.1)
    high = band_color("bass", 1.0)
    assert sum(high) > sum(low)


def test_band_color_clamps_energy() -> None:
    r, g, b = band_color("mid", 2.5)
    assert 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255
    r0, g0, b0 = band_color("mid", -1.0)
    assert sum((r0, g0, b0)) < sum((r, g, b))


def test_compute_band_energies_silence() -> None:
    samples = np.zeros(1024, dtype=np.float32)
    levels = compute_band_energies(samples, 22050)
    assert levels["bass"] == 0.0
    assert levels["mid"] == 0.0
    assert levels["treble"] == 0.0


def test_compute_band_energies_bass_tone() -> None:
    sr = 22050
    t = np.arange(2048) / sr
    # 80 Hz sine — pure bass
    samples = (0.8 * np.sin(2 * np.pi * 80 * t)).astype(np.float32)
    levels = compute_band_energies(samples, sr)
    assert levels["bass"] > levels["treble"]
    assert levels["bass"] > 0.1


def test_compute_band_energies_treble_tone() -> None:
    sr = 22050
    t = np.arange(2048) / sr
    samples = (0.8 * np.sin(2 * np.pi * 5000 * t)).astype(np.float32)
    levels = compute_band_energies(samples, sr)
    assert levels["treble"] > levels["bass"]


# ---------------------------------------------------------------------------
# Device selection
# ---------------------------------------------------------------------------


def test_find_monitor_device_prefers_monitor_name() -> None:
    devices = [
        {"name": "Built-in Mic", "max_input_channels": 2},
        {"name": "alsa_output.pci.analog-stereo.monitor", "max_input_channels": 2},
        {"name": "Webcam", "max_input_channels": 1},
    ]
    idx = find_monitor_device(query_devices=lambda: devices)
    assert idx == 1


def test_find_monitor_device_empty_returns_none() -> None:
    with patch("sounddevice.default") as default:
        default.device = None
        idx = find_monitor_device(query_devices=lambda: [])
    assert idx is None


def test_find_monitor_device_fallback_default_input() -> None:
    devices = [
        {"name": "Mic", "max_input_channels": 1},
        {"name": "Line", "max_input_channels": 2},
    ]
    with patch("sounddevice.default") as default:
        default.device = (0, 1)
        idx = find_monitor_device(query_devices=lambda: devices)
    assert idx == 0


# ---------------------------------------------------------------------------
# AudioMirror lifecycle
# ---------------------------------------------------------------------------


@pytest.fixture
def positions_file(tmp_path: Path) -> str:
    path = tmp_path / "positions.json"
    path.write_text(
        """
        {
          "lights": [
            {"name": "Hue Play 1", "position": "left", "enabled": true},
            {"name": "Hue Play 2", "position": "bottom", "enabled": true},
            {"name": "Led cima", "position": "top", "enabled": true},
            {"name": "Off light", "position": "center", "enabled": false}
          ]
        }
        """,
        encoding="utf-8",
    )
    return str(path)


@pytest.fixture
def mirror(positions_file: str) -> AudioMirror:
    hue = MagicMock()
    return AudioMirror(hue, positions_file)


def test_apply_profile_party(mirror: AudioMirror) -> None:
    mirror.apply_profile("party")
    expected = AUDIO_MIRROR_PROFILES["party"]
    assert mirror.active_profile == "party"
    assert mirror.fps == expected["fps"]
    assert mirror.brightness == expected["brightness"]
    assert mirror.energy_gain == expected["energy_gain"]


def test_apply_profile_unknown_raises(mirror: AudioMirror) -> None:
    with pytest.raises(ValueError, match="Unknown audio profile"):
        mirror.apply_profile("cinema")


def test_load_light_positions_filters(mirror: AudioMirror) -> None:
    with patch("marvin_hue.audio_mirror.is_enabled_for_app", return_value=True):
        lights = mirror.load_light_positions()
    names = {light["name"] for light in lights}
    assert "Off light" not in names
    assert "Hue Play 1" in names
    assert len(lights) == 3


def test_start_fails_without_device(mirror: AudioMirror) -> None:
    with pytest.raises(RuntimeError, match="Nenhum dispositivo de áudio"):
        mirror.start(device_resolver=lambda: None)
    assert mirror.is_running() is False


def test_start_with_mock_device_and_stop(mirror: AudioMirror) -> None:
    """Start without opening real stream: stub _mirror_loop."""
    with patch.object(mirror, "_mirror_loop"):
        ok = mirror.start(profile="chill", device_resolver=lambda: 0)
    assert ok is True
    assert mirror.is_running() is True
    assert mirror.active_profile == "chill"
    assert mirror.fps == AUDIO_MIRROR_PROFILES["chill"]["fps"]

    mirror.stop()
    assert mirror.is_running() is False
    status = mirror.get_status()
    assert status["running"] is False
    assert status["mode"] == "audio"
    assert status["bass"] == 0.0


def test_start_already_running_returns_false(mirror: AudioMirror) -> None:
    with patch.object(mirror, "_mirror_loop"):
        mirror.start(device_resolver=lambda: 0)
        second = mirror.start(device_resolver=lambda: 0)
    assert second is False
    mirror.running = False


def test_get_status_includes_spectrum(mirror: AudioMirror) -> None:
    mirror._levels = {"bass": 0.5, "mid": 0.3, "treble": 0.1}
    status = mirror.get_status()
    assert status["bass"] == 0.5
    assert status["mid"] == 0.3
    assert status["treble"] == 0.1
    assert "colors" in status


def test_process_frame_applies_colors(mirror: AudioMirror) -> None:
    with patch("marvin_hue.audio_mirror.is_enabled_for_app", return_value=True):
        sr = 22050
        t = np.arange(1024) / sr
        samples = (0.9 * np.sin(2 * np.pi * 100 * t)).astype(np.float32)
        mirror._process_frame(samples, sr)
    # Hue controller should have been called for enabled lights
    assert mirror.hue.set_light_color.called
    assert mirror._levels["bass"] >= 0.0
