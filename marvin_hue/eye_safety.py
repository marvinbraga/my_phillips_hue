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

Hardcoded EYE_SAFETY_LIMITS remains the offline fallback.
Runtime policy (from SQLite lights registry) may override limits and
mark lights as disabled for app features (enabled_for_app=False).
"""
from __future__ import annotations

# Limite por lâmpada, em PERCENTUAL (0-100). Fallback when registry silent.
EYE_SAFETY_LIMITS: dict[str, int] = {"Fita Led": 25, "Led cima": 25}

# Runtime overlays (name -> pct or None meaning "no extra row limit")
_runtime_limits_pct: dict[str, int | None] | None = None
_runtime_disabled: set[str] | None = None


def set_runtime_policy(
    *,
    limits_pct: dict[str, int | None],
    disabled_names: set[str],
) -> None:
    """Install policy from registry (sync cache). Call from async layer after load."""
    global _runtime_limits_pct, _runtime_disabled
    _runtime_limits_pct = dict(limits_pct)
    _runtime_disabled = set(disabled_names)


def set_runtime_limits(limits_pct: dict[str, int | None]) -> None:
    """Override only brightness limits (keeps current disabled set)."""
    global _runtime_limits_pct
    _runtime_limits_pct = dict(limits_pct)


def set_runtime_enabled(enabled_by_name: dict[str, bool]) -> None:
    """Set enabled_for_app map; False names go into the disabled set."""
    global _runtime_disabled
    _runtime_disabled = {name for name, enabled in enabled_by_name.items() if not enabled}


def clear_runtime_policy() -> None:
    """Clear runtime overlays (tests / shutdown)."""
    global _runtime_limits_pct, _runtime_disabled
    _runtime_limits_pct = None
    _runtime_disabled = None


def is_enabled_for_app(light_name: str) -> bool:
    """False only when registry marks the light disabled."""
    if _runtime_disabled is None:
        return True
    return light_name not in _runtime_disabled


def is_light_enabled_for_app(light_name: str) -> bool:
    """Alias matching API naming in home-features plan / requirements."""
    return is_enabled_for_app(light_name)


def get_effective_limit(light_name: str) -> int | None:
    """Effective eye-safety limit percent (runtime overlay on defaults)."""
    return eye_safety_limit_pct(light_name)


def eye_safety_limit_pct(light_name: str) -> int | None:
    """Limite percentual da lâmpada, ou None se não houver restrição."""
    if _runtime_limits_pct is not None and light_name in _runtime_limits_pct:
        runtime = _runtime_limits_pct[light_name]
        if runtime is not None:
            return runtime
        # Explicit null in DB → fall back to hardcoded for that name
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
    limit_pct = eye_safety_limit_pct(light_name)
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
