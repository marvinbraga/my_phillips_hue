"""Last applied scene: record on apply, clear when the lights leave the scene.

The record is a best-effort UI marker (the Controle badge). Recording or
clearing never breaks the action that triggered it: ``LastAppliedSceneService``
logs and swallows its own errors, so callers just ``await svc.record(...)``.

Ports, the lazy provider type and every ``source`` constant live here so the
callers (apply, lights off, undo, schedules, mirror, chat) share one owner.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol

from marvin_hue.basics import LightConfig
from marvin_hue.domain.last_applied_scene import LastAppliedScene
from marvin_hue.logging_config import get_logger
from marvin_hue.persistence.last_applied_repository import LastAppliedSceneRepository

logger = get_logger("services.last_applied_scene")

# Recorded by apply (who applied the scene)
SOURCE_APPLY = "apply"
SOURCE_GROUP = "group"
SOURCE_SCHEDULE = "schedule"
SOURCE_CHAT = "chat"
# Clear reasons (who took the lights out of the scene)
SOURCE_LIGHTS_OFF = "lights_off"
SOURCE_UNDO = "undo"
SOURCE_SCHEDULE_OFF = "schedule_off"
SOURCE_MIRROR = "mirror"


class SceneLookup(Protocol):
    """Port: resolve a named LightConfig (LightSetupsManager structurally)."""

    def get_config(self, name: str) -> LightConfig | None: ...


class LastAppliedRecorderPort(Protocol):
    """Port: record the last applied scene (never raises)."""

    async def record(self, name: str, *, source: str) -> None: ...


class LastAppliedClearPort(Protocol):
    """Port: forget the last applied scene (never raises)."""

    async def clear(self, *, source: str) -> None: ...


class LastAppliedPort(LastAppliedRecorderPort, LastAppliedClearPort, Protocol):
    """Record + clear (LastAppliedSceneService structurally)."""


LastAppliedProvider = Callable[[], LastAppliedPort | None]


def resolve_last_applied(
    provider: LastAppliedProvider | None,
) -> LastAppliedPort | None:
    """Call a lazy provider; None (fail-open) when absent or broken."""
    if provider is None:
        return None
    try:
        return provider()
    except Exception as exc:  # noqa: BLE001 — fail-open: act without the marker
        logger.warning(f"Last applied scene service unavailable: {exc}")
        return None


async def clear_after_undo(
    service: LastAppliedClearPort | None, result: Mapping[str, Any]
) -> None:
    """Clear once an undo restored at least one light (shared by HTTP and chat)."""
    if service is None:
        return
    if int(result.get("restored_count") or 0) <= 0:
        return
    await service.clear(source=SOURCE_UNDO)


class LastAppliedSceneService:
    """Última cena aplicada (SQLite do app, linha única).

    ``manager_lookup`` é chamado a cada leitura (nunca capturado), para
    acompanhar recargas/trocas do manager (ex.: import de backup).
    """

    def __init__(
        self,
        repo: LastAppliedSceneRepository,
        manager_lookup: Callable[[], SceneLookup],
    ) -> None:
        self._repo = repo
        self._manager_lookup = manager_lookup

    async def aclose(self) -> None:
        await self._repo.close()

    async def get(self) -> LastAppliedScene | None:
        """The current scene, or None when never set, cleared, or orphaned.

        Orphans (scene renamed/removed from setups.json) stay in the table and
        come back if the scene reappears.
        """
        scene = await self._repo.get()
        if scene is None or scene.config_name is None:
            return None
        if self._manager_lookup().get_config(scene.config_name) is None:
            return None
        return scene

    async def record(self, name: str, *, source: str) -> None:
        """Best-effort: errors are logged, never raised."""
        try:
            await self._repo.record(name, source)
        except Exception as exc:  # noqa: BLE001 — UI marker only
            logger.warning(f"Recording last applied scene {name!r} failed: {exc}")
            return
        logger.info("last_applied_recorded name={!r} source={!r}", name, source)

    async def clear(self, *, source: str) -> None:
        """Best-effort: errors are logged, never raised."""
        try:
            await self._repo.clear(source)
        except Exception as exc:  # noqa: BLE001 — UI marker only
            logger.warning(f"Clearing last applied scene ({source}) failed: {exc}")
            return
        logger.info("last_applied_cleared source={!r}", source)
