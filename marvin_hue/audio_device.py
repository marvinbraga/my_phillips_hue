"""Pulse/PipeWire/PortAudio discovery for system-output (monitor) capture.

Not a facade: these are focused helpers. AudioMirror owns start/stop lifecycle
and calls into this module for device selection only.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from typing import Any

from marvin_hue.logging_config import get_logger

logger = get_logger("audio_device")

_PREFERRED_RATES: tuple[int, ...] = (48000, 44100, 32000, 16000, 22050, 8000)
_MIN_BLOCK: int = 256
_MAX_BLOCK: int = 4096
_BLOCK_SECONDS: float = 0.023
_PACTL_TIMEOUT_SECS: int = 3


def _device_field(dev: Any, key: str, default: Any = None) -> Any:
    if isinstance(dev, dict):
        return dev.get(key, default)
    return getattr(dev, key, default)


def _device_name(dev: Any) -> str:
    return str(_device_field(dev, "name", "") or "")


def _device_max_in(dev: Any) -> int:
    try:
        return int(_device_field(dev, "max_input_channels", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _device_default_rate(dev: Any) -> float | None:
    try:
        rate = _device_field(dev, "default_samplerate", None)
        if rate is None:
            return None
        return float(rate)
    except (TypeError, ValueError):
        return None


def _run_pactl(runner: Callable[..., Any], args: list[str]) -> str:
    try:
        proc = runner(
            args,
            capture_output=True,
            text=True,
            check=False,
            timeout=_PACTL_TIMEOUT_SECS,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        logger.debug(f"pactl unavailable: {exc}")
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def _parse_pactl_sources(
    sources_txt: str,
) -> tuple[list[str], list[str], list[str]]:
    source_names: list[str] = []
    running_monitors: list[str] = []
    all_monitors: list[str] = []
    for line in sources_txt.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        name = parts[1]
        source_names.append(name)
        if ".monitor" not in name:
            continue
        all_monitors.append(name)
        if "RUNNING" in line:
            running_monitors.append(name)
    return source_names, running_monitors, all_monitors


def _choose_pulse_monitor(
    source_names: list[str],
    running_monitors: list[str],
    all_monitors: list[str],
    sink: str,
) -> str | None:
    if sink:
        candidate = f"{sink}.monitor"
        if candidate in source_names:
            logger.info(f"Pulse monitor (default sink): {candidate}")
            return candidate
    if running_monitors:
        logger.info(f"Pulse monitor (RUNNING): {running_monitors[0]}")
        return running_monitors[0]
    if all_monitors:
        logger.info(f"Pulse monitor (first): {all_monitors[0]}")
        return all_monitors[0]
    return None


def find_pulse_monitor_source(
    *,
    run_cmd: Callable[..., Any] | None = None,
) -> str | None:
    """
    Resolve o source monitor do sink padrão (o que você OUVE), via pactl.

    O default source do Pulse costuma ser o microfone — inútil para música.
    """
    runner = run_cmd or subprocess.run
    sources_txt = _run_pactl(runner, ["pactl", "list", "short", "sources"])
    if not sources_txt:
        return None
    names, running, monitors = _parse_pactl_sources(sources_txt)
    sink = _run_pactl(runner, ["pactl", "get-default-sink"])
    return _choose_pulse_monitor(names, running, monitors, sink)


def _is_pulse_bridge_name(name: str) -> bool:
    """True for PortAudio/Pulse bridge device names (not hardware ALSA)."""
    low = name.lower().strip()
    return low == "pulse" or low.startswith("pulse:")


def _is_pipewire_bridge_name(name: str) -> bool:
    """True for ALSA 'pipewire' bridge — does NOT honor PULSE_SOURCE."""
    low = name.lower().strip()
    return low == "pipewire" or low.startswith("pipewire:")


def _is_hardware_capture_name(name: str) -> bool:
    """Heuristic: hardware mics/webcams that are not system-output monitors."""
    low = name.lower()
    if "monitor" in low:
        return False
    if _is_pulse_bridge_name(name) or _is_pipewire_bridge_name(name):
        return False
    markers = (
        "mic",
        "microphone",
        "webcam",
        "camera",
        "c920",
        "wave",
        "headset",
        "input",
        "analog",
        "usb audio",
        "hw:",
    )
    return any(m in low for m in markers)


def _import_sounddevice() -> Any:
    try:
        import sounddevice as sd
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Biblioteca sounddevice não instalada. Execute: uv add sounddevice"
        ) from exc
    return sd


def _input_devices(dev_list: list[Any]) -> list[tuple[int, Any, str]]:
    inputs: list[tuple[int, Any, str]] = []
    for idx, dev in enumerate(dev_list):
        max_in = _device_max_in(dev)
        if max_in <= 0:
            continue
        name = _device_name(dev)
        inputs.append((idx, dev, name))
    return inputs


def _pulse_and_pipewire_indices(
    inputs: list[tuple[int, Any, str]],
) -> tuple[int | None, int | None]:
    pulse_idx: int | None = None
    pipewire_idx: int | None = None
    for idx, _dev, name in inputs:
        if pulse_idx is None and _is_pulse_bridge_name(name):
            pulse_idx = idx
        if pipewire_idx is None and _is_pipewire_bridge_name(name):
            pipewire_idx = idx
    return pulse_idx, pipewire_idx


def _default_input_index(sd: Any) -> int | None:
    try:
        default = sd.default.device
        if isinstance(default, (list, tuple)):
            return int(default[0]) if default[0] is not None else None
        if default is not None:
            return int(default)
    except (TypeError, ValueError, AttributeError, OSError) as exc:
        logger.debug(f"Could not resolve default input: {exc}")
    return None


def _select_default_or_fallback(
    inputs: list[tuple[int, Any, str]],
    default_in: int | None,
) -> int:
    if default_in is not None and default_in >= 0:
        for idx, _dev, name in inputs:
            if idx != default_in:
                continue
            low = name.lower()
            if "monitor" in low or _is_pulse_bridge_name(name) or _is_pipewire_bridge_name(name):
                logger.info(f"Audio device (default PA/PW): index={idx} name={name!r}")
                return idx
            if _is_hardware_capture_name(name):
                logger.warning(
                    f"Skipping default input (looks like mic/hw): index={idx} name={name!r}"
                )
                break
            logger.info(f"Audio device (default input): index={default_in}")
            return default_in

    for idx, _dev, name in inputs:
        if _is_hardware_capture_name(name):
            continue
        logger.info(f"Audio device (non-hw input): index={idx} name={name!r}")
        return idx

    idx, _dev, name = inputs[0]
    logger.warning(f"Audio device (last resort, may be microphone): index={idx} name={name!r}")
    return idx


def _devices_as_list(devices: Any) -> list[Any] | None:
    if devices is None:
        return None
    try:
        dev_list = list(devices)
    except TypeError:
        return None
    return dev_list or None


def _first_named_monitor(inputs: list[tuple[int, Any, str]]) -> int | None:
    for idx, _dev, name in inputs:
        if "monitor" in name.lower():
            logger.info(f"Audio device (monitor): index={idx} name={name!r}")
            return idx
    return None


def _select_pulse_or_pipewire(
    pulse_idx: int | None,
    pipewire_idx: int | None,
    pulse_source: str | None,
) -> int | None:
    if pulse_idx is not None:
        logger.info(
            f"Audio device (pulse bridge for system monitor): "
            f"index={pulse_idx} pulse_source={pulse_source!r}"
        )
        return pulse_idx
    if pulse_source and pipewire_idx is not None:
        logger.warning(
            "PULSE_SOURCE monitor is set but no 'pulse' device found; "
            "using 'pipewire' may capture the microphone instead of "
            f"system audio (pulse_source={pulse_source!r})"
        )
    if pipewire_idx is None:
        return None
    if pulse_source:
        logger.warning(
            f"Audio device (pipewire fallback): index={pipewire_idx} "
            f"pulse_source={pulse_source!r} — system audio routing may fail"
        )
        return pipewire_idx
    logger.info(
        f"Audio device (pipewire): index={pipewire_idx} "
        "(no monitor source; may follow default capture)"
    )
    return pipewire_idx


def find_monitor_device(
    query_devices: Callable[[], Any] | None = None,
    *,
    pulse_source: str | None = None,
) -> int | None:
    """
    Escolhe device de captura para o *áudio do sistema* (não microfone).

    Ordem:
    1. Nome contendo 'monitor' (sink monitor exposto no PortAudio)
    2. Device ``pulse`` — obrigatório quando há ``PULSE_SOURCE=*.monitor``;
       o bridge ALSA ``pipewire`` **ignora** PULSE_SOURCE e usa o default
       source do Pulse (quase sempre o microfone)
    3. ``pipewire`` só se não houver ``pulse`` e não houver monitor source
    4. Default input se for monitor/pulse
    5. Fallback: primeiro input que não pareça microfone/webcam
    """
    sd = _import_sounddevice()
    raw = query_devices() if query_devices is not None else sd.query_devices()
    dev_list = _devices_as_list(raw)
    if not dev_list:
        return None
    inputs = _input_devices(dev_list)
    if not inputs:
        return None
    named = _first_named_monitor(inputs)
    if named is not None:
        return named
    pulse_idx, pipewire_idx = _pulse_and_pipewire_indices(inputs)
    virtual = _select_pulse_or_pipewire(pulse_idx, pipewire_idx, pulse_source)
    if virtual is not None:
        return virtual
    return _select_default_or_fallback(inputs, _default_input_index(sd))


def _fft_hop_block(rate: int) -> int:
    block = max(_MIN_BLOCK, min(_MAX_BLOCK, int(rate * _BLOCK_SECONDS)))
    block = 1 << (block - 1).bit_length()
    return max(_MIN_BLOCK, min(_MAX_BLOCK, block))


def resolve_input_stream_params(
    device: int,
    *,
    query_devices: Callable[..., Any] | None = None,
    check_input_settings: Callable[..., Any] | None = None,
) -> tuple[int, int, int]:
    """
    Resolve (sample_rate, channels, blocksize) aceitos pelo device.

    Prefere stereo quando disponível (análise L/R). Block ~ hop 1024.
    """
    sd = _import_sounddevice()

    q = query_devices or sd.query_devices
    checker = check_input_settings or sd.check_input_settings

    try:
        info = q(device)
    except (TypeError, ValueError, KeyError, OSError):
        info = None

    max_in = _device_max_in(info) if info is not None else 1
    channels = 1 if max_in <= 0 else min(2, max_in)

    preferred: list[int] = []
    native = _device_default_rate(info) if info is not None else None
    if native and native > 0:
        preferred.append(round(native))
    for candidate in _PREFERRED_RATES:
        if candidate not in preferred:
            preferred.append(candidate)

    last_err: Exception | None = None
    for rate in preferred:
        try:
            checker(device=device, channels=channels, samplerate=rate, dtype="float32")
            logger.info(f"Audio stream params: device={device} rate={rate} channels={channels}")
            return rate, channels, _fft_hop_block(rate)
        except Exception as exc:
            last_err = exc
            logger.debug(f"Sample rate {rate} rejected for device {device}: {exc}")

    if native and native > 0:
        rate = round(native)
        logger.warning(
            f"Using device default rate {rate} without check_input_settings "
            f"(last error: {last_err})"
        )
        return rate, channels, _fft_hop_block(rate)

    raise RuntimeError(
        f"Nenhuma taxa de amostragem compatível com o dispositivo de áudio. Último erro: {last_err}"
    ) from last_err
