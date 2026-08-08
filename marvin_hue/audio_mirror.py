"""
Espelhamento reativo a áudio/música para Philips Hue.

Captura o áudio do sistema (preferindo monitor/loopback PulseAudio/PipeWire),
calcula energia por bandas via FFT e aplica cores nas lâmpadas conforme a
posição configurada (mesmo mapeamento de light_positions.json do screen mirror).
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from typing import Any, Callable

import numpy as np

from marvin_hue.colors import Color
from marvin_hue.controllers import HueController
from marvin_hue.eye_safety import is_enabled_for_app
from marvin_hue.logging_config import get_logger

logger = get_logger("audio_mirror")

# party: reativo, alto contraste
# chill: suave, energia baixa
# pulse: beat-ish, alto contraste / resposta rápida
AUDIO_MIRROR_PROFILES: dict[str, dict[str, float | int]] = {
    "party": {
        "fps": 28,
        "brightness": 230,
        "smoothing_factor": 0.55,
        "transition_time": 0,
        # sensitivity na escala dB (1.0 = neutro; >1 empurra um pouco para cima)
        "energy_gain": 1.0,
    },
    "chill": {
        "fps": 18,
        "brightness": 150,
        "smoothing_factor": 0.25,
        "transition_time": 2,
        "energy_gain": 0.85,
    },
    "pulse": {
        "fps": 32,
        "brightness": 250,
        "smoothing_factor": 0.75,
        "transition_time": 0,
        "energy_gain": 1.1,
    },
}

# Frequências de corte aproximadas (Hz) para bandas
_BASS_MAX_HZ = 250.0
_MID_MAX_HZ = 2000.0

# Mapeamento posição → banda espectral
POSITION_TO_BAND: dict[str, str] = {
    "bottom": "bass",
    "bottom-left": "bass",
    "bottom-right": "bass",
    "left": "mid",
    "right": "mid",
    "center": "mid",
    "ambient": "mid",
    "top": "treble",
    "top-left": "treble",
    "top-right": "treble",
}

# Cores base por banda (RGB 0-255) — energia escala o brilho efetivo
BAND_BASE_COLORS: dict[str, tuple[int, int, int]] = {
    "bass": (255, 60, 20),  # vermelho/laranja quente
    "mid": (120, 40, 200),  # roxo/verde-púrpura
    "treble": (40, 180, 255),  # azul/ciano
}

# Mid usa blend verde/roxo conforme energia
_MID_GREEN = (40, 200, 80)
_MID_PURPLE = (140, 40, 220)


def position_to_band(position: str) -> str:
    """Mapeia posição da lâmpada para banda (bass|mid|treble). Desconhecido → ambient/mid full."""
    return POSITION_TO_BAND.get(position, "mid")


def band_color(band: str, energy: float) -> tuple[int, int, int]:
    """
    Converte banda + energia (0–1) em RGB.

    Bass → vermelhos/laranjas; mid → verdes/roxos; treble → azuis/cianos.
    Energia baixa escurece a cor (multiplica canais).
    """
    e = max(0.0, min(1.0, float(energy)))
    if band == "bass":
        base = BAND_BASE_COLORS["bass"]
    elif band == "treble":
        base = BAND_BASE_COLORS["treble"]
    else:
        # mid: interpola verde → roxo com a energia
        g0, g1 = _MID_GREEN, _MID_PURPLE
        base = (
            int(g0[0] + (g1[0] - g0[0]) * e),
            int(g0[1] + (g1[1] - g0[1]) * e),
            int(g0[2] + (g1[2] - g0[2]) * e),
        )
    # Escala mínima 0.12 para não apagar totalmente em silêncio quase total
    scale = 0.12 + 0.88 * e
    return (
        max(0, min(255, int(base[0] * scale))),
        max(0, min(255, int(base[1] * scale))),
        max(0, min(255, int(base[2] * scale))),
    )


def compute_band_powers(
    samples: np.ndarray,
    sample_rate: int,
) -> dict[str, float]:
    """Energia bruta (não normalizada) por banda — para AGC/escala dB."""
    if samples.size < 8:
        return {"bass": 0.0, "mid": 0.0, "treble": 0.0, "rms": 0.0}

    mono = np.asarray(samples, dtype=np.float64).reshape(-1)
    rms = float(np.sqrt(np.mean(mono * mono)))

    # Energia espectral real (soma de potências), não magnitude média —
    # a média achatava as bandas e empurrava tudo para o teto no AGC.
    window = np.hanning(mono.size)
    spectrum = np.fft.rfft(mono * window)
    power_spec = (np.abs(spectrum) ** 2) / max(mono.size, 1)
    freqs = np.fft.rfftfreq(mono.size, d=1.0 / sample_rate)

    def _band_power(f_lo: float, f_hi: float) -> float:
        mask = (freqs >= f_lo) & (freqs < f_hi)
        n = int(np.count_nonzero(mask))
        if n <= 0:
            return 0.0
        # Densidade média por bin — bandas largas (mid) não “ganham” só por largura
        return float(np.sum(power_spec[mask]) / n)

    return {
        "bass": _band_power(20.0, _BASS_MAX_HZ),
        "mid": _band_power(_BASS_MAX_HZ, _MID_MAX_HZ),
        "treble": _band_power(_MID_MAX_HZ, min(sample_rate / 2.0, 12_000.0)),
        "rms": rms,
    }


def power_to_level(
    power: float,
    *,
    ref: float = 1e-2,
    floor_db: float = -45.0,
    ceiling_db: float = 6.0,
    sensitivity: float = 1.0,
) -> float:
    """
    Mapeia potência linear (densidade |FFT|²) → 0..1 em escala dB.

    Calibrado para densidade média por bin ~1e-5 (silêncio) … ~1e-1 (forte).
    sensitivity > 1 sobe o mapeamento; < 1 exige mais volume.
    """
    p = max(float(power), 0.0)
    if p <= 0.0:
        return 0.0
    sens = max(0.25, min(3.0, float(sensitivity)))
    db = 10.0 * float(np.log10(p / ref + 1e-15))
    db += 6.0 * float(np.log2(sens))
    if db <= floor_db:
        return 0.0
    if db >= ceiling_db:
        return 1.0
    return (db - floor_db) / (ceiling_db - floor_db)


def compute_band_energies(
    samples: np.ndarray,
    sample_rate: int,
    *,
    peak_tracker: "PeakTracker | None" = None,
    sensitivity: float = 1.0,
) -> dict[str, float]:
    """
    Energia 0–1 por banda em escala **absoluta dB**.

    Não usa AGC v/peak (isso colava o espectro no máximo). O PeakTracker
    opcional só aplica um noise-gate suave e clamp final.
    """
    powers = compute_band_powers(samples, sample_rate)
    if powers["rms"] < 1e-5:
        return {"bass": 0.0, "mid": 0.0, "treble": 0.0}

    absolute = {
        "bass": power_to_level(powers["bass"], sensitivity=sensitivity),
        "mid": power_to_level(powers["mid"], sensitivity=sensitivity),
        "treble": power_to_level(powers["treble"], sensitivity=sensitivity),
    }

    if peak_tracker is not None:
        return peak_tracker.normalize(absolute, powers)

    return absolute


class PeakTracker:
    """
    Pós-processamento leve: noise gate + histórico de pico só para UI/stats.

    NÃO renormaliza para encher a escala (isso causava barras sempre no topo).
    """

    def __init__(
        self,
        gate: float = 0.04,
        release: float = 0.995,
    ) -> None:
        self.gate = gate
        self.release = release
        self.ceilings: dict[str, float] = {
            "bass": gate,
            "mid": gate,
            "treble": gate,
        }
        self.peaks = self.ceilings

    def normalize(
        self,
        absolute_levels: dict[str, float],
        _raw_powers: dict[str, float] | None = None,
    ) -> dict[str, float]:
        out: dict[str, float] = {}
        for key in ("bass", "mid", "treble"):
            v = max(0.0, min(1.0, float(absolute_levels.get(key, 0.0))))
            # atualiza pico só para status/debug
            if v > self.ceilings[key]:
                self.ceilings[key] = v
            else:
                self.ceilings[key] = max(self.gate, self.ceilings[key] * self.release)
            # noise gate suave
            if v < self.gate:
                v = 0.0
            else:
                v = (v - self.gate) / (1.0 - self.gate)
            out[key] = max(0.0, min(1.0, v))
        return out


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


def find_pulse_monitor_source(
    *,
    run_cmd: Callable[..., Any] | None = None,
) -> str | None:
    """
    Resolve o source monitor do sink padrão (o que você OUVE), via pactl.

    O default source do Pulse costuma ser o microfone — inútil para música.
    """
    runner = run_cmd or subprocess.run

    def _run(args: list[str]) -> str:
        try:
            proc = runner(args, capture_output=True, text=True, check=False, timeout=3)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            logger.debug(f"pactl unavailable: {exc}")
            return ""
        if proc.returncode != 0:
            return ""
        return (proc.stdout or "").strip()

    sources_txt = _run(["pactl", "list", "short", "sources"])
    if not sources_txt:
        return None

    source_names: list[str] = []
    running_monitors: list[str] = []
    all_monitors: list[str] = []
    for line in sources_txt.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        name = parts[1]
        source_names.append(name)
        if ".monitor" in name:
            all_monitors.append(name)
            if "RUNNING" in line:
                running_monitors.append(name)

    sink = _run(["pactl", "get-default-sink"])
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


def find_monitor_device(
    query_devices: Callable[[], Any] | None = None,
) -> int | None:
    """
    Escolhe device de captura, nesta ordem:
    1. Nome contendo 'monitor' (sink monitor PA/PW)
    2. 'pulse' ou 'pipewire' (com PULSE_SOURCE=monitor no open)
    3. Default input (se for pulse/pipewire/monitor)
    4. Default input qualquer
    5. Primeiro device com canais de entrada (evita webcams se possível)

    Returns:
        Device index ou None se não houver dispositivos.
    """
    try:
        import sounddevice as sd
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Biblioteca sounddevice não instalada. Execute: uv add sounddevice"
        ) from exc

    devices = query_devices() if query_devices is not None else sd.query_devices()
    if devices is None:
        return None

    try:
        dev_list = list(devices)
    except TypeError:
        return None

    if not dev_list:
        return None

    inputs: list[tuple[int, Any, str]] = []
    for idx, dev in enumerate(dev_list):
        max_in = _device_max_in(dev)
        if max_in <= 0:
            continue
        name = _device_name(dev)
        inputs.append((idx, dev, name))

    if not inputs:
        return None

    for idx, _dev, name in inputs:
        if "monitor" in name.lower():
            logger.info(f"Audio device (monitor): index={idx} name={name!r}")
            return idx

    for idx, _dev, name in inputs:
        low = name.lower().strip()
        if low in {"pulse", "pipewire"} or low.startswith("pulse") or low.startswith("pipewire"):
            logger.info(f"Audio device (pulse/pipewire): index={idx} name={name!r}")
            return idx

    default_in: int | None = None
    try:
        default = sd.default.device
        if isinstance(default, (list, tuple)):
            default_in = int(default[0]) if default[0] is not None else None
        elif default is not None:
            default_in = int(default)
    except Exception as exc:
        logger.debug(f"Could not resolve default input: {exc}")

    if default_in is not None and default_in >= 0:
        for idx, _dev, name in inputs:
            if idx != default_in:
                continue
            low = name.lower()
            if "monitor" in low or "pulse" in low or "pipewire" in low:
                logger.info(f"Audio device (default PA/PW): index={idx} name={name!r}")
                return idx
        logger.info(f"Audio device (default input): index={default_in}")
        return default_in

    for idx, _dev, name in inputs:
        low = name.lower()
        if "webcam" in low or "camera" in low or "c920" in low:
            continue
        logger.info(f"Audio device (first non-webcam input): index={idx} name={name!r}")
        return idx

    idx, _dev, name = inputs[0]
    logger.info(f"Audio device (first input): index={idx} name={name!r}")
    return idx


def resolve_input_stream_params(
    device: int,
    *,
    query_devices: Callable[..., Any] | None = None,
    check_input_settings: Callable[..., Any] | None = None,
) -> tuple[int, int, int]:
    """
    Resolve (sample_rate, channels, blocksize) aceitos pelo device.

    PortAudio/ALSA rejeita taxas arbitrárias (ex.: 22050 em device 44100-only).
    Usa default_samplerate do device e tenta fallbacks comuns.
    """
    try:
        import sounddevice as sd
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Biblioteca sounddevice não instalada. Execute: uv add sounddevice"
        ) from exc

    q = query_devices or sd.query_devices
    checker = check_input_settings or sd.check_input_settings

    try:
        info = q(device)
    except Exception:
        info = None

    max_in = _device_max_in(info) if info is not None else 1
    channels = 1 if max_in <= 0 else min(2, max_in)

    preferred: list[int] = []
    native = _device_default_rate(info) if info is not None else None
    if native and native > 0:
        preferred.append(int(round(native)))
    for candidate in (48000, 44100, 32000, 16000, 22050, 8000):
        if candidate not in preferred:
            preferred.append(candidate)

    last_err: Exception | None = None
    for rate in preferred:
        try:
            checker(device=device, channels=channels, samplerate=rate, dtype="float32")
            logger.info(
                f"Audio stream params: device={device} rate={rate} channels={channels}"
            )
            # block ~23ms at 44.1k → ~1024; scale with rate
            block = max(256, min(4096, int(rate * 0.023)))
            # keep power-of-two-ish for FFT friendliness
            block = 1 << (block - 1).bit_length()
            block = max(256, min(4096, block))
            return rate, channels, block
        except Exception as exc:
            last_err = exc
            logger.debug(f"Sample rate {rate} rejected for device {device}: {exc}")

    # Último recurso: confiar no default do device sem check
    if native and native > 0:
        rate = int(round(native))
        block = max(256, min(4096, 1 << (int(rate * 0.023) - 1).bit_length()))
        logger.warning(
            f"Using device default rate {rate} without check_input_settings "
            f"(last error: {last_err})"
        )
        return rate, channels, block

    raise RuntimeError(
        "Nenhuma taxa de amostragem compatível com o dispositivo de áudio. "
        f"Último erro: {last_err}"
    ) from last_err


class AudioMirror:
    """
    Controlador de espelhamento reativo a áudio/música.

    Mesmo lifecycle do ScreenMirror: start/stop/is_running/get_status/set_status_callback.
    Reutiliza light_positions.json e eye_safety / enabled_for_app.
    """

    # Preferências legadas (taxa real é resolvida por device em start/loop)
    SAMPLE_RATE = 44100
    BLOCK_SIZE = 1024

    def __init__(
        self,
        hue_controller: HueController,
        positions_file: str = ".res/light_positions.json",
    ) -> None:
        self.hue = hue_controller
        self.positions_file = positions_file
        self.running = False
        self.thread: threading.Thread | None = None
        self.fps = 30
        self.brightness = 200
        self.smoothing_factor = 0.45
        self.transition_time = 1
        self.energy_gain = 1.2
        self.active_profile: str | None = None
        self._on_status_change: Callable[[dict[str, Any]], None] | None = None
        self._current_colors: dict[str, tuple[int, int, int]] = {}
        self._smoothed_colors: dict[str, tuple[int, int, int]] = {}
        self._levels: dict[str, float] = {"bass": 0.0, "mid": 0.0, "treble": 0.0}
        self._smoothed_levels: dict[str, float] = {
            "bass": 0.0,
            "mid": 0.0,
            "treble": 0.0,
        }
        self._device_index: int | None = None
        self._sample_rate: int = self.SAMPLE_RATE
        self._channels: int = 1
        self._block_size: int = self.BLOCK_SIZE
        self._pulse_source: str | None = None
        self._peak_tracker = PeakTracker()

    def apply_profile(self, name: str) -> None:
        """Aplica perfil nomeado (party | chill | pulse)."""
        if name not in AUDIO_MIRROR_PROFILES:
            raise ValueError(f"Unknown audio profile: {name}")
        for key, value in AUDIO_MIRROR_PROFILES[name].items():
            setattr(self, key, value)
        self.active_profile = name
        logger.info(f"Applied audio mirror profile '{name}': {AUDIO_MIRROR_PROFILES[name]}")

    def load_light_positions(self) -> list[dict[str, Any]]:
        """
        Carrega lâmpadas ativas para o espelhamento de áudio.

        Diferente da tela: position ``none`` ainda participa como ``ambient``
        (full spectrum), senão só 2–3 lâmpadas reagem e o resto fica morto.
        """
        try:
            with open(self.positions_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                lights: list[dict[str, Any]] = []
                for light in data.get("lights", []):
                    if not light.get("enabled", True):
                        continue
                    name = str(light.get("name", ""))
                    if not is_enabled_for_app(name):
                        continue
                    entry = dict(light)
                    pos = str(entry.get("position") or "none")
                    if pos == "none":
                        entry["position"] = "ambient"
                    lights.append(entry)
                logger.debug(f"Audio mirror: {len(lights)} active lights")
                return lights
        except FileNotFoundError:
            logger.warning(f"Positions file not found: {self.positions_file}")
            return []
        except json.JSONDecodeError as e:
            logger.exception(f"Error parsing positions file: {e}")
            return []

    def _interpolate_color(
        self, current: tuple[int, int, int], target: tuple[int, int, int]
    ) -> tuple[int, int, int]:
        factor = self.smoothing_factor
        return (
            int(current[0] + (target[0] - current[0]) * factor),
            int(current[1] + (target[1] - current[1]) * factor),
            int(current[2] + (target[2] - current[2]) * factor),
        )

    def _color_changed_significantly(
        self, light_name: str, new_color: tuple[int, int, int], threshold: int = 6
    ) -> bool:
        if light_name not in self._smoothed_colors:
            return True
        old = self._smoothed_colors[light_name]
        diff = (
            abs(new_color[0] - old[0])
            + abs(new_color[1] - old[1])
            + abs(new_color[2] - old[2])
        )
        return diff > threshold

    def _apply_color_to_light(self, light_name: str, r: int, g: int, b: int) -> None:
        if not is_enabled_for_app(light_name):
            return
        target = (r, g, b)
        if light_name in self._smoothed_colors:
            smoothed = self._interpolate_color(self._smoothed_colors[light_name], target)
        else:
            smoothed = target

        if not self._color_changed_significantly(light_name, smoothed):
            return

        self._smoothed_colors[light_name] = smoothed
        try:
            # Brilho da lâmpada escala com a luminância do RGB alvo (mais batida = mais claro)
            lum = (smoothed[0] + smoothed[1] + smoothed[2]) / (3.0 * 255.0)
            bri = max(8, min(254, int(self.brightness * (0.25 + 0.75 * lum))))
            color = Color(smoothed[0], smoothed[1], smoothed[2], bri)
            light = self.hue.set_light_color(light_name, color)
            if light:
                light.transitiontime = int(round(self.transition_time))
        except ValueError as e:
            logger.debug(f"Light '{light_name}' unavailable for audio mirror: {e}")
        except Exception as e:
            logger.debug(f"Error applying audio color to '{light_name}': {e}")

    def _smooth_levels(self, raw: dict[str, float]) -> dict[str, float]:
        # smoothing_factor alto = reage mais; baixo = mais inércia
        # energy_gain já entrou como sensitivity na escala dB — NÃO multiplica de novo.
        alpha = max(0.05, min(1.0, float(self.smoothing_factor)))
        out: dict[str, float] = {}
        for key in ("bass", "mid", "treble"):
            prev = self._smoothed_levels.get(key, 0.0)
            val = prev + (raw[key] - prev) * alpha
            out[key] = max(0.0, min(1.0, val))
            self._smoothed_levels[key] = out[key]
        return out

    def _mix_full_spectrum(self, levels: dict[str, float]) -> tuple[int, int, int]:
        total = levels["bass"] + levels["mid"] + levels["treble"]
        if total < 0.04:
            return band_color("mid", total)
        r = g = b = 0.0
        for bname in ("bass", "mid", "treble"):
            w = levels[bname]
            cr, cg, cb = band_color(bname, w)
            r += cr * w
            g += cg * w
            b += cb * w
        inv = 1.0 / max(total, 1e-6)
        return (
            max(0, min(255, int(r * inv))),
            max(0, min(255, int(g * inv))),
            max(0, min(255, int(b * inv))),
        )

    def _process_frame(self, mono: np.ndarray, sample_rate: int) -> None:
        raw = compute_band_energies(
            mono,
            sample_rate,
            peak_tracker=self._peak_tracker,
            sensitivity=float(self.energy_gain),
        )
        levels = self._smooth_levels(raw)
        self._levels = levels

        lights = self.load_light_positions()
        for light in lights:
            name = str(light.get("name", ""))
            if not name:
                continue
            position = str(light.get("position", "ambient"))
            if position == "ambient" or position not in POSITION_TO_BAND:
                rgb = self._mix_full_spectrum(levels)
            else:
                band = position_to_band(position)
                rgb = band_color(band, levels[band])

            self._apply_color_to_light(name, rgb[0], rgb[1], rgb[2])
            if name in self._smoothed_colors:
                self._current_colors[name] = self._smoothed_colors[name]
            else:
                self._current_colors[name] = rgb

        if self._on_status_change:
            self._on_status_change(self.get_status())

    def _mirror_loop(self) -> None:
        """Loop de captura de áudio + FFT + aplicação nas lâmpadas."""
        try:
            import sounddevice as sd
        except ImportError as exc:  # pragma: no cover
            logger.error(f"sounddevice missing in loop: {exc}")
            self.running = False
            return

        device = self._device_index
        if device is None:
            logger.error("Audio mirror loop started without device index")
            self.running = False
            return

        try:
            sample_rate, channels, block = resolve_input_stream_params(device)
        except Exception as exc:
            logger.exception(f"Could not resolve audio stream params: {exc}")
            self.running = False
            return

        self._sample_rate = sample_rate
        self._channels = channels
        self._block_size = block

        # Força Pulse/PipeWire a capturar o MONITOR do sink (música), não o mic.
        prev_pulse_source = os.environ.get("PULSE_SOURCE")
        pulse_source = self._pulse_source
        if pulse_source:
            os.environ["PULSE_SOURCE"] = pulse_source
            logger.info(f"PULSE_SOURCE={pulse_source}")

        try:
            with sd.InputStream(
                device=device,
                channels=channels,
                samplerate=sample_rate,
                blocksize=block,
                dtype="float32",
            ) as stream:
                logger.info(
                    f"Audio stream open device={device} rate={sample_rate} "
                    f"channels={channels} block={block} pulse_source={pulse_source!r}"
                )
                while self.running:
                    start = time.time()
                    try:
                        data, overflowed = stream.read(block)
                        if overflowed:
                            logger.debug("Audio buffer overflow")
                        arr = np.asarray(data, dtype=np.float32)
                        if arr.ndim == 2 and arr.shape[1] > 1:
                            mono = arr.mean(axis=1)
                        else:
                            mono = arr.reshape(-1)
                        self._process_frame(mono, sample_rate)
                    except Exception as frame_exc:
                        logger.debug(f"Audio frame error: {frame_exc}")

                    frame_time = 1.0 / max(1, self.fps)
                    elapsed = time.time() - start
                    if elapsed < frame_time:
                        time.sleep(frame_time - elapsed)
        except Exception as exc:
            logger.exception(f"Audio mirror stream failed: {exc}")
            self.running = False
        finally:
            if pulse_source is not None:
                if prev_pulse_source is None:
                    os.environ.pop("PULSE_SOURCE", None)
                else:
                    os.environ["PULSE_SOURCE"] = prev_pulse_source

    def start(
        self,
        fps: int | None = None,
        brightness: int | None = None,
        profile: str | None = None,
        *,
        device_resolver: Callable[[], int | None] | None = None,
    ) -> bool:
        """
        Inicia captura de áudio em thread daemon.

        Raises:
            RuntimeError: se nenhum dispositivo de áudio estiver disponível
                (mensagem em português).
        """
        if self.running:
            logger.warning("Audio mirroring already running")
            return False

        if profile is not None:
            self.apply_profile(profile)

        if fps is not None:
            self.fps = fps
        elif profile is None:
            self.fps = 30

        if brightness is not None:
            self.brightness = brightness
        elif profile is None:
            self.brightness = 200

        resolver = device_resolver or find_monitor_device
        device = resolver()
        if device is None:
            raise RuntimeError(
                "Nenhum dispositivo de áudio encontrado. "
                "No Linux, use PulseAudio/PipeWire (device 'pulse' ou 'pipewire') "
                "e garanta um sink monitor (o que você ouve). "
                "Verifique com: pactl list short sources"
            )
        self._device_index = device
        self._pulse_source = find_pulse_monitor_source()
        self._peak_tracker = PeakTracker()

        # Resolve taxa antes da thread para falhar cedo com mensagem clara
        try:
            sample_rate, channels, block = resolve_input_stream_params(device)
            self._sample_rate = sample_rate
            self._channels = channels
            self._block_size = block
        except Exception as exc:
            self._device_index = None
            self._pulse_source = None
            raise RuntimeError(
                "Não foi possível abrir o dispositivo de áudio com uma taxa "
                f"de amostragem válida (device={device}). "
                "Tente o device pulse/pipewire. Detalhe: "
                f"{exc}"
            ) from exc

        logger.info(
            f"Starting audio mirroring (FPS: {self.fps}, brightness: {self.brightness}"
            f", profile: {self.active_profile}, device: {device}, "
            f"rate={sample_rate}, ch={channels}, pulse_source={self._pulse_source!r})"
        )
        self.running = True
        self.thread = threading.Thread(target=self._mirror_loop, daemon=True)
        self.thread.start()
        return True

    def stop(self) -> bool:
        """Para o loop e limpa caches."""
        logger.info("Stopping audio mirroring")
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
            self.thread = None
        self._current_colors.clear()
        self._smoothed_colors.clear()
        self._levels = {"bass": 0.0, "mid": 0.0, "treble": 0.0}
        self._smoothed_levels = {"bass": 0.0, "mid": 0.0, "treble": 0.0}
        self._device_index = None
        self._pulse_source = None
        logger.info("Audio mirroring stopped successfully")
        return True

    def is_running(self) -> bool:
        return self.running

    def get_status(self) -> dict[str, Any]:
        """Status com levels de espectro (bass/mid/treble 0–1) e cores."""
        return {
            "running": self.running,
            "mode": "audio",
            "fps": self.fps,
            "brightness": self.brightness,
            "smoothing_factor": self.smoothing_factor,
            "transition_time": self.transition_time,
            "energy_gain": self.energy_gain,
            "active_profile": self.active_profile,
            "colors": self._current_colors.copy(),
            "sample_rate": self._sample_rate,
            "channels": self._channels,
            "device_index": self._device_index,
            "pulse_source": self._pulse_source,
            "bass": self._levels.get("bass", 0.0),
            "mid": self._levels.get("mid", 0.0),
            "treble": self._levels.get("treble", 0.0),
        }

    def set_status_callback(self, callback: Callable[[dict[str, Any]], None]) -> None:
        self._on_status_change = callback
