"""HueContextMiddleware — injeta contexto vivo no system prompt a cada turno."""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

from marvin_hue.controllers import HueController
from marvin_hue.basics import LightSetupsManager


class HueContextMiddleware(AgentMiddleware):
    def __init__(self, controller: HueController, manager: LightSetupsManager,
                 locations_path: Optional[str] = ".res/light_physical_locations.json",
                 status_ttl_s: float = 2.0):
        super().__init__()
        self._controller = controller
        self._manager = manager
        self._locations_path = locations_path
        # get_lights_status() faz I/O na bridge FÍSICA (lenta, centenas de ms) e
        # wrap_model_call roda a CADA chamada de modelo — N vezes por turno num
        # loop de tools. Cache TTL curto evita marretar a bridge.
        self._status_ttl_s = status_ttl_s
        self._status_cache: Optional[str] = None
        self._status_cache_at = 0.0

    def _status_block(self) -> str:
        now = time.monotonic()
        if self._status_cache is not None and (now - self._status_cache_at) < self._status_ttl_s:
            return self._status_cache
        try:
            rows = self._controller.get_lights_status()
        except Exception:  # noqa: BLE001
            return ""
        lines = ["Status ATUAL das lâmpadas:"]
        for s in rows:
            estado = "ligada" if s["on"] else "desligada"
            pct = int((s["brightness"] / 254) * 100) if s["on"] else 0
            lines.append(f"- {s['name']}: {estado}, brilho {pct}%")
        self._status_cache = "\n".join(lines)
        self._status_cache_at = now
        return self._status_cache

    def _presets_block(self) -> str:
        names = [c.name for c in getattr(self._manager, "configs", [])][:30]
        return "Presets disponíveis: " + ", ".join(names) if names else ""

    def _locations_block(self) -> str:
        if not self._locations_path or not Path(self._locations_path).exists():
            return ""
        data = json.loads(Path(self._locations_path).read_text(encoding="utf-8"))
        warns = [
            f"- {l['name']}: máx {l['max_brightness_percent']}% (próxima aos olhos)"
            for l in data.get("lights", []) if "max_brightness_percent" in l
        ]
        return "Restrições físicas:\n" + "\n".join(warns) if warns else ""

    def _augment(self, base: str) -> str:
        blocks = [base, self._status_block(), self._locations_block(), self._presets_block()]
        return "\n\n".join(b for b in blocks if b)

    def wrap_model_call(
        self, request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        # Forma canônica (não-deprecada): override via system_message.
        augmented = self._augment(request.system_prompt or "")
        return handler(request.override(system_message=SystemMessage(content=augmented)))

    async def awrap_model_call(
        self, request: ModelRequest,
        handler: Callable[[ModelRequest], Any],
    ) -> Any:
        augmented = self._augment(request.system_prompt or "")
        return await handler(request.override(system_message=SystemMessage(content=augmented)))
