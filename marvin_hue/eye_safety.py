"""Invariante de segurança ocular — fonte única de verdade (produção).

Mora na raiz do pacote (domínio físico das luzes): controllers.py (core)
NÃO pode depender de chat/ — inversão de dependência e risco de ciclo.
Fita Led e Led cima estão muito próximas aos olhos: brilho > limite é
bloqueado por CÓDIGO, independentemente do que o modelo solicitar. Reusado por:
  - EyeSafetyMiddleware (feedback ao modelo nas tools diretas) — Fase 3.2;
  - HueController.set_light_color / apply_light_config / set_brightness /
    set_all_brightness (garantia real no chokepoint, cobre presets,
    screen-mirror e o caminho "all") — Fase 2.3/3.x;
  - eval-set de invariantes (tests/eval) — Fase 0.3.
"""
from __future__ import annotations

# Limite por lâmpada, em PERCENTUAL (0-100). Fonte: .res/light_physical_locations.json
EYE_SAFETY_LIMITS: dict[str, int] = {"Fita Led": 25, "Led cima": 25}


def eye_safety_limit_pct(light_name: str) -> int | None:
    """Limite percentual da lâmpada, ou None se não houver restrição."""
    return EYE_SAFETY_LIMITS.get(light_name)


def clamp_eye_safety(light_name: str, value: int, scale: str = "pct") -> int:
    """Clampa `value` ao limite da lâmpada na escala indicada.

    Args:
        light_name: nome exato da lâmpada.
        value: brilho solicitado, na escala `scale`.
        scale: "pct" (0-100) ou "hue" (0-254).
    Returns:
        O brilho clampado (na MESMA escala de entrada). Sem restrição -> inalterado.
    """
    limit_pct = EYE_SAFETY_LIMITS.get(light_name)
    if limit_pct is None:
        return value
    if scale == "pct":
        return min(value, limit_pct)
    if scale == "hue":
        # Teto de SEGURANÇA: arredonda PARA BAIXO (floor), nunca para cima.
        # 25% de 254 = 63.5 -> 63 (24.8%); round() daria 64 (25.2%), acima do limite.
        hue_limit = int((limit_pct / 100) * 254)
        return min(value, hue_limit)
    raise ValueError(f"escala desconhecida: {scale!r}")
