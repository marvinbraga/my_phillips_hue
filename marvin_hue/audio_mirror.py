"""
Espelhamento reativo a áudio/música para Philips Hue.

Captura o áudio do sistema (preferindo monitor/loopback PulseAudio/PipeWire),
analisa com multi-band + beat (estilo Entertainment) e aplica cores nas
lâmpadas conforme a posição configurada (light_positions.json).
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from typing import Any

import numpy as np

from marvin_hue.audio_color import (
    PeakTracker,
    band_color,
    compute_band_energies,
    compute_band_powers,
    modulate_base_color,
    position_to_band,
    power_to_level,
)
from marvin_hue.audio_device import (
    find_monitor_device,
    find_pulse_monitor_source,
    resolve_input_stream_params,
)
from marvin_hue.audio_engine import (
    DEFAULT_SPECTRUM_BINS,
    AnalysisFrame,
    AnalyzerConfig,
    AudioAnalyzer,
    entertainment_color,
)
from marvin_hue.basics import LightConfig
from marvin_hue.controllers import HueController
from marvin_hue.eye_safety import is_enabled_for_app
from marvin_hue.logging_config import get_logger
from marvin_hue.output.port import LightFrameColor, LightOutputPort
from marvin_hue.output.rest_adapter import RestPhueAdapter

# Public re-exports: device/color helpers used to live here; keep import path stable.
__all__ = (
    "ALL_AUDIO_PROFILES",
    "AUDIO_INTENSITY_PROFILES",
    "AUDIO_MIRROR_PROFILES",
    "AudioMirror",
    "PeakTracker",
    "band_color",
    "compute_band_energies",
    "compute_band_powers",
    "find_monitor_device",
    "find_pulse_monitor_source",
    "modulate_base_color",
    "position_to_band",
    "power_to_level",
    "resolve_input_stream_params",
)

logger = get_logger("audio_mirror")

# party: reativo, alto contraste, fps alto, transition 0
# chill: suave, beat baixo, hue lento
# pulse: beat-ish, ataque rápido, transition 0
AUDIO_MIRROR_PROFILES: dict[str, dict[str, float | int]] = {
    "party": {
        "fps": 36,
        "brightness": 235,
        "smoothing_factor": 0.70,
        "transition_time": 0,
        "energy_gain": 1.05,
        "beat_sensitivity": 1.25,
        "hue_speed": 1.1,
        "attack": 0.55,
        "release": 0.12,
    },
    "chill": {
        "fps": 18,
        "brightness": 150,
        "smoothing_factor": 0.28,
        "transition_time": 2,
        "energy_gain": 0.85,
        "beat_sensitivity": 0.55,
        "hue_speed": 0.35,
        "attack": 0.32,
        "release": 0.06,
    },
    "pulse": {
        "fps": 38,
        "brightness": 250,
        "smoothing_factor": 0.80,
        "transition_time": 0,
        "energy_gain": 1.15,
        "beat_sensitivity": 1.55,
        "hue_speed": 0.85,
        "attack": 0.60,
        "release": 0.14,
    },
}

# Hue Sync-like intensity aliases (map onto energy_gain / beat knobs)
AUDIO_INTENSITY_PROFILES: dict[str, dict[str, float | int]] = {
    "subtle": {**AUDIO_MIRROR_PROFILES["chill"], "fps": 24},
    "moderate": {
        "fps": 30,
        "brightness": 200,
        "smoothing_factor": 0.50,
        "transition_time": 0,
        "energy_gain": 1.0,
        "beat_sensitivity": 1.0,
        "hue_speed": 0.8,
        "attack": 0.45,
        "release": 0.10,
    },
    "high": {**AUDIO_MIRROR_PROFILES["party"]},
    "extreme": {**AUDIO_MIRROR_PROFILES["pulse"]},
}

# Combined profile lookup for apply_profile / API
ALL_AUDIO_PROFILES: dict[str, dict[str, float | int]] = {
    **AUDIO_MIRROR_PROFILES,
    **AUDIO_INTENSITY_PROFILES,
}


class AudioMirror:
    """
    Controlador de espelhamento reativo a áudio/música.

    Mesmo lifecycle do ScreenMirror: start/stop/is_running/get_status/set_status_callback.
    Reutiliza light_positions.json e eye_safety / enabled_for_app.
    """

    SAMPLE_RATE = 44100
    BLOCK_SIZE = 1024

    def __init__(
        self,
        hue_controller: HueController,
        positions_file: str = ".res/light_positions.json",
        output_port: LightOutputPort | None = None,
    ) -> None:
        self.hue = hue_controller
        self.positions_file = positions_file
        self._output: LightOutputPort = output_port or RestPhueAdapter(hue_controller)
        self.running = False
        self.thread: threading.Thread | None = None
        self.fps = 30
        self.brightness = 200
        self.smoothing_factor = 0.45
        self.transition_time = 1
        self.energy_gain = 1.05
        self.beat_sensitivity = 1.0
        self.hue_speed = 1.0
        self.attack = 0.45
        self.release = 0.10
        self.active_profile: str | None = None
        self.entertainment_area_id: str | None = None
        self.entertainment_enabled: bool = False
        self._on_status_change: Callable[[dict[str, Any]], None] | None = None
        self._current_colors: dict[str, tuple[int, int, int]] = {}
        self._smoothed_colors: dict[str, tuple[int, int, int]] = {}
        self._levels: dict[str, float | list[float]] = {
            "bass": 0.0,
            "mid": 0.0,
            "treble": 0.0,
            "beat": 0.0,
            "spectrum": [0.0] * DEFAULT_SPECTRUM_BINS,
        }
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
        self._analyzer = AudioAnalyzer(
            sample_rate=self.SAMPLE_RATE,
            config=AnalyzerConfig(
                attack=self.attack,
                release=self.release,
                beat_sensitivity=self.beat_sensitivity,
                hue_speed=self.hue_speed,
                energy_gain=self.energy_gain,
            ),
        )
        self._last_beat: float = 0.0
        self._session_started = False
        # Cached light positions — loaded on start / explicit reload; not every frame
        self._cached_positions: list[dict[str, Any]] | None = None
        # LightConfig base colors: audio modulates intensity, not invents hue
        self.config_name: str | None = None
        self._base_colors: dict[str, tuple[int, int, int]] = {}
        self._base_brightness: dict[str, int] = {}

    def set_light_config(self, config: LightConfig | None) -> None:
        """
        Define cores base a partir de um LightConfig (setup).

        Com config ativo, o áudio só modula intensidade/brilho das cores do
        setup (preserva R:G:B). ``None`` limpa e volta ao path free-HSV.
        """
        if config is None:
            self.config_name = None
            self._base_colors.clear()
            self._base_brightness.clear()
            # Drop smooth history so the next frame is not stuck on the old palette
            self._smoothed_colors.clear()
            logger.info("Audio mirror base colors cleared (free entertainment path)")
            return

        colors: dict[str, tuple[int, int, int]] = {}
        brightness: dict[str, int] = {}
        for setting in config.settings:
            name = str(setting.light_name)
            color = setting.color
            colors[name] = (int(color.red), int(color.green), int(color.blue))
            brightness[name] = int(color.brightness)
        self._base_colors = colors
        self._base_brightness = brightness
        self.config_name = str(config.name)
        # Immediate palette switch (no long blend from previous setup hues)
        self._smoothed_colors.clear()
        logger.info(
            f"Audio mirror base colors from config {self.config_name!r}: {len(colors)} lights"
        )

    def set_output_port(self, port: LightOutputPort) -> None:
        """Replace output transport (call before start, or when idle)."""
        if self.running:
            raise RuntimeError("Cannot change output port while mirror is running")
        self._output = port

    @property
    def output_port(self) -> LightOutputPort:
        return self._output

    def _sync_analyzer_config(self) -> None:
        self._analyzer.configure(
            attack=float(self.attack),
            release=float(self.release),
            beat_sensitivity=float(self.beat_sensitivity),
            hue_speed=float(self.hue_speed),
            energy_gain=float(self.energy_gain),
        )

    def apply_profile(self, name: str) -> None:
        """Aplica perfil nomeado (party|chill|pulse|subtle|moderate|high|extreme)."""
        if name not in ALL_AUDIO_PROFILES:
            raise ValueError(f"Unknown audio profile: {name}")
        profile = ALL_AUDIO_PROFILES[name]
        for key, value in profile.items():
            setattr(self, key, value)
        self.active_profile = name
        self._sync_analyzer_config()
        logger.info(f"Applied audio mirror profile '{name}': {profile}")

    def load_light_positions(self, *, force_reload: bool = False) -> list[dict[str, Any]]:
        """
        Carrega lâmpadas ativas para o espelhamento de áudio.

        position ``none`` participa como ``ambient`` (full entertainment mix).
        Result is cached after the first successful load; pass ``force_reload=True``
        (or call :meth:`reload_light_positions`) to re-read the JSON file.
        """
        if self._cached_positions is not None and not force_reload:
            return self._cached_positions
        try:
            with open(self.positions_file, encoding="utf-8") as f:
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
                self._cached_positions = lights
                return lights
        except FileNotFoundError:
            logger.warning(f"Positions file not found: {self.positions_file}")
            self._cached_positions = []
            return []
        except json.JSONDecodeError as e:
            logger.exception(f"Error parsing positions file: {e}")
            self._cached_positions = []
            return []

    def reload_light_positions(self) -> list[dict[str, Any]]:
        """Invalidate cache and reload positions from disk."""
        self._cached_positions = None
        return self.load_light_positions(force_reload=True)

    def _interpolate_color(
        self, current: tuple[int, int, int], target: tuple[int, int, int]
    ) -> tuple[int, int, int]:
        factor = self.smoothing_factor
        # On beat, temporarily reduce RGB smoothing so onsets punch through
        if self._last_beat > 0.30:
            # higher factor → closer to target (less lag)
            boost = 0.22 + 0.45 * self._last_beat
            factor = min(1.0, factor + boost)
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
        # Beat → lower threshold so flashes reach the bridge
        thr = threshold
        if self._last_beat > 0.35:
            thr = max(2, int(threshold * (1.0 - 0.7 * self._last_beat)))
        old = self._smoothed_colors[light_name]
        diff = abs(new_color[0] - old[0]) + abs(new_color[1] - old[1]) + abs(new_color[2] - old[2])
        return diff > thr

    def _smooth_color_for_light(
        self, light_name: str, r: int, g: int, b: int
    ) -> tuple[int, int, int] | None:
        """Return smoothed RGB if changed enough; update caches. None = skip."""
        if not is_enabled_for_app(light_name):
            return None
        target = (r, g, b)
        if light_name in self._smoothed_colors:
            smoothed = self._interpolate_color(self._smoothed_colors[light_name], target)
        else:
            smoothed = target

        if not self._color_changed_significantly(light_name, smoothed):
            # Keep last smoothed for UI but do not re-send
            if light_name in self._smoothed_colors:
                return None
            return None

        self._smoothed_colors[light_name] = smoothed
        return smoothed

    def _brightness_for_rgb(self, smoothed: tuple[int, int, int]) -> int:
        lum = (smoothed[0] + smoothed[1] + smoothed[2]) / (3.0 * 255.0)
        beat_boost = 1.0 + 0.35 * self._last_beat
        return max(
            8,
            min(254, int(self.brightness * (0.22 + 0.78 * lum) * beat_boost)),
        )

    def _apply_color_to_light(self, light_name: str, r: int, g: int, b: int) -> None:
        """Legacy single-light path (Rest via output port)."""
        smoothed = self._smooth_color_for_light(light_name, r, g, b)
        if smoothed is None:
            return
        bri = self._brightness_for_rgb(smoothed)
        try:
            # Keep RestPhueAdapter.transition_time in sync
            if isinstance(self._output, RestPhueAdapter):
                self._output.transition_time = int(round(self.transition_time))
            self._output.apply_frame(
                [
                    LightFrameColor(
                        light_name=light_name,
                        r=smoothed[0],
                        g=smoothed[1],
                        b=smoothed[2],
                        brightness=bri,
                    )
                ]
            )
        except Exception as e:
            logger.debug(f"Error applying audio color to '{light_name}': {e}")

    def _smooth_levels(self, raw: dict[str, float]) -> dict[str, float]:
        alpha = max(0.05, min(1.0, float(self.smoothing_factor)))
        out: dict[str, float] = {}
        for key in ("bass", "mid", "treble"):
            prev = self._smoothed_levels.get(key, 0.0)
            val = prev + (raw[key] - prev) * alpha
            out[key] = max(0.0, min(1.0, val))
            self._smoothed_levels[key] = out[key]
        return out

    def _record_levels(self, frame: AnalysisFrame) -> None:
        beat = float(frame.beat)
        self._last_beat = beat
        spectrum = list(frame.spectrum) if frame.spectrum else [0.0] * DEFAULT_SPECTRUM_BINS
        self._levels = {
            "bass": float(frame.bass),
            "mid": float(frame.mid),
            "treble": float(frame.treble),
            "beat": beat,
            "spectrum": spectrum,
        }

    def _rgb_for_named_light(
        self, name: str, position: str, frame: AnalysisFrame
    ) -> tuple[int, int, int]:
        env = getattr(self._analyzer, "_env_ui", {}) or {}
        bass_e = float(env.get("bass", frame.bass))
        mid_e = float(env.get("mid", frame.mid))
        treble_e = float(env.get("treble", frame.treble))
        energy_gain = float(self._analyzer.config.energy_gain)
        base = self._base_colors.get(name)
        if base is not None:
            return modulate_base_color(
                base,
                position,
                bass=bass_e,
                mid=mid_e,
                treble=treble_e,
                beat=self._last_beat,
                energy_gain=energy_gain,
            )
        name_phase = (sum(ord(c) for c in name) % 1000) / 1000.0
        return entertainment_color(
            bass=bass_e,
            mid=mid_e,
            treble=treble_e,
            beat=float(frame.beat),
            centroid=float(frame.centroid),
            stereo_bias=float(frame.stereo_bias),
            position=position,
            phase=(float(self._analyzer.phase) + name_phase) % 1.0,
            hue_speed=float(self._analyzer.config.hue_speed),
            energy_gain=energy_gain,
        )

    def _queue_smoothed_color(
        self,
        name: str,
        target: tuple[int, int, int],
        batch_all: bool,
        frame_colors: list[LightFrameColor],
    ) -> None:
        if name in self._smoothed_colors:
            smoothed = self._interpolate_color(self._smoothed_colors[name], target)
        else:
            smoothed = target
        if batch_all or self._color_changed_significantly(name, smoothed):
            self._smoothed_colors[name] = smoothed
            if is_enabled_for_app(name):
                bri = self._brightness_for_rgb(smoothed)
                frame_colors.append(
                    LightFrameColor(
                        light_name=name,
                        r=smoothed[0],
                        g=smoothed[1],
                        b=smoothed[2],
                        brightness=bri,
                    )
                )
        elif name in self._smoothed_colors:
            smoothed = self._smoothed_colors[name]
        self._current_colors[name] = smoothed

    def _push_frame_colors(self, frame_colors: list[LightFrameColor]) -> None:
        if not frame_colors:
            return
        try:
            if isinstance(self._output, RestPhueAdapter):
                self._output.transition_time = int(round(self.transition_time))
            self._output.apply_frame(frame_colors)
        except Exception as exc:
            logger.debug(f"apply_frame error: {exc}")

    def _process_frame(self, samples: np.ndarray, sample_rate: int) -> None:
        """
        Analisa bloco mono (N,) ou stereo (N, 2) e aplica cores por posição.

        Roles:
        - left / top-left / bottom-left → stereo left bias + mid/bass
        - right / top-right / bottom-right → right
        - bottom → bass dominant
        - top → treble + beat flash
        - center / ambient / none → full entertainment mix
        """
        if sample_rate != self._analyzer.sample_rate:
            self._analyzer.set_sample_rate(sample_rate)

        frame = self._analyzer.process(samples)
        self._record_levels(frame)
        frame_colors: list[LightFrameColor] = []
        batch_all = self._output.transport == "entertainment"
        for light in self.load_light_positions():
            name = str(light.get("name", ""))
            if not name:
                continue
            position = str(light.get("position", "ambient"))
            rgb = self._rgb_for_named_light(name, position, frame)
            self._queue_smoothed_color(name, rgb, batch_all, frame_colors)
        self._push_frame_colors(frame_colors)
        if self._on_status_change:
            self._on_status_change(self.get_status())

    def _bind_pulse_source(self) -> str | None:
        prev = os.environ.get("PULSE_SOURCE")
        pulse_source = self._pulse_source
        if pulse_source:
            os.environ["PULSE_SOURCE"] = pulse_source
            logger.info(f"PULSE_SOURCE={pulse_source} (system output monitor)")
        else:
            logger.warning(
                "Opening audio stream without PULSE_SOURCE monitor — "
                "likely capturing microphone/default source"
            )
        return prev

    def _restore_pulse_source(self, previous: str | None, bound: str | None) -> None:
        if bound is None:
            return
        if previous is None:
            os.environ.pop("PULSE_SOURCE", None)
            return
        os.environ["PULSE_SOURCE"] = previous

    def _ingest_stream_block(self, stream: Any, block: int, sample_rate: int) -> None:
        data, overflowed = stream.read(block)
        if overflowed:
            logger.debug("Audio buffer overflow")
        arr = np.asarray(data, dtype=np.float32)
        if arr.ndim == 2 and arr.shape[1] >= 2:
            self._process_frame(arr, sample_rate)
            return
        self._process_frame(arr.reshape(-1), sample_rate)

    def _mirror_loop(self) -> None:
        """Loop de captura de áudio + análise + aplicação nas lâmpadas."""
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
        except Exception:
            logger.exception("Could not resolve audio stream params")
            self.running = False
            return

        self._sample_rate = sample_rate
        self._channels = channels
        self._block_size = block
        self._analyzer.set_sample_rate(sample_rate)
        self._sync_analyzer_config()
        self._analyzer.reset()
        prev_pulse_source = self._bind_pulse_source()
        pulse_source = self._pulse_source
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
                    started = time.time()
                    try:
                        self._ingest_stream_block(stream, block, sample_rate)
                    except Exception as frame_exc:
                        logger.debug(f"Audio frame error: {frame_exc}")
                    frame_time = 1.0 / max(1, self.fps)
                    elapsed = time.time() - started
                    if elapsed < frame_time:
                        time.sleep(frame_time - elapsed)
        except Exception:
            logger.exception("Audio mirror stream failed")
            self.running = False
        finally:
            self._restore_pulse_source(prev_pulse_source, pulse_source)

    def _apply_start_knobs(
        self,
        fps: int | None,
        brightness: int | None,
        profile: str | None,
    ) -> None:
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

    def _pick_capture_device(self, device_resolver: Callable[[], int | None] | None) -> int:
        self._pulse_source = find_pulse_monitor_source()
        if self._pulse_source is None:
            logger.warning(
                "Nenhum sink monitor encontrado via pactl — a captura pode "
                "usar o microfone. Confira: pactl list short sources | "
                "grep monitor"
            )
        device = (
            device_resolver()
            if device_resolver is not None
            else find_monitor_device(pulse_source=self._pulse_source)
        )
        if device is None:
            raise RuntimeError(
                "Nenhum dispositivo de áudio encontrado. "
                "No Linux, use PulseAudio/PipeWire (device 'pulse') "
                "e garanta um sink monitor (o que você ouve). "
                "Verifique com: pactl list short sources"
            )
        return device

    def _warmup_stream(self, device: int) -> tuple[int, int, int]:
        try:
            sample_rate, channels, block = resolve_input_stream_params(device)
        except Exception as exc:
            self._device_index = None
            self._pulse_source = None
            raise RuntimeError(
                "Não foi possível abrir o dispositivo de áudio com uma taxa "
                f"de amostragem válida (device={device}). "
                "Tente o device pulse. Detalhe: "
                f"{exc}"
            ) from exc
        self._sample_rate = sample_rate
        self._channels = channels
        self._block_size = block
        self._analyzer.set_sample_rate(sample_rate)
        return sample_rate, channels, block

    def _begin_output_or_abort(self) -> None:
        try:
            self._output.begin_session()
            self._session_started = True
        except Exception as exc:
            self._device_index = None
            self._pulse_source = None
            raise RuntimeError(f"Falha ao iniciar transporte de saída: {exc}") from exc

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

        self._apply_start_knobs(fps, brightness, profile)
        device = self._pick_capture_device(device_resolver)
        self._device_index = device
        self._peak_tracker = PeakTracker()
        self._analyzer.reset()
        self._sync_analyzer_config()
        self.reload_light_positions()
        sample_rate, channels, _block = self._warmup_stream(device)
        logger.info(
            f"Starting audio mirroring (FPS: {self.fps}, brightness: {self.brightness}"
            f", profile: {self.active_profile}, device: {device}, "
            f"rate={sample_rate}, ch={channels}, pulse_source={self._pulse_source!r}, "
            f"transport={self._output.transport})"
        )
        self._begin_output_or_abort()
        self.running = True
        self.thread = threading.Thread(target=self._mirror_loop, daemon=True)
        self.thread.start()
        return True

    def stop(self, *, end_output: bool = True) -> bool:
        """Para o loop e limpa caches.

        ``end_output=False`` when the async route will ``await stop_stream()``
        to avoid deadlocking the event loop via ``run_coro``.
        """
        logger.info("Stopping audio mirroring")
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
            self.thread = None
        if self._session_started:
            if end_output:
                try:
                    self._output.end_session()
                except Exception as e:
                    logger.debug(f"end_session error: {e}")
            self._session_started = False
        self._current_colors.clear()
        self._smoothed_colors.clear()
        self._levels = {
            "bass": 0.0,
            "mid": 0.0,
            "treble": 0.0,
            "beat": 0.0,
            "spectrum": [0.0] * DEFAULT_SPECTRUM_BINS,
        }
        self._smoothed_levels = {"bass": 0.0, "mid": 0.0, "treble": 0.0}
        self._last_beat = 0.0
        self._device_index = None
        self._pulse_source = None
        self._cached_positions = None
        self._analyzer.reset()
        logger.info("Audio mirroring stopped successfully")
        return True

    def is_running(self) -> bool:
        return self.running

    def get_status(self) -> dict[str, Any]:
        """Status com levels de espectro (bass/mid/treble/beat + spectrum[]) e cores."""
        spectrum = self._levels.get("spectrum", [])
        if not isinstance(spectrum, list):
            spectrum = []
        return {
            "running": self.running,
            "mode": "audio",
            "fps": self.fps,
            "brightness": self.brightness,
            "smoothing_factor": self.smoothing_factor,
            "transition_time": self.transition_time,
            "energy_gain": self.energy_gain,
            "beat_sensitivity": self.beat_sensitivity,
            "hue_speed": self.hue_speed,
            "active_profile": self.active_profile,
            "colors": self._current_colors.copy(),
            "sample_rate": self._sample_rate,
            "channels": self._channels,
            "device_index": self._device_index,
            "pulse_source": self._pulse_source,
            "bass": float(self._levels.get("bass", 0.0) or 0.0),  # type: ignore[arg-type]
            "mid": float(self._levels.get("mid", 0.0) or 0.0),  # type: ignore[arg-type]
            "treble": float(self._levels.get("treble", 0.0) or 0.0),  # type: ignore[arg-type]
            "beat": float(self._levels.get("beat", 0.0) or 0.0),  # type: ignore[arg-type]
            "spectrum": list(spectrum),
            "transport": self._output.transport,
            "entertainment_area_id": self.entertainment_area_id,
            "entertainment_enabled": self.entertainment_enabled,
            "entertainment_ready": self._output.transport == "entertainment"
            or (
                # ready if credentials path could use entertainment later
                False
            ),
            "config_name": self.config_name,
        }

    def set_status_callback(self, callback: Callable[[dict[str, Any]], None]) -> None:
        self._on_status_change = callback
