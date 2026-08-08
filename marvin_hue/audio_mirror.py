"""
Espelhamento reativo a áudio/música para Philips Hue.

Captura o áudio do sistema (preferindo monitor/loopback PulseAudio/PipeWire),
calcula energia por bandas via FFT e aplica cores nas lâmpadas conforme a
posição configurada (mesmo mapeamento de light_positions.json do screen mirror).
"""

from __future__ import annotations

import json
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
        "fps": 30,
        "brightness": 220,
        "smoothing_factor": 0.55,
        "transition_time": 0,
        "energy_gain": 1.4,
    },
    "chill": {
        "fps": 20,
        "brightness": 140,
        "smoothing_factor": 0.2,
        "transition_time": 3,
        "energy_gain": 0.85,
    },
    "pulse": {
        "fps": 35,
        "brightness": 240,
        "smoothing_factor": 0.75,
        "transition_time": 0,
        "energy_gain": 1.6,
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


def compute_band_energies(
    samples: np.ndarray,
    sample_rate: int,
) -> dict[str, float]:
    """
    Calcula energia normalizada (0–1) para bass, mid e treble via FFT.

    Args:
        samples: array 1D float mono
        sample_rate: taxa de amostragem em Hz
    """
    if samples.size < 8:
        return {"bass": 0.0, "mid": 0.0, "treble": 0.0}

    # Janela Hann para reduzir leakage
    window = np.hanning(samples.size)
    spectrum = np.abs(np.fft.rfft(samples * window))
    freqs = np.fft.rfftfreq(samples.size, d=1.0 / sample_rate)

    def _band_power(f_lo: float, f_hi: float) -> float:
        mask = (freqs >= f_lo) & (freqs < f_hi)
        if not np.any(mask):
            return 0.0
        # RMS-ish da magnitude
        return float(np.sqrt(np.mean(spectrum[mask] ** 2)))

    bass_raw = _band_power(20.0, _BASS_MAX_HZ)
    mid_raw = _band_power(_BASS_MAX_HZ, _MID_MAX_HZ)
    treble_raw = _band_power(_MID_MAX_HZ, min(sample_rate / 2.0, 12_000.0))

    # Normalização log-ish: comprime picos sem zerar baixos
    def _norm(v: float) -> float:
        if v <= 0.0:
            return 0.0
        # escala empírica para magnitudes típicas de float32 [-1,1]
        return max(0.0, min(1.0, float(np.log1p(v * 8.0) / np.log1p(8.0))))

    return {
        "bass": _norm(bass_raw),
        "mid": _norm(mid_raw),
        "treble": _norm(treble_raw),
    }


def find_monitor_device(
    query_devices: Callable[[], Any] | None = None,
) -> int | None:
    """
    Escolhe device de captura: preferência por nome contendo 'monitor'
    (sink monitor PulseAudio/PipeWire); fallback para default input.

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

    # sd.query_devices() sem arg retorna lista de dicts (ou DeviceList)
    try:
        dev_list = list(devices)
    except TypeError:
        return None

    if not dev_list:
        return None

    for idx, dev in enumerate(dev_list):
        name = str(dev.get("name", "") if isinstance(dev, dict) else getattr(dev, "name", ""))
        max_in = int(
            dev.get("max_input_channels", 0)
            if isinstance(dev, dict)
            else getattr(dev, "max_input_channels", 0)
        )
        if max_in > 0 and "monitor" in name.lower():
            logger.info(f"Audio device (monitor): index={idx} name={name!r}")
            return idx

    # Fallback: default input
    try:
        default = sd.default.device
        if isinstance(default, (list, tuple)):
            default_in = default[0]
        else:
            default_in = default
        if default_in is not None and int(default_in) >= 0:
            logger.info(f"Audio device (default input): index={default_in}")
            return int(default_in)
    except Exception as exc:
        logger.debug(f"Could not resolve default input: {exc}")

    # Último recurso: primeiro device com input channels
    for idx, dev in enumerate(dev_list):
        max_in = int(
            dev.get("max_input_channels", 0)
            if isinstance(dev, dict)
            else getattr(dev, "max_input_channels", 0)
        )
        if max_in > 0:
            logger.info(f"Audio device (first input): index={idx}")
            return idx

    return None


class AudioMirror:
    """
    Controlador de espelhamento reativo a áudio/música.

    Mesmo lifecycle do ScreenMirror: start/stop/is_running/get_status/set_status_callback.
    Reutiliza light_positions.json e eye_safety / enabled_for_app.
    """

    SAMPLE_RATE = 22050
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

    def apply_profile(self, name: str) -> None:
        """Aplica perfil nomeado (party | chill | pulse)."""
        if name not in AUDIO_MIRROR_PROFILES:
            raise ValueError(f"Unknown audio profile: {name}")
        for key, value in AUDIO_MIRROR_PROFILES[name].items():
            setattr(self, key, value)
        self.active_profile = name
        logger.info(f"Applied audio mirror profile '{name}': {AUDIO_MIRROR_PROFILES[name]}")

    def load_light_positions(self) -> list[dict[str, Any]]:
        """Carrega lâmpadas ativas do JSON (enabled, position != none, enabled_for_app)."""
        try:
            with open(self.positions_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                lights = [
                    light
                    for light in data.get("lights", [])
                    if light.get("enabled")
                    and light.get("position") != "none"
                    and is_enabled_for_app(str(light.get("name", "")))
                ]
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
        self, light_name: str, new_color: tuple[int, int, int], threshold: int = 12
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
            color = Color(smoothed[0], smoothed[1], smoothed[2], self.brightness)
            light = self.hue.set_light_color(light_name, color)
            if light:
                light.transitiontime = int(round(self.transition_time))
        except ValueError as e:
            logger.debug(f"Light '{light_name}' unavailable for audio mirror: {e}")
        except Exception as e:
            logger.debug(f"Error applying audio color to '{light_name}': {e}")

    def _smooth_levels(self, raw: dict[str, float]) -> dict[str, float]:
        # smoothing_factor alto = reage mais; baixo = mais inércia
        alpha = max(0.05, min(1.0, float(self.smoothing_factor)))
        out: dict[str, float] = {}
        for key in ("bass", "mid", "treble"):
            prev = self._smoothed_levels.get(key, 0.0)
            val = prev + (raw[key] - prev) * alpha
            # energy_gain e clamp
            val = max(0.0, min(1.0, val * float(self.energy_gain)))
            out[key] = val
            self._smoothed_levels[key] = val
        return out

    def _process_frame(self, mono: np.ndarray, sample_rate: int) -> None:
        raw = compute_band_energies(mono, sample_rate)
        levels = self._smooth_levels(raw)
        self._levels = levels

        lights = self.load_light_positions()
        for light in lights:
            name = str(light.get("name", ""))
            position = str(light.get("position", "ambient"))
            band = position_to_band(position)
            # ambient / unknown: média full spectrum
            if position == "ambient" or position not in POSITION_TO_BAND:
                energy = (levels["bass"] + levels["mid"] + levels["treble"]) / 3.0
                # cor full-spectrum: mistura ponderada
                r = g = b = 0
                for bname, weight in (
                    ("bass", levels["bass"]),
                    ("mid", levels["mid"]),
                    ("treble", levels["treble"]),
                ):
                    cr, cg, cb = band_color(bname, weight)
                    r += cr
                    g += cg
                    b += cb
                total_w = max(
                    levels["bass"] + levels["mid"] + levels["treble"], 1e-6
                )
                # média simples se silêncio; senão média das bandas coloridas
                if total_w < 0.05:
                    rgb = band_color("mid", energy)
                else:
                    rgb = (
                        max(0, min(255, r // 3)),
                        max(0, min(255, g // 3)),
                        max(0, min(255, b // 3)),
                    )
            else:
                energy = levels[band]
                rgb = band_color(band, energy)

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
        sample_rate = self.SAMPLE_RATE
        block = self.BLOCK_SIZE
        frame_time = 1.0 / max(1, self.fps)

        try:
            with sd.InputStream(
                device=device,
                channels=1,
                samplerate=sample_rate,
                blocksize=block,
                dtype="float32",
            ) as stream:
                logger.info(
                    f"Audio stream open device={device} rate={sample_rate} block={block}"
                )
                while self.running:
                    start = time.time()
                    try:
                        data, overflowed = stream.read(block)
                        if overflowed:
                            logger.debug("Audio buffer overflow")
                        mono = np.asarray(data, dtype=np.float32).reshape(-1)
                        self._process_frame(mono, sample_rate)
                    except Exception as frame_exc:
                        logger.debug(f"Audio frame error: {frame_exc}")

                    # FPS pode mudar em runtime
                    frame_time = 1.0 / max(1, self.fps)
                    elapsed = time.time() - start
                    if elapsed < frame_time:
                        time.sleep(frame_time - elapsed)
        except Exception as exc:
            logger.exception(f"Audio mirror stream failed: {exc}")
            self.running = False

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
                "No Linux, use PulseAudio/PipeWire e garanta um sink monitor "
                "(o que você ouve). Verifique com: pactl list short sources"
            )
        self._device_index = device

        logger.info(
            f"Starting audio mirroring (FPS: {self.fps}, brightness: {self.brightness}"
            f", profile: {self.active_profile}, device: {device})"
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
            "bass": self._levels.get("bass", 0.0),
            "mid": self._levels.get("mid", 0.0),
            "treble": self._levels.get("treble", 0.0),
        }

    def set_status_callback(self, callback: Callable[[dict[str, Any]], None]) -> None:
        self._on_status_change = callback
