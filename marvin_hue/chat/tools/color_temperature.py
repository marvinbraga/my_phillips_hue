"""Temperatura de cor (Kelvin) → RGB, aproximação de Tanner Helland.

Função pura: o resultado vira uma cor RGB comum, então todo o caminho de cor e
de segurança ocular do ``HueController`` é reaproveitado (sem suporte a ``ct``).
"""

from __future__ import annotations

import math

KELVIN_MIN = 2000
KELVIN_MAX = 6500


def clamp_kelvin(kelvin: int) -> int:
    """Limita a temperatura à faixa suportada (2000–6500 K)."""
    return max(KELVIN_MIN, min(KELVIN_MAX, int(kelvin)))


def _channel(value: float) -> int:
    return max(0, min(255, int(round(value))))


def kelvin_to_rgb(kelvin: int) -> tuple[int, int, int]:
    """Converte Kelvin (limitado a 2000–6500) em RGB 0–255.

    Na faixa suportada (temp/100 entre 20 e 65) só valem os ramos "quentes"
    de Tanner Helland: vermelho saturado, verde e azul por log.
    """
    temp = clamp_kelvin(kelvin) / 100.0
    green = 99.4708025861 * math.log(temp) - 161.1195681661
    blue = 138.5177312231 * math.log(temp - 10) - 305.0447927307
    return 255, _channel(green), _channel(blue)
