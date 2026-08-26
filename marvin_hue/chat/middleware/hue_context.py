"""HueContextMiddleware — injeta contexto vivo no system prompt a cada turno."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

from marvin_hue.basics import LightSetupsManager
from marvin_hue.controllers import HueController


class HueContextMiddleware(AgentMiddleware):
    def __init__(
        self,
        controller: HueController,
        manager: LightSetupsManager,
        locations_path: str | None = ".res/light_physical_locations.json",
        status_ttl_s: float = 2.0,
        *,
        registry_rows: Sequence[object] | None = None,
    ):
        super().__init__()
        self._controller = controller
        self._manager = manager
        self._locations_path = locations_path
        self._registry_rows = registry_rows
        # get_lights_status() faz I/O na bridge FÍSICA (lenta, centenas de ms) e
        # wrap_model_call roda a CADA chamada de modelo — N vezes por turno num
        # loop de tools. Cache TTL curto evita marretar a bridge.
        self._status_ttl_s = status_ttl_s
        self._status_cache: str | None = None
        self._status_cache_at = 0.0
        # Localizações são estáticas: parseia uma vez (memoizado), nunca a cada turno.
        self._locations_cache: str | None = None

    def _status_block(self) -> str:
        now = time.monotonic()
        if (
            self._status_cache is not None
            and (now - self._status_cache_at) < self._status_ttl_s
        ):
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

    def _registry_restrictions_block(self, rows: Sequence[object]) -> str:
        warns: list[str] = []
        for row in rows:
            name = str(getattr(row, "name", "") or "").strip()
            if not name:
                continue
            limit = getattr(row, "eye_safety_limit_pct", None)
            if isinstance(limit, bool) or not isinstance(limit, int):
                continue
            warns.append(f"- {name}: máx {limit}% (próxima aos olhos)")
        return "Restrições físicas:\n" + "\n".join(warns) if warns else ""

    def _json_restrictions_block(self) -> str:
        if not self._locations_path or not Path(self._locations_path).exists():
            return ""
        try:
            data = json.loads(Path(self._locations_path).read_text(encoding="utf-8"))
            warns = [
                f"- {item['name']}: máx {item['max_brightness_percent']}% "
                "(próxima aos olhos)"
                for item in data.get("lights", [])
                if "max_brightness_percent" in item and "name" in item
            ]
            return "Restrições físicas:\n" + "\n".join(warns) if warns else ""
        except Exception:  # noqa: BLE001
            return ""

    def _locations_block(self) -> str:
        # Memoizado: registry snapshot / arquivo estático; não relê a cada
        # chamada de modelo. Falha graciosamente (retorna "") — espelha _status_block.
        if self._locations_cache is not None:
            return self._locations_cache
        if self._registry_rows is not None:
            block = self._registry_restrictions_block(self._registry_rows)
        else:
            block = self._json_restrictions_block()
        self._locations_cache = block
        return block

    def _augment(self, base: str) -> str:
        blocks = [
            base,
            self._status_block(),
            self._locations_block(),
            self._presets_block(),
        ]
        return "\n\n".join(b for b in blocks if b)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        # Forma canônica (não-deprecada): override via system_message.
        augmented = self._augment(request.system_prompt or "")
        return handler(
            request.override(system_message=SystemMessage(content=augmented))
        )

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Any],
    ) -> Any:
        # _augment faz I/O SÍNCRONO na bridge física (get_lights_status). No
        # caminho async (FastAPI), executá-lo direto bloquearia o event loop
        # (compartilhado com o WebSocket /ws/mirror). Offload p/ thread.
        augmented = await asyncio.to_thread(self._augment, request.system_prompt or "")
        return await handler(
            request.override(system_message=SystemMessage(content=augmented))
        )
