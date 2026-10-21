"""HITL (P9): tools que mudam estado de forma ampla/persistente.

Com ``AgentConfig.require_approval`` (padrão: desligado), o orquestrador e os
subagents pedem aprovação humana antes delas. Mudanças pontuais de lâmpada
(set_light_color, set_brightness, turn_*, set_color_temperature) ficam fora.
"""

from __future__ import annotations

from collections.abc import Iterable

_APPROVE_REJECT = {"allowed_decisions": ["approve", "reject"]}
_APPROVE_EDIT_REJECT = {"allowed_decisions": ["approve", "edit", "reject"]}

HITL_INTERRUPT_ON: dict[str, dict[str, list[str]]] = {
    "apply_config": _APPROVE_REJECT,
    "save_current_config": _APPROVE_EDIT_REJECT,
    "create_config": _APPROVE_EDIT_REJECT,
    "apply_config_to_group": _APPROVE_REJECT,
    "create_schedule": _APPROVE_REJECT,
    "set_schedule_enabled": _APPROVE_REJECT,
    "start_mirror": _APPROVE_REJECT,
    "stop_mirror": _APPROVE_REJECT,
    "undo_last_scene": _APPROVE_REJECT,
}


def interrupt_on_for(tool_names: Iterable[str]) -> dict[str, dict[str, list[str]]]:
    """Subconjunto de ``HITL_INTERRUPT_ON`` para as tools dadas."""
    names = set(tool_names)
    return {k: dict(v) for k, v in HITL_INTERRUPT_ON.items() if k in names}
