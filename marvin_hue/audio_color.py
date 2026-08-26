"""Band mapping and RGB modulation for audio-reactive lighting.

Separable from AudioMirror lifecycle: positions → bands → RGB scaling.
DSP stays in audio_engine; this module only maps energy onto colors.
"""

from __future__ import annotations

import numpy as np

from marvin_hue.audio_engine import density_to_level

# Frequências de corte aproximadas (Hz) para bandas legadas (compat)
_BASS_MAX_HZ = 250.0
_MID_MAX_HZ = 2000.0
_BASS_MIN_HZ = 20.0
_TREBLE_MAX_HZ = 12_000.0
_MIN_SAMPLES_FOR_FFT = 8
_SILENCE_RMS = 1e-5

# Floor scale when energy≈0 so lights dim but keep a faint glow of the setup hue.
_BASE_COLOR_FLOOR = 0.15
# How much beat lifts toward white (preserves hue family, adds punch).
_BEAT_WHITE_LIFT = 0.28
_BEAT_SCALE_BOOST = 0.35
_MAX_MODULATION_SCALE = 1.15
_BAND_COLOR_FLOOR = 0.12
_BAND_COLOR_RANGE = 0.88

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

BAND_BASE_COLORS: dict[str, tuple[int, int, int]] = {
    "bass": (255, 60, 20),
    "mid": (120, 40, 200),
    "treble": (40, 180, 255),
}

_MID_GREEN = (40, 200, 80)
_MID_PURPLE = (140, 40, 220)


def position_to_band(position: str) -> str:
    """Mapeia posição da lâmpada para banda (bass|mid|treble). Desconhecido → mid."""
    return POSITION_TO_BAND.get(position, "mid")


def _clamp_unit(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _clamp_rgb_int(value: float) -> int:
    return max(0, min(255, round(value)))


def _mid_band_base(energy: float) -> tuple[int, int, int]:
    g0, g1 = _MID_GREEN, _MID_PURPLE
    return (
        int(g0[0] + (g1[0] - g0[0]) * energy),
        int(g0[1] + (g1[1] - g0[1]) * energy),
        int(g0[2] + (g1[2] - g0[2]) * energy),
    )


def band_color(band: str, energy: float) -> tuple[int, int, int]:
    """
    Converte banda + energia (0–1) em RGB (legado / fallback).

    Bass → vermelhos/laranjas; mid → verdes/roxos; treble → azuis/cianos.
    """
    e = _clamp_unit(energy)
    if band == "bass":
        base = BAND_BASE_COLORS["bass"]
    elif band == "treble":
        base = BAND_BASE_COLORS["treble"]
    else:
        base = _mid_band_base(e)
    scale = _BAND_COLOR_FLOOR + _BAND_COLOR_RANGE * e
    return (
        max(0, min(255, int(base[0] * scale))),
        max(0, min(255, int(base[1] * scale))),
        max(0, min(255, int(base[2] * scale))),
    )


def _band_energy(band: str, bass: float, mid: float, treble: float) -> float:
    if band == "bass":
        return float(bass)
    if band == "treble":
        return float(treble)
    return float(mid)


def modulate_base_color(
    base_rgb: tuple[int, int, int],
    position: str,
    *,
    bass: float = 0.0,
    mid: float = 0.0,
    treble: float = 0.0,
    beat: float = 0.0,
    energy_gain: float = 1.0,
) -> tuple[int, int, int]:
    """
    Escala a cor base da LightConfig pela energia da banda da posição.

    Preserva a proporção R:G:B do setup (não inventa hue via centroide).
    Silêncio → dim (floor); energia alta + beat → brilho e leve lift ao branco.
    """
    raw = _band_energy(position_to_band(position), bass, mid, treble) * energy_gain
    energy = _clamp_unit(raw)
    beat_c = _clamp_unit(beat)
    scale = _BASE_COLOR_FLOOR + (1.0 - _BASE_COLOR_FLOOR) * energy
    scale = min(_MAX_MODULATION_SCALE, scale * (1.0 + _BEAT_SCALE_BOOST * beat_c))
    white_mix = _BEAT_WHITE_LIFT * beat_c
    keep = 1.0 - white_mix
    r0, g0, b0 = base_rgb
    return (
        _clamp_rgb_int(r0 * scale * keep + 255.0 * white_mix * scale),
        _clamp_rgb_int(g0 * scale * keep + 255.0 * white_mix * scale),
        _clamp_rgb_int(b0 * scale * keep + 255.0 * white_mix * scale),
    )


def compute_band_powers(
    samples: np.ndarray,
    sample_rate: int,
) -> dict[str, float]:
    """Energia bruta (densidade) por banda — legado / AGC debug."""
    if samples.size < _MIN_SAMPLES_FOR_FFT:
        return {"bass": 0.0, "mid": 0.0, "treble": 0.0, "rms": 0.0}

    mono = np.asarray(samples, dtype=np.float64).reshape(-1)
    rms = float(np.sqrt(np.mean(mono * mono)))

    window = np.hanning(mono.size)
    spectrum = np.fft.rfft(mono * window)
    power_spec = (np.abs(spectrum) ** 2) / max(mono.size, 1)
    freqs = np.fft.rfftfreq(mono.size, d=1.0 / sample_rate)

    def _band_power(f_lo: float, f_hi: float) -> float:
        mask = (freqs >= f_lo) & (freqs < f_hi)
        n = int(np.count_nonzero(mask))
        if n <= 0:
            return 0.0
        return float(np.sum(power_spec[mask]) / n)

    return {
        "bass": _band_power(_BASS_MIN_HZ, _BASS_MAX_HZ),
        "mid": _band_power(_BASS_MAX_HZ, _MID_MAX_HZ),
        "treble": _band_power(_MID_MAX_HZ, min(sample_rate / 2.0, _TREBLE_MAX_HZ)),
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

    Wrapper legado — mesma assinatura dos testes; implementação alinhada
    ao density_to_level do audio_engine com defaults históricos.
    """
    return density_to_level(
        power,
        ref=ref,
        floor_db=floor_db,
        ceiling_db=ceiling_db,
        sensitivity=sensitivity,
    )


def compute_band_energies(
    samples: np.ndarray,
    sample_rate: int,
    *,
    peak_tracker: PeakTracker | None = None,
    sensitivity: float = 1.0,
) -> dict[str, float]:
    """
    Energia 0–1 por banda em escala **absoluta dB** (compat).

    Preferir ``AudioAnalyzer`` no loop principal; esta função permanece
    para testes e callers legados.
    """
    powers = compute_band_powers(samples, sample_rate)
    if powers["rms"] < _SILENCE_RMS:
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

    def _gated_level(self, key: str, raw: float) -> float:
        v = _clamp_unit(raw)
        if v > self.ceilings[key]:
            self.ceilings[key] = v
        else:
            self.ceilings[key] = max(self.gate, self.ceilings[key] * self.release)
        if v < self.gate:
            return 0.0
        return _clamp_unit((v - self.gate) / (1.0 - self.gate))

    def normalize(
        self,
        absolute_levels: dict[str, float],
        _raw_powers: dict[str, float] | None = None,
    ) -> dict[str, float]:
        return {
            key: self._gated_level(key, float(absolute_levels.get(key, 0.0)))
            for key in ("bass", "mid", "treble")
        }
