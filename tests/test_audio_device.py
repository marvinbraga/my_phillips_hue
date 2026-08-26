"""Pulse/PipeWire/PortAudio discovery — lives in audio_device, not AudioMirror."""

from __future__ import annotations

import subprocess
from typing import Any
from unittest.mock import patch

import pytest

from marvin_hue.audio_device import (
    find_monitor_device,
    find_pulse_monitor_source,
    resolve_input_stream_params,
)


class _CmdResult:
    def __init__(self, stdout: str, returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode


def test_find_pulse_monitor_source_prefers_default_sink_monitor() -> None:
    def fake_run(args: list[str], **_kwargs: object) -> _CmdResult:
        if args[:3] == ["pactl", "get-default-sink"]:
            return _CmdResult("alsa_output.pci-0000_09_00.4.analog-stereo\n")
        if args[:3] == ["pactl", "list", "short"]:
            return _CmdResult(
                "66\talsa_input.mic\tPipeWire\ts16le 1ch 48000Hz\tRUNNING\n"
                "67\talsa_output.pci-0000_09_00.4.analog-stereo.monitor\t"
                "PipeWire\ts32le 2ch 48000Hz\tRUNNING\n"
            )
        return _CmdResult("", 1)

    src = find_pulse_monitor_source(run_cmd=fake_run)
    assert src == "alsa_output.pci-0000_09_00.4.analog-stereo.monitor"


def test_find_pulse_monitor_source_uses_running_monitor_without_default_sink() -> None:
    def fake_run(args: list[str], **_kwargs: object) -> _CmdResult:
        if args[:3] == ["pactl", "get-default-sink"]:
            return _CmdResult("")
        if args[:3] == ["pactl", "list", "short"]:
            return _CmdResult(
                "1\talsa_input.mic\tPipeWire\ts16le 1ch 48000Hz\tRUNNING\n"
                "2\tsink_idle.monitor\tPipeWire\ts32le 2ch 48000Hz\tSUSPENDED\n"
                "3\tsink_active.monitor\tPipeWire\ts32le 2ch 48000Hz\tRUNNING\n"
            )
        return _CmdResult("", 1)

    src = find_pulse_monitor_source(run_cmd=fake_run)
    assert src == "sink_active.monitor"


def test_find_pulse_monitor_source_falls_back_to_first_monitor() -> None:
    def fake_run(args: list[str], **_kwargs: object) -> _CmdResult:
        if args[:3] == ["pactl", "get-default-sink"]:
            return _CmdResult("missing-sink")
        if args[:3] == ["pactl", "list", "short"]:
            return _CmdResult(
                "2\tfirst.monitor\tPipeWire\ts32le 2ch 48000Hz\tSUSPENDED\n"
                "3\tsecond.monitor\tPipeWire\ts32le 2ch 48000Hz\tSUSPENDED\n"
            )
        return _CmdResult("", 1)

    src = find_pulse_monitor_source(run_cmd=fake_run)
    assert src == "first.monitor"


def test_find_pulse_monitor_source_returns_none_when_pactl_missing() -> None:
    def fake_run(_args: list[str], **_kwargs: object) -> _CmdResult:
        raise FileNotFoundError("pactl")

    assert find_pulse_monitor_source(run_cmd=fake_run) is None


def test_find_pulse_monitor_source_returns_none_when_no_monitors() -> None:
    def fake_run(args: list[str], **_kwargs: object) -> _CmdResult:
        if args[:3] == ["pactl", "list", "short"]:
            return _CmdResult("1\talsa_input.mic\tPipeWire\ts16le 1ch 48000Hz\tRUNNING\n")
        return _CmdResult("", 1)

    assert find_pulse_monitor_source(run_cmd=fake_run) is None


def test_find_pulse_monitor_source_timeout_returns_none() -> None:
    def fake_run(_args: list[str], **_kwargs: object) -> _CmdResult:
        raise subprocess.TimeoutExpired(cmd="pactl", timeout=3)

    assert find_pulse_monitor_source(run_cmd=fake_run) is None


def test_find_monitor_device_prefers_monitor_name() -> None:
    devices = [
        {"name": "Built-in Mic", "max_input_channels": 2},
        {"name": "alsa_output.pci.analog-stereo.monitor", "max_input_channels": 2},
        {"name": "Webcam", "max_input_channels": 1},
    ]
    idx = find_monitor_device(query_devices=lambda: devices)
    assert idx == 1


def test_find_monitor_device_prefers_pulse_over_alsa_hw() -> None:
    devices = [
        {"name": "HD-Audio Generic: ALC1220 Analog (hw:1,0)", "max_input_channels": 2},
        {"name": "pulse", "max_input_channels": 32},
        {"name": "HD Pro Webcam C920: USB Audio (hw:3,0)", "max_input_channels": 2},
    ]
    idx = find_monitor_device(query_devices=lambda: devices)
    assert idx == 1


def test_find_monitor_device_prefers_pulse_over_pipewire() -> None:
    devices = [
        {"name": "Elgato Wave:3: USB Audio (hw:2,0)", "max_input_channels": 2},
        {"name": "pipewire", "max_input_channels": 128},
        {"name": "pulse", "max_input_channels": 32},
        {"name": "HD Pro Webcam C920: USB Audio (hw:3,0)", "max_input_channels": 2},
    ]
    idx = find_monitor_device(
        query_devices=lambda: devices,
        pulse_source="alsa_output.pci.analog-stereo.monitor",
    )
    assert idx == 2


def test_find_monitor_device_pulse_without_source_still_beats_hw() -> None:
    devices = [
        {"name": "pipewire", "max_input_channels": 128},
        {"name": "pulse", "max_input_channels": 32},
        {"name": "Built-in Mic", "max_input_channels": 2},
    ]
    idx = find_monitor_device(query_devices=lambda: devices)
    assert idx == 1


def test_find_monitor_device_empty_returns_none() -> None:
    with patch("sounddevice.default") as default:
        default.device = None
        idx = find_monitor_device(query_devices=list)
    assert idx is None


def test_find_monitor_device_none_query_returns_none() -> None:
    assert find_monitor_device(query_devices=lambda: None) is None


def test_find_monitor_device_skips_default_hardware_mic() -> None:
    devices = [
        {"name": "Elgato Wave Mic", "max_input_channels": 1},
        {"name": "Some Line In", "max_input_channels": 2},
    ]
    with patch("sounddevice.default") as default:
        default.device = (0, 1)
        idx = find_monitor_device(query_devices=lambda: devices)
    assert idx in {0, 1}


def test_find_monitor_device_accepts_object_devices() -> None:
    class Dev:
        def __init__(self, name: str, channels: int) -> None:
            self.name = name
            self.max_input_channels = channels

    devices = [Dev("hw:0,0 analog", 2), Dev("pulse", 32)]
    idx = find_monitor_device(query_devices=lambda: devices)
    assert idx == 1


def test_resolve_input_stream_params_uses_device_default_rate() -> None:
    def query(device: int | None = None) -> list[Any] | dict[str, Any]:
        if device is None:
            return []
        return {
            "name": "pulse",
            "max_input_channels": 2,
            "default_samplerate": 44100.0,
        }

    accepted: list[int] = []

    def check(**kwargs: object) -> None:
        rate = int(kwargs["samplerate"])  # type: ignore[arg-type,call-overload]
        if rate == 22050:
            raise ValueError("invalid sample rate")
        accepted.append(rate)

    rate, channels, block = resolve_input_stream_params(
        0,
        query_devices=query,
        check_input_settings=check,
    )
    assert rate == 44100
    assert channels == 2
    assert block >= 256
    assert 22050 not in accepted or accepted[0] == 44100


def test_resolve_input_stream_params_skips_invalid_rates() -> None:
    def query(_device: int | None = None) -> dict[str, Any]:
        return {
            "name": "ALC1220",
            "max_input_channels": 2,
            "default_samplerate": 22050.0,
        }

    def check(**kwargs: object) -> None:
        rate = int(kwargs["samplerate"])  # type: ignore[arg-type,call-overload]
        if rate not in (48000, 44100):
            raise ValueError(f"Invalid sample rate {rate}")

    rate, channels, _block = resolve_input_stream_params(
        4,
        query_devices=query,
        check_input_settings=check,
    )
    assert rate in (48000, 44100)
    assert channels == 2


def test_resolve_input_stream_params_mono_when_one_channel() -> None:
    def query(_device: int | None = None) -> dict[str, Any]:
        return {
            "name": "pulse",
            "max_input_channels": 1,
            "default_samplerate": 48000.0,
        }

    def check(**_kwargs: object) -> None:
        return None

    rate, channels, block = resolve_input_stream_params(
        0,
        query_devices=query,
        check_input_settings=check,
    )
    assert rate == 48000
    assert channels == 1
    assert 256 <= block <= 4096


def test_resolve_input_stream_params_raises_when_no_rate_works() -> None:
    def query(_device: int | None = None) -> dict[str, Any]:
        return {"name": "broken", "max_input_channels": 2, "default_samplerate": None}

    def check(**_kwargs: object) -> None:
        raise ValueError("nope")

    with pytest.raises(RuntimeError, match="Nenhuma taxa de amostragem"):
        resolve_input_stream_params(
            0,
            query_devices=query,
            check_input_settings=check,
        )
