"""
Motor de análise de áudio estilo Hue Entertainment.

Análise pura (sem dependências Hue): ring buffer, multi-band density,
envelope followers, onset/beat (spectral flux), centroid, stereo bias
e mapeamento de cor entertainment (HSV → RGB).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping

import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_BUFFER_SIZE = 4096
DEFAULT_HOP_SIZE = 1024

# Multi-band edges (Hz)
BAND_EDGES: dict[str, tuple[float, float]] = {
    "sub": (20.0, 60.0),
    "bass": (60.0, 150.0),
    "lowmid": (150.0, 400.0),
    "mid": (400.0, 1000.0),
    "highmid": (1000.0, 2500.0),
    "treble": (2500.0, 6000.0),
    "presence": (6000.0, 12000.0),
}

# Aggregate for UI bars
UI_BAND_PARTS: dict[str, tuple[str, ...]] = {
    "bass": ("sub", "bass"),
    "mid": ("lowmid", "mid", "highmid"),
    "treble": ("treble", "presence"),
}

# dB mapping for spectral density (mean |FFT|² per bin, Hann window).
# Live float32 music on Pulse monitor ~RMS 0.02 → densidades ~1e-5..1e-2.
_POWER_REF = 2e-4
_FLOOR_DB = -48.0
_CEILING_DB = 6.0

# Spectral centroid normalization (Hz)
_CENTROID_MIN_HZ = 120.0
_CENTROID_MAX_HZ = 5500.0


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------


def hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    """
    Convert HSV to RGB 0–255.

    h: hue in [0, 1) (wraps); s, v in [0, 1].
    """
    h = float(h) % 1.0
    s = max(0.0, min(1.0, float(s)))
    v = max(0.0, min(1.0, float(v)))
    if s <= 1e-9:
        g = int(round(v * 255.0))
        return g, g, g

    i = int(h * 6.0)
    f = h * 6.0 - i
    p = v * (1.0 - s)
    q = v * (1.0 - f * s)
    t = v * (1.0 - (1.0 - f) * s)
    i = i % 6
    if i == 0:
        r, g, b = v, t, p
    elif i == 1:
        r, g, b = q, v, p
    elif i == 2:
        r, g, b = p, v, t
    elif i == 3:
        r, g, b = p, q, v
    elif i == 4:
        r, g, b = t, p, v
    else:
        r, g, b = v, p, q
    return (
        max(0, min(255, int(round(r * 255.0)))),
        max(0, min(255, int(round(g * 255.0)))),
        max(0, min(255, int(round(b * 255.0)))),
    )


def density_to_level(
    power: float,
    *,
    ref: float = _POWER_REF,
    floor_db: float = _FLOOR_DB,
    ceiling_db: float = _CEILING_DB,
    sensitivity: float = 1.0,
) -> float:
    """Map linear spectral density → 0..1 via absolute dB (not AGC)."""
    p = max(float(power), 0.0)
    if p <= 0.0:
        return 0.0
    sens = max(0.25, min(3.0, float(sensitivity)))
    db = 10.0 * math.log10(p / max(ref, 1e-18) + 1e-15)
    db += 6.0 * math.log2(sens)
    if db <= floor_db:
        return 0.0
    if db >= ceiling_db:
        return 1.0
    return (db - floor_db) / (ceiling_db - floor_db)


def entertainment_color(
    *,
    bass: float,
    mid: float,
    treble: float,
    beat: float,
    centroid: float,
    stereo_bias: float = 0.0,
    position: str = "ambient",
    phase: float = 0.0,
    hue_speed: float = 1.0,
    energy_gain: float = 1.0,
) -> tuple[int, int, int]:
    """
    Hue Entertainment-like color mapping.

    - Hue drifts with spectral centroid + slow phase + bass pull toward red/orange
    - Saturation stays high (0.72–1.0)
    - Value from weighted multi-band energy + beat flash
    - Optional stereo hue shift for left/right positions
    """
    b = max(0.0, min(1.0, float(bass)))
    m = max(0.0, min(1.0, float(mid)))
    t = max(0.0, min(1.0, float(treble)))
    beat_v = max(0.0, min(1.0, float(beat)))
    c = max(0.0, min(1.0, float(centroid)))
    bias = max(-1.0, min(1.0, float(stereo_bias)))
    pos = (position or "ambient").lower()

    # Base hue from brightness of spectrum (centroid) + slow drift
    # low centroid → warm (0.0–0.12), high → cyan/blue (0.45–0.62)
    base_hue = 0.02 + c * 0.55
    # Bass pulls hue toward red/magenta-warm
    base_hue = (base_hue - 0.08 * b + 0.04 * t) % 1.0
    # Slow phase wander (hue_speed scales)
    base_hue = (base_hue + float(phase) * 0.12 * max(0.1, hue_speed)) % 1.0

    # Position roles
    if pos in {"left", "top-left", "bottom-left"}:
        base_hue = (base_hue - 0.04 - 0.06 * max(0.0, -bias)) % 1.0
        energy = 0.45 * b + 0.45 * m + 0.10 * t
    elif pos in {"right", "top-right", "bottom-right"}:
        base_hue = (base_hue + 0.04 + 0.06 * max(0.0, bias)) % 1.0
        energy = 0.45 * b + 0.45 * m + 0.10 * t
    elif pos == "bottom":
        # Bass dominant — warmer
        base_hue = (base_hue * 0.35 + 0.02 * 0.65) % 1.0
        energy = 0.70 * b + 0.20 * m + 0.10 * t
    elif pos == "top":
        # Treble + beat flash — cooler
        base_hue = (base_hue * 0.4 + 0.55 * 0.6) % 1.0
        energy = 0.15 * b + 0.25 * m + 0.60 * t
        energy = min(1.0, energy + 0.35 * beat_v)
    else:
        # center / ambient / full mix
        energy = 0.40 * b + 0.35 * m + 0.25 * t

    gain = max(0.4, min(2.0, float(energy_gain)))
    energy = max(0.0, min(1.0, energy * (0.85 + 0.15 * gain)))

    # Saturation: high, slightly drops on very soft passages
    sat = 0.72 + 0.28 * min(1.0, 0.35 + energy + 0.2 * beat_v)

    # Value: floor so lights never fully black on soft music; beat flash
    value = 0.10 + 0.72 * energy + 0.28 * beat_v
    value = max(0.0, min(1.0, value))

    return hsv_to_rgb(base_hue, sat, value)


# ---------------------------------------------------------------------------
# Envelope + analysis frame
# ---------------------------------------------------------------------------


class EnvelopeFollower:
    """
    Per-band envelope with asymmetric attack/release.

    attack/release are blend coefficients in (0, 1]: higher = faster track.
    Typical: attack 0.3–0.6, release 0.05–0.15.
    """

    def __init__(self, attack: float = 0.45, release: float = 0.10) -> None:
        self.attack = max(0.01, min(1.0, float(attack)))
        self.release = max(0.005, min(1.0, float(release)))
        self.value: float = 0.0

    def process(self, x: float) -> float:
        target = max(0.0, float(x))
        if target > self.value:
            self.value += (target - self.value) * self.attack
        else:
            self.value += (target - self.value) * self.release
        return self.value

    def reset(self) -> None:
        self.value = 0.0


@dataclass
class AnalysisFrame:
    """One analysis hop result (UI-friendly + entertainment fields)."""

    bass: float = 0.0
    mid: float = 0.0
    treble: float = 0.0
    beat: float = 0.0
    centroid: float = 0.0
    stereo_bias: float = 0.0
    rms: float = 0.0
    bands: dict[str, float] = field(default_factory=dict)

    def color_for_position(
        self,
        position: str,
        *,
        phase: float = 0.0,
        hue_speed: float = 1.0,
        energy_gain: float = 1.0,
    ) -> tuple[int, int, int]:
        return entertainment_color(
            bass=self.bass,
            mid=self.mid,
            treble=self.treble,
            beat=self.beat,
            centroid=self.centroid,
            stereo_bias=self.stereo_bias,
            position=position,
            phase=phase,
            hue_speed=hue_speed,
            energy_gain=energy_gain,
        )


# ---------------------------------------------------------------------------
# AudioAnalyzer
# ---------------------------------------------------------------------------


@dataclass
class AnalyzerConfig:
    """Tunable analyzer parameters (profiles map into this)."""

    buffer_size: int = DEFAULT_BUFFER_SIZE
    hop_size: int = DEFAULT_HOP_SIZE
    attack: float = 0.45
    release: float = 0.10
    beat_sensitivity: float = 1.0
    beat_decay: float = 0.88
    hue_speed: float = 1.0
    energy_gain: float = 1.0
    # Per-band attack/release overrides (optional)
    band_attack: Mapping[str, float] | None = None
    band_release: Mapping[str, float] | None = None


class AudioAnalyzer:
    """
    Stateful multi-band analyzer with ring buffer, envelopes, and beat pulse.

    Call ``process(block)`` with mono (N,) or stereo (N, 2) float samples.
    Returns an ``AnalysisFrame`` every call (uses latest filled ring buffer).
    """

    def __init__(
        self,
        sample_rate: int = 44100,
        config: AnalyzerConfig | None = None,
    ) -> None:
        self.sample_rate = int(sample_rate)
        self.config = config or AnalyzerConfig()
        n = max(512, int(self.config.buffer_size))
        self._buf_size = n
        self._ring = np.zeros(n, dtype=np.float64)
        self._ring_l = np.zeros(n, dtype=np.float64)
        self._ring_r = np.zeros(n, dtype=np.float64)
        self._write = 0
        self._filled = 0
        self._stereo = False

        # Per fine-band envelopes
        self._envs: dict[str, EnvelopeFollower] = {}
        for name in BAND_EDGES:
            att = float(
                (self.config.band_attack or {}).get(name, self.config.attack)
            )
            rel = float(
                (self.config.band_release or {}).get(name, self.config.release)
            )
            # Slightly faster attack on bass/sub for punch; slower release on treble
            if name in {"sub", "bass"} and self.config.band_attack is None:
                att = min(1.0, att * 1.15)
            if name in {"treble", "presence"} and self.config.band_release is None:
                rel = max(0.03, rel * 0.85)
            self._envs[name] = EnvelopeFollower(attack=att, release=rel)

        self._prev_mag: np.ndarray | None = None
        self._flux_ema: float = 0.0
        self._flux_var: float = 1e-6
        self._beat_env: float = 0.0
        self._phase: float = 0.0
        self._frame_count: int = 0
        self._window = np.hanning(n)
        # UI spectrum: auto-range ceiling + peak-hold (separate from light envelopes)
        self._ui_ceiling: dict[str, float] = {
            "bass": 0.18,
            "mid": 0.18,
            "treble": 0.18,
        }
        self._ui_hold: dict[str, float] = {"bass": 0.0, "mid": 0.0, "treble": 0.0}
        # Last envelope aggregates (for smooth light colors)
        self._env_ui: dict[str, float] = {"bass": 0.0, "mid": 0.0, "treble": 0.0}

    def reset(self) -> None:
        self._ring.fill(0.0)
        self._ring_l.fill(0.0)
        self._ring_r.fill(0.0)
        self._write = 0
        self._filled = 0
        self._prev_mag = None
        self._flux_ema = 0.0
        self._flux_var = 1e-6
        self._beat_env = 0.0
        self._phase = 0.0
        self._frame_count = 0
        for env in self._envs.values():
            env.reset()
        self._ui_ceiling = {"bass": 0.18, "mid": 0.18, "treble": 0.18}
        self._ui_hold = {"bass": 0.0, "mid": 0.0, "treble": 0.0}
        self._env_ui = {"bass": 0.0, "mid": 0.0, "treble": 0.0}

    def configure(self, **kwargs: float | int) -> None:
        """Update selected AnalyzerConfig fields and re-tune envelopes if needed."""
        for key, val in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, val)
        # Refresh envelope rates when attack/release change
        if "attack" in kwargs or "release" in kwargs:
            for name, env in self._envs.items():
                att = float(self.config.attack)
                rel = float(self.config.release)
                if name in {"sub", "bass"}:
                    att = min(1.0, att * 1.15)
                if name in {"treble", "presence"}:
                    rel = max(0.03, rel * 0.85)
                env.attack = max(0.01, min(1.0, att))
                env.release = max(0.005, min(1.0, rel))

    def set_sample_rate(self, sample_rate: int) -> None:
        if int(sample_rate) != self.sample_rate:
            self.sample_rate = int(sample_rate)

    def _push(self, mono: np.ndarray, left: np.ndarray | None, right: np.ndarray | None) -> None:
        n = mono.size
        if n <= 0:
            return
        if n >= self._buf_size:
            mono = mono[-self._buf_size :]
            n = mono.size
            if left is not None:
                left = left[-self._buf_size :]
            if right is not None:
                right = right[-self._buf_size :]

        end = self._write + n
        if end <= self._buf_size:
            self._ring[self._write : end] = mono
            if left is not None and right is not None:
                self._ring_l[self._write : end] = left
                self._ring_r[self._write : end] = right
        else:
            first = self._buf_size - self._write
            self._ring[self._write :] = mono[:first]
            self._ring[: end % self._buf_size] = mono[first:]
            if left is not None and right is not None:
                self._ring_l[self._write :] = left[:first]
                self._ring_l[: end % self._buf_size] = left[first:]
                self._ring_r[self._write :] = right[:first]
                self._ring_r[: end % self._buf_size] = right[first:]
        self._write = end % self._buf_size
        self._filled = min(self._buf_size, self._filled + n)

    def _ordered_buffer(self) -> np.ndarray:
        if self._filled < self._buf_size:
            # Partial: return what we have zero-padded (stable FFT size)
            out = np.zeros(self._buf_size, dtype=np.float64)
            if self._filled > 0:
                out[-self._filled :] = self._ring[: self._filled]
            return out
        # Full ring: chronological order
        return np.concatenate((self._ring[self._write :], self._ring[: self._write]))

    def _band_densities(self, power_spec: np.ndarray, freqs: np.ndarray) -> dict[str, float]:
        nyq = self.sample_rate / 2.0
        out: dict[str, float] = {}
        for name, (lo, hi) in BAND_EDGES.items():
            hi_c = min(hi, nyq)
            if lo >= nyq or hi_c <= lo:
                out[name] = 0.0
                continue
            mask = (freqs >= lo) & (freqs < hi_c)
            n = int(np.count_nonzero(mask))
            if n <= 0:
                out[name] = 0.0
            else:
                out[name] = float(np.sum(power_spec[mask]) / n)
        return out

    def _spectral_centroid(self, mag: np.ndarray, freqs: np.ndarray) -> float:
        total = float(np.sum(mag))
        if total < 1e-12:
            return 0.0
        # Ignore DC / sub-20 for stability
        mask = freqs >= 20.0
        if not np.any(mask):
            return 0.0
        m = mag[mask]
        f = freqs[mask]
        s = float(np.sum(m))
        if s < 1e-12:
            return 0.0
        hz = float(np.sum(f * m) / s)
        # Log-ish normalize
        lo = math.log(_CENTROID_MIN_HZ)
        hi = math.log(_CENTROID_MAX_HZ)
        hz_c = max(_CENTROID_MIN_HZ, min(_CENTROID_MAX_HZ, hz))
        return max(0.0, min(1.0, (math.log(hz_c) - lo) / (hi - lo)))

    def _update_beat(self, mag: np.ndarray) -> float:
        """Spectral flux onset → beat pulse 0..1 with decay envelope."""
        if self._prev_mag is None or self._prev_mag.shape != mag.shape:
            self._prev_mag = mag.copy()
            self._beat_env *= float(self.config.beat_decay)
            return self._beat_env

        diff = mag - self._prev_mag
        flux = float(np.sum(np.maximum(diff, 0.0)))
        self._prev_mag = mag.copy()

        # Adaptive threshold via EMA of flux
        alpha = 0.15
        delta = flux - self._flux_ema
        self._flux_ema += alpha * delta
        self._flux_var = (1.0 - alpha) * self._flux_var + alpha * (delta * delta)
        std = math.sqrt(max(self._flux_var, 1e-12))
        sens = max(0.3, min(2.5, float(self.config.beat_sensitivity)))
        # Higher sensitivity → lower threshold
        thresh = self._flux_ema + (1.6 / sens) * std
        onset = 0.0
        if flux > thresh and flux > 1e-8:
            onset = min(1.0, (flux - thresh) / (thresh + 1e-9) * 0.5 * sens)
            onset = max(0.0, min(1.0, onset))

        decay = max(0.5, min(0.98, float(self.config.beat_decay)))
        if onset > self._beat_env:
            self._beat_env = min(1.0, 0.35 * self._beat_env + 0.85 * onset)
        else:
            self._beat_env *= decay
        return max(0.0, min(1.0, self._beat_env))

    def process(self, block: np.ndarray) -> AnalysisFrame:
        """
        Ingest a mono (N,) or stereo (N, C) block and return an AnalysisFrame.

        Stereo is preserved for L/R bias; mono mix is used for spectrum.
        """
        arr = np.asarray(block, dtype=np.float64)
        left: np.ndarray | None = None
        right: np.ndarray | None = None

        if arr.ndim == 2 and arr.shape[1] >= 2:
            left = arr[:, 0]
            right = arr[:, 1]
            mono = 0.5 * (left + right)
            self._stereo = True
        elif arr.ndim == 2:
            mono = arr[:, 0]
            self._stereo = False
        else:
            mono = arr.reshape(-1)
            self._stereo = False

        if mono.size == 0:
            return AnalysisFrame()

        self._push(mono, left, right)
        buf = self._ordered_buffer()
        rms = float(np.sqrt(np.mean(buf * buf) + 1e-20))

        # Silence short-circuit (still decay envelopes / beat)
        if rms < 1e-5:
            for env in self._envs.values():
                env.process(0.0)
            self._beat_env *= float(self.config.beat_decay)
            for k in self._ui_hold:
                self._ui_hold[k] *= 0.9
                self._ui_ceiling[k] = max(0.12, self._ui_ceiling[k] * 0.99)
            self._env_ui = {"bass": 0.0, "mid": 0.0, "treble": 0.0}
            self._frame_count += 1
            return AnalysisFrame(
                bass=self._ui_hold["bass"] * 0.5,
                mid=self._ui_hold["mid"] * 0.5,
                treble=self._ui_hold["treble"] * 0.5,
                beat=max(0.0, self._beat_env),
                centroid=0.0,
                stereo_bias=0.0,
                rms=rms,
                bands={k: 0.0 for k in BAND_EDGES},
            )

        windowed = buf * self._window
        spectrum = np.fft.rfft(windowed)
        mag = np.abs(spectrum)
        power_spec = (mag ** 2) / max(self._buf_size, 1)
        freqs = np.fft.rfftfreq(self._buf_size, d=1.0 / self.sample_rate)

        # Mild pre-emphasis so treble is visible on bass-heavy tracks
        if mag.size > 4:
            n_bins = mag.size
            pre = 1.0 + 1.8 * (np.arange(n_bins, dtype=np.float64) / max(n_bins - 1, 1))
            power_ui = ((mag * pre) ** 2) / max(self._buf_size, 1)
        else:
            power_ui = power_spec

        densities = self._band_densities(power_spec, freqs)
        densities_ui = self._band_densities(power_ui, freqs)
        sens = float(self.config.energy_gain)

        raw_levels: dict[str, float] = {
            name: density_to_level(densities[name], sensitivity=sens)
            for name in BAND_EDGES
        }
        env_levels: dict[str, float] = {
            name: self._envs[name].process(raw_levels[name]) for name in BAND_EDGES
        }

        def _agg_mean(parts: tuple[str, ...], src: dict[str, float]) -> float:
            vals = [src[p] for p in parts]
            return max(0.0, min(1.0, float(sum(vals) / max(len(vals), 1))))

        def _agg_max_d(parts: tuple[str, ...], src: dict[str, float]) -> float:
            return float(max(max(0.0, src[p]) for p in parts))

        env_bass = _agg_mean(UI_BAND_PARTS["bass"], env_levels)
        env_mid = _agg_mean(UI_BAND_PARTS["mid"], env_levels)
        env_treble = _agg_mean(UI_BAND_PARTS["treble"], env_levels)
        self._env_ui = {"bass": env_bass, "mid": env_mid, "treble": env_treble}

        # --- UI meters: relative spectral balance × overall loudness ---
        # Use MAX density per group (not sum) so mid's 3 sub-bands don't dominate.
        # Log-scale equalizes decades of energy difference between bass and treble.
        def _log_p(x: float, boost: float = 1.0) -> float:
            return float(np.log1p(max(0.0, x) * boost * 5e4))

        p_b = _log_p(_agg_max_d(UI_BAND_PARTS["bass"], densities_ui), 1.0) + 1e-9
        p_m = _log_p(_agg_max_d(UI_BAND_PARTS["mid"], densities_ui), 1.15) + 1e-9
        p_t = _log_p(_agg_max_d(UI_BAND_PARTS["treble"], densities_ui), 6.0) + 1e-9
        p_tot = p_b + p_m + p_t

        # Overall loudness from time-domain RMS (0..1), snappy
        # rms ~0.01 quiet, ~0.04 moderate, ~0.1 loud on Pulse monitor
        loud_lin = min(1.0, float(np.sqrt(max(rms, 0.0) / 0.05)))
        loud_lin = loud_lin ** 0.75
        loud_lin = min(1.0, loud_lin * (0.85 + 0.25 * sens))

        share_b = p_b / p_tot
        share_m = p_m / p_tot
        share_t = p_t / p_tot

        def _meter(share: float, weight: float = 1.0) -> float:
            # equal share (~0.33) → strong bar when loud; unequal shares spread bars
            shaped = (share * 2.5 * weight) ** 0.7
            return max(0.0, min(1.0, shaped * max(loud_lin, 0.08)))

        inst = {
            "bass": _meter(share_b, 1.0),
            "mid": _meter(share_m, 1.0),
            "treble": _meter(share_t, 1.2),
        }

        display: dict[str, float] = {}
        for key, instant in inst.items():
            # Fast peak-hold for the tip
            hold = self._ui_hold[key]
            if instant >= hold:
                hold = instant
            else:
                hold = hold * 0.88
            self._ui_hold[key] = hold
            self._ui_ceiling[key] = max(0.15, self._ui_ceiling[key] * 0.995, instant)
            display[key] = max(0.0, min(1.0, 0.78 * instant + 0.22 * hold))

        bass = display["bass"]
        mid = display["mid"]
        treble = display["treble"]

        centroid = self._spectral_centroid(mag, freqs)
        beat = self._update_beat(mag)

        # Stereo bias -1..1 from ring L/R RMS
        stereo_bias = 0.0
        if self._stereo and self._filled >= 64:
            if self._filled < self._buf_size:
                lbuf = self._ring_l[: self._filled]
                rbuf = self._ring_r[: self._filled]
            else:
                lbuf = np.concatenate(
                    (self._ring_l[self._write :], self._ring_l[: self._write])
                )
                rbuf = np.concatenate(
                    (self._ring_r[self._write :], self._ring_r[: self._write])
                )
            rms_l = float(np.sqrt(np.mean(lbuf * lbuf) + 1e-20))
            rms_r = float(np.sqrt(np.mean(rbuf * rbuf) + 1e-20))
            stereo_bias = (rms_r - rms_l) / (rms_r + rms_l + 1e-9)
            stereo_bias = max(-1.0, min(1.0, stereo_bias))

        # Advance slow hue phase from envelope energy (stable lights)
        energy = 0.4 * env_bass + 0.35 * env_mid + 0.25 * env_treble
        self._phase = (
            self._phase + 0.008 * float(self.config.hue_speed) * (0.3 + 0.7 * energy)
        ) % 1.0
        self._frame_count += 1

        return AnalysisFrame(
            bass=bass,
            mid=mid,
            treble=treble,
            beat=beat,
            centroid=centroid,
            stereo_bias=stereo_bias,
            rms=rms,
            bands=env_levels,
        )

    @property
    def phase(self) -> float:
        return self._phase

    def color_for_position(self, position: str, frame: AnalysisFrame) -> tuple[int, int, int]:
        """Map light color from envelope levels (smooth), not raw UI meters."""
        return entertainment_color(
            bass=self._env_ui.get("bass", frame.bass),
            mid=self._env_ui.get("mid", frame.mid),
            treble=self._env_ui.get("treble", frame.treble),
            beat=frame.beat,
            centroid=frame.centroid,
            stereo_bias=frame.stereo_bias,
            position=position,
            phase=self._phase,
            hue_speed=float(self.config.hue_speed),
            energy_gain=float(self.config.energy_gain),
        )
