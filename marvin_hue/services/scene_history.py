"""Scene history: snapshot current Hue state and restore (undo)."""

from __future__ import annotations

import asyncio
from typing import Any, Optional, Protocol

from marvin_hue.colors import Color
from marvin_hue.domain.scene_history import (
    SceneHistoryNotFoundError,
    SceneHistoryValidationError,
    SceneSnapshot,
)
from marvin_hue.logging_config import get_logger
from marvin_hue.persistence.scene_history_repository import SceneHistoryRepository

logger = get_logger("services.scene_history")

# Keep last N snapshots (plan mentioned ~30; product request: 50).
DEFAULT_HISTORY_KEEP = 50


class HueSceneController(Protocol):
    """Minimal Hue port for snapshot/restore."""

    def get_lights_status(self) -> list[dict[str, Any]]: ...

    def turn_on(self, light_name: str) -> bool: ...

    def turn_off(self, light_name: str) -> bool: ...

    def set_light_color(self, light_name: str, color: Color) -> object: ...


class SceneHistoryService:
    """Capture and restore full light scenes via HueController public API."""

    def __init__(
        self,
        repo: SceneHistoryRepository,
        *,
        keep_latest: int = DEFAULT_HISTORY_KEEP,
    ) -> None:
        if keep_latest < 1:
            raise SceneHistoryValidationError("keep_latest must be >= 1")
        self._repo = repo
        self._keep_latest = keep_latest

    async def aclose(self) -> None:
        await self._repo.close()

    async def snapshot(
        self,
        hue: HueSceneController,
        *,
        source: str,
        label: Optional[str] = None,
    ) -> SceneSnapshot:
        """Capture current lights status and store; prune old rows."""

        def _capture() -> list[dict[str, Any]]:
            return list(hue.get_lights_status())

        payload = await asyncio.to_thread(_capture)
        snap = SceneSnapshot(source=source, payload=payload, label=label)
        created = await self._repo.create(snap)
        deleted = await self._repo.prune_keep_latest(self._keep_latest)
        if deleted:
            logger.debug(f"Pruned {deleted} old scene snapshots (keep={self._keep_latest})")
        logger.info(
            f"Scene snapshot id={created.id} source={source!r} "
            f"lights={len(payload)} label={label!r}"
        )
        return created

    async def list_recent(self, limit: int = 10) -> list[SceneSnapshot]:
        return await self._repo.list_recent(limit=limit)

    async def get_latest(self) -> Optional[SceneSnapshot]:
        return await self._repo.get_latest()

    async def restore_last(self, hue: HueSceneController) -> dict[str, Any]:
        """Restore the most recent snapshot onto the bridge."""
        snap = await self._repo.get_latest()
        if snap is None:
            raise SceneHistoryNotFoundError("No scene snapshot available to restore")

        payload = snap.payload

        def _restore() -> list[str]:
            restored: list[str] = []
            for item in payload:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                if not item.get("on"):
                    hue.turn_off(name)
                    restored.append(name)
                    continue
                hue.turn_on(name)
                color = item.get("color") or {}
                if not isinstance(color, dict):
                    color = {}
                bri = int(item.get("brightness") or 0)
                # Color validates 0-255 RGB and 0-254 brightness
                r = max(0, min(255, int(color.get("r", 0))))
                g = max(0, min(255, int(color.get("g", 0))))
                b = max(0, min(255, int(color.get("b", 0))))
                bri_clamped = max(0, min(254, bri))
                try:
                    hue.set_light_color(name, Color(r, g, b, bri_clamped))
                except (ValueError, TypeError) as exc:
                    logger.warning(f"restore color failed for {name!r}: {exc}")
                restored.append(name)
            return restored

        restored_names = await asyncio.to_thread(_restore)
        logger.info(
            f"Restored scene snapshot id={snap.id} source={snap.source!r} "
            f"lights={len(restored_names)}"
        )
        return {
            "snapshot_id": snap.id,
            "source": snap.source,
            "label": snap.label,
            "created_at": snap.created_at.isoformat(),
            "restored_lights": restored_names,
            "restored_count": len(restored_names),
        }
