"""EyeSafetyMiddleware — feedback de segurança ocular nas tools diretas.

Fita Led e Led cima estão muito próximas aos olhos: brilho > limite é clampado
antes de executar a tool, dando ao modelo um sinal coerente. A garantia
AUTORITATIVA de <=25% mora no chokepoint do HueController (set_light_color /
apply_light_config); este middleware NÃO é a única defesa. Reusa a função
canônica `clamp_eye_safety` (fonte única, achado #4).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from langchain.agents.middleware import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolCall

from marvin_hue.eye_safety import EYE_SAFETY_LIMITS, clamp_eye_safety

# Tools cujos args carregam brilho e a escala de cada uma.
# "pct"  -> brightness é 0-100 (set_brightness)
# "hue"  -> brightness é 0-254 (set_light_color, apply via cor)
_BRIGHTNESS_FIELD_SCALE: dict[str, tuple[str, str]] = {
    "set_brightness": ("brightness", "pct"),
    "set_light_color": ("brightness", "hue"),
}


class EyeSafetyMiddleware(AgentMiddleware):
    """Clampa o brilho das lâmpadas frontais antes de executar a tool direta."""

    def _override_request(self, request: ToolCallRequest) -> ToolCallRequest:
        name = request.tool_call["name"]
        spec = _BRIGHTNESS_FIELD_SCALE.get(name)
        if spec is None:
            return request
        field, scale = spec
        args = request.tool_call["args"]
        light = args.get("light_name")
        if not isinstance(light, str) or EYE_SAFETY_LIMITS.get(light) is None or field not in args:
            return request
        # NÃO mutar in-place (caminho deprecado). Construir override imutável.
        new_args = {**args, field: clamp_eye_safety(light, int(args[field]), scale=scale)}
        new_tool_call = cast(ToolCall, {**request.tool_call, "args": new_args})
        return request.override(tool_call=new_tool_call)

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ) -> Any:
        # handler devolve ToolMessage | Command — apenas repassamos (D3).
        return handler(self._override_request(request))

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ) -> Any:
        return await handler(self._override_request(request))
