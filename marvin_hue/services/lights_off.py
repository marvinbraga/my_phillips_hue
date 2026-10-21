"""Turn off every enabled light (HTTP ``POST /lights/off``).

Focused application service — not a Facade. Order of operations:

1. Stop an active screen/audio mirror (fail-open), otherwise its capture loop
   would relight the lamps right after we turn them off. The mirror takes its
   own ``mirror_stop`` snapshot.
2. Resolve the enabled light names from the controller cache (no bridge I/O).
   None enabled → empty ``ApplyResult``, no snapshot.
3. Read the bridge status ONCE. Failure here means the bridge is unreachable:
   raise ``LightsOffBridgeError`` (fail fast; the route maps it to the
   documented 500 body) instead of N per-light timeouts.
4. Store that status as the ``lights_off`` snapshot (newest, so "Desfazer"
   restores the scene that was lit) — skipped when every enabled light is
   already off, so a second press never makes undo restore "off". Snapshot
   persistence is fail-open.
5. One offloaded pass of one-shot transitions; per-light errors never abort
   the rest.
6. At least one light turned off → forget the last applied scene (best-effort),
   since the lights no longer show it.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from marvin_hue.apply_result import ApplyResult
from marvin_hue.eye_safety import is_enabled_for_app
from marvin_hue.logging_config import get_logger
from marvin_hue.services.last_applied_scene import (
    SOURCE_LIGHTS_OFF,
    LastAppliedClearPort,
)
from marvin_hue.services.mirror_control import MirrorNotActiveError

logger = get_logger("services.lights_off")

LIGHTS_OFF_SOURCE = SOURCE_LIGHTS_OFF
LIGHTS_OFF_LABEL = "before lights off"


class LightsOffBridgeError(Exception):
    """The bridge could not be read before the turn-off loop started.

    ``light_names`` holds the enabled lights that were about to be turned off
    (empty when even the inventory could not be listed).
    """

    def __init__(self, message: str, light_names: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.light_names = light_names


class HueLightsOffPort(Protocol):
    """Port: the HueController calls this use case needs (sync; offloaded)."""

    def list_lights(self) -> list[str]: ...

    def get_lights_status(self) -> list[dict[str, Any]]: ...

    def turn_off_with_transition(self, light_name: str, tenths: int) -> bool: ...


class LightsOffHistoryPort(Protocol):
    """Port: persist an already-captured status as a scene snapshot."""

    async def snapshot_status(
        self,
        status: list[dict[str, Any]],
        *,
        source: str,
        label: str | None = None,
    ) -> Any: ...


class MirrorStopPort(Protocol):
    """Port: ``MirrorControlService.stop`` (raises when no mirror is running)."""

    async def stop(self) -> dict[str, Any]: ...


def _any_enabled_light_on(status: list[dict[str, Any]], enabled: set[str]) -> bool:
    return any(bool(row.get("on")) for row in status if str(row.get("name")) in enabled)


def _turn_off_sync(hue: HueLightsOffPort, names: list[str], tenths: int) -> ApplyResult:
    applied: list[str] = []
    failed: list[tuple[str, str]] = []
    for name in names:
        try:
            if not hue.turn_off_with_transition(name, tenths):
                failed.append((name, "Lâmpada não encontrada ou desabilitada"))
                continue
        except Exception as e:  # noqa: BLE001 — isolate per-light failures
            logger.warning(f"Erro ao desligar '{name}': {e}")
            failed.append((name, str(e)))
        else:
            applied.append(name)
    return ApplyResult(applied=tuple(applied), failed=tuple(failed))


class LightsOffService:
    """Stop mirror, snapshot (idempotent, fail-open), turn off enabled lights."""

    def __init__(
        self,
        hue: HueLightsOffPort,
        history: LightsOffHistoryPort | None = None,
        *,
        mirror: MirrorStopPort | None = None,
        last_applied: LastAppliedClearPort | None = None,
    ) -> None:
        self._hue = hue
        self._history = history
        self._mirror = mirror
        self._last_applied = last_applied

    async def turn_off_all(self, *, transition_time: float = 0) -> ApplyResult:
        """Turn off every enabled light; ``transition_time`` in seconds (>= 0).

        Raises:
            LightsOffBridgeError: the bridge could not be read before the loop.
        """
        await self._stop_mirror_fail_open()

        try:
            names = [n for n in self._hue.list_lights() if is_enabled_for_app(n)]
        except Exception as e:  # noqa: BLE001 — mapped to the documented 500
            logger.error(f"Lights off: inventário indisponível: {e}")
            raise LightsOffBridgeError(str(e)) from e
        if not names:
            logger.info("Lights off: nenhuma lâmpada habilitada")
            return ApplyResult(applied=(), failed=())

        try:
            status = await asyncio.to_thread(self._hue.get_lights_status)
        except Exception as e:  # noqa: BLE001 — mapped to the documented 500
            logger.error(f"Lights off: bridge indisponível: {e}")
            raise LightsOffBridgeError(str(e), tuple(names)) from e

        if _any_enabled_light_on(status, set(names)):
            await self._snapshot_fail_open(status)
        else:
            logger.info("Lights off: todas já desligadas; snapshot ignorado")

        tenths = int(transition_time * 10)  # request model enforces >= 0
        result = await asyncio.to_thread(_turn_off_sync, self._hue, names, tenths)
        logger.info(
            f"Lights off: applied={len(result.applied)} failed={len(result.failed)}"
        )
        if result.applied and self._last_applied is not None:
            await self._last_applied.clear(source=SOURCE_LIGHTS_OFF)
        return result

    async def _stop_mirror_fail_open(self) -> None:
        if self._mirror is None:
            return
        try:
            await self._mirror.stop()
        except MirrorNotActiveError:
            return
        except Exception as e:  # noqa: BLE001 — fail-open: still turn off
            logger.warning(f"Lights off: falha ao parar espelhamento: {e}")
        else:
            logger.info("Lights off: espelhamento ativo parado")

    async def _snapshot_fail_open(self, status: list[dict[str, Any]]) -> None:
        if self._history is None:
            return
        try:
            await self._history.snapshot_status(
                status,
                source=LIGHTS_OFF_SOURCE,
                label=LIGHTS_OFF_LABEL,
            )
        except Exception as snap_exc:  # noqa: BLE001 — fail-open: still turn off
            logger.warning(f"Scene snapshot before lights off failed: {snap_exc}")
