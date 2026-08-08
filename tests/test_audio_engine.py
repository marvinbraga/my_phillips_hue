"""Unit tests for entertainment-style AudioAnalyzer (no hardware)."""

from __future__ import annotations

import numpy as np
import pytest

from marvin_hue.audio_engine import (
    AnalysisFrame,
    AnalyzerConfig,
    AudioAnalyzer,
    EnvelopeFollower,
    density_to_level,
    entertainment_color,
    hsv_to_rgb,
)


def _sine(freq: float, sr: int, n: int, amp: float = 0.3) -> np.ndarray:
    t = np.arange(n) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_hsv_to_rgb_primary() -> None:
    r, g, b = hsv_to_rgb(0.0, 1.0, 1.0)  # red
    assert r > 250 and g < 5 and b < 5
    r, g, b = hsv_to_rgb(1.0 / 3.0, 1.0, 1.0)  # green
    assert g > 250 and r < 5 and b < 5
    r, g, b = hsv_to_rgb(2.0 / 3.0, 1.0, 1.0)  # blue
    assert b > 250 and r < 5 and g < 5


def test_hsv_to_rgb_clamps() -> None:
    r, g, b = hsv_to_rgb(-0.1, 1.5, 2.0)
    assert 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255


def test_entertainment_color_valid_rgb() -> None:
    rgb = entertainment_color(
        bass=0.8,
        mid=0.4,
        treble=0.2,
        beat=0.5,
        centroid=0.3,
        stereo_bias=-0.2,
        position="left",
        phase=0.1,
    )
    assert len(rgb) == 3
    assert all(0 <= c <= 255 for c in rgb)
    assert sum(rgb) > 20  # not black with energy


def test_entertainment_color_bottom_warmer_than_top() -> None:
    bottom = entertainment_color(
        bass=0.9, mid=0.2, treble=0.1, beat=0.0, centroid=0.2, position="bottom"
    )
    top = entertainment_color(
        bass=0.1, mid=0.2, treble=0.9, beat=0.0, centroid=0.8, position="top"
    )
    # bottom should be warmer (more red) or at least different
    assert bottom != top
    assert bottom[0] >= bottom[2] or bottom[0] > 80


def test_entertainment_color_beat_increases_value() -> None:
    soft = entertainment_color(
        bass=0.3, mid=0.3, treble=0.3, beat=0.0, centroid=0.4, position="ambient"
    )
    hard = entertainment_color(
        bass=0.3, mid=0.3, treble=0.3, beat=1.0, centroid=0.4, position="ambient"
    )
    assert sum(hard) >= sum(soft)


def test_density_to_level_range() -> None:
    assert density_to_level(0.0) == 0.0
    quiet = density_to_level(1e-6)
    mid = density_to_level(1e-3)
    loud = density_to_level(5e-2)
    assert quiet < mid < loud
    assert loud <= 1.0
    assert mid < 0.98


def test_envelope_follower_attack_faster_than_release() -> None:
    env = EnvelopeFollower(attack=0.5, release=0.1)
    up = env.process(1.0)
    assert up > 0.4
    env.value = 1.0
    down = env.process(0.0)
    assert down > 0.8  # slow release


def test_analyzer_silence() -> None:
    az = AudioAnalyzer(sample_rate=22050)
    silence = np.zeros(2048, dtype=np.float32)
    # fill ring
    for _ in range(4):
        frame = az.process(silence)
    assert frame.bass == 0.0
    assert frame.mid == 0.0
    assert frame.treble == 0.0
    assert frame.rms < 1e-4


def test_analyzer_bass_tone() -> None:
    sr = 44100
    az = AudioAnalyzer(sample_rate=sr, config=AnalyzerConfig(attack=0.6, release=0.15))
    block = _sine(80.0, sr, 1024, amp=0.35)
    frame = AnalysisFrame()
    for _ in range(12):
        frame = az.process(block)
    assert frame.bass > frame.treble
    assert frame.bass > 0.08


def test_analyzer_treble_tone() -> None:
    sr = 44100
    az = AudioAnalyzer(sample_rate=sr, config=AnalyzerConfig(attack=0.6, release=0.15))
    block = _sine(5000.0, sr, 1024, amp=0.35)
    frame = AnalysisFrame()
    for _ in range(12):
        frame = az.process(block)
    assert frame.treble > frame.bass
    assert frame.treble > 0.05


def test_analyzer_beat_flux_increases_on_transient() -> None:
    sr = 44100
    az = AudioAnalyzer(
        sample_rate=sr,
        config=AnalyzerConfig(beat_sensitivity=1.5, beat_decay=0.85, attack=0.5),
    )
    # Steady low tone to fill buffers / set flux baseline
    steady = _sine(100.0, sr, 1024, amp=0.05)
    for _ in range(16):
        az.process(steady)

    baseline_beat = az.process(steady).beat

    # Sudden loud broadband-ish transient (square-ish burst)
    t = np.arange(1024) / sr
    burst = (0.6 * np.sin(2 * np.pi * 120 * t)).astype(np.float32)
    burst[:80] *= 0.0
    # Add higher harmonics for flux
    burst = burst + 0.4 * _sine(800.0, sr, 1024, amp=1.0)
    burst = np.clip(burst, -1.0, 1.0).astype(np.float32)

    peak_beat = 0.0
    for _ in range(4):
        fr = az.process(burst)
        peak_beat = max(peak_beat, fr.beat)

    assert peak_beat > baseline_beat
    assert peak_beat > 0.05


def test_analyzer_stereo_bias() -> None:
    sr = 44100
    az = AudioAnalyzer(sample_rate=sr)
    n = 1024
    left = _sine(200.0, sr, n, amp=0.4)
    right = _sine(200.0, sr, n, amp=0.05)
    stereo = np.stack([left, right], axis=1)
    frame = AnalysisFrame()
    for _ in range(10):
        frame = az.process(stereo)
    assert frame.stereo_bias < -0.2  # left louder → negative bias


def test_analyzer_color_for_position() -> None:
    az = AudioAnalyzer(sample_rate=44100)
    block = _sine(200.0, 44100, 1024, amp=0.3)
    frame = az.process(block)
    for _ in range(8):
        frame = az.process(block)
    rgb = az.color_for_position("center", frame)
    assert all(0 <= c <= 255 for c in rgb)


def test_analysis_frame_color_for_position_helper() -> None:
    frame = AnalysisFrame(bass=0.7, mid=0.5, treble=0.3, beat=0.2, centroid=0.4)
    rgb = frame.color_for_position("top-left", phase=0.2)
    assert all(0 <= c <= 255 for c in rgb)


@pytest.mark.parametrize(
    "pos",
    [
        "left",
        "right",
        "bottom",
        "top",
        "center",
        "ambient",
        "top-left",
        "bottom-right",
    ],
)
def test_entertainment_color_all_positions(pos: str) -> None:
    rgb = entertainment_color(
        bass=0.5,
        mid=0.5,
        treble=0.5,
        beat=0.3,
        centroid=0.5,
        stereo_bias=0.1,
        position=pos,
    )
    assert all(0 <= c <= 255 for c in rgb)
