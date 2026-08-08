"""Health aggregation for dashboard and GET /api/health.

Collects bridge connectivity, light reachability, mirror state, chat
availability, and lights-registry stats into a single JSON payload.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

from marvin_hue.chat import HueLightAgent
from marvin_hue.config import settings
from marvin_hue.controllers import HueController
from marvin_hue.logging_config import get_logger
from marvin_hue.screen_mirror import ScreenMirror
from marvin_hue.services.light_registry import LightRegistryService

logger = get_logger("services.health")


async def collect_health(
    *,
    hue: HueController,
    screen_mirror: ScreenMirror,
    chat_agent: HueLightAgent | None,
    chat_reason: str | None,
    registry: LightRegistryService | None,
) -> dict[str, Any]:
    """Build the health snapshot for API and dashboard.

    Bridge and light status use thread offload (sync phue I/O). Registry and
    chat are async/local. Failures degrade to connected=false / zero counts
    rather than raising, so the dashboard always returns 200.
    """
    now = datetime.now(timezone.utc)
    bridge_block = await _bridge_block(hue)
    lights_block = await _lights_block(hue, registry)
    mirror_block = _mirror_block(screen_mirror)
    chat_block = {
        "available": chat_agent is not None,
        "reason": None if chat_agent is not None else chat_reason,
    }
    registry_block = await _registry_block(registry)
    schedules_block = _schedules_block()

    return {
        "bridge": bridge_block,
        "lights": lights_block,
        "mirror": mirror_block,
        "chat": chat_block,
        "registry": registry_block,
        "schedules": schedules_block,
        "timestamp": now.isoformat(),
    }


async def _bridge_block(hue: HueController) -> dict[str, Any]:
    try:
        lights = await asyncio.to_thread(hue.bridge.get_light_objects)
        light_count = len(lights) if lights else 0
        return {
            "connected": True,
            "bridge_ip": getattr(hue.bridge, "ip", settings.bridge_ip),
            "light_count": light_count,
        }
    except Exception as exc:
        logger.warning(f"Health bridge probe failed: {exc}")
        return {
            "connected": False,
            "bridge_ip": settings.bridge_ip,
            "light_count": 0,
            "error": str(exc),
        }


async def _lights_block(
    hue: HueController,
    registry: LightRegistryService | None,
) -> dict[str, Any]:
    total = 0
    unreachable = 0
    try:
        status_rows = await asyncio.to_thread(hue.get_lights_status)
        total = len(status_rows)
        unreachable = sum(1 for row in status_rows if not row.get("reachable", True))
    except Exception as exc:
        logger.warning(f"Health lights status failed: {exc}")

    disabled_in_app = 0
    if registry is not None:
        try:
            registered = await registry.list_lights(include_deleted=False)
            disabled_in_app = sum(1 for light in registered if not light.enabled_for_app)
        except Exception as exc:
            logger.warning(f"Health registry disabled count failed: {exc}")

    return {
        "total": total,
        "unreachable": unreachable,
        "disabled_in_app": disabled_in_app,
    }


def _mirror_block(screen_mirror: ScreenMirror) -> dict[str, Any]:
    try:
        status = screen_mirror.get_status()
        return {
            "running": bool(status.get("running", False)),
            "fps": status.get("fps"),
            "profile": status.get("profile"),  # null until mirror profiles land
        }
    except Exception as exc:
        logger.warning(f"Health mirror status failed: {exc}")
        return {"running": False, "fps": None, "profile": None}


async def _registry_block(
    registry: LightRegistryService | None,
) -> dict[str, Any]:
    count = 0
    last_sync_at: Optional[str] = None
    if registry is not None:
        try:
            lights = await registry.list_lights(include_deleted=False)
            count = len(lights)
        except Exception as exc:
            logger.warning(f"Health registry count failed: {exc}")
        raw = getattr(registry, "last_sync_at", None)
        if isinstance(raw, datetime):
            last_sync_at = raw.isoformat()
        elif isinstance(raw, str):
            last_sync_at = raw

    return {
        "count": count,
        "db_path": settings.app_db_path,
        "last_sync_at": last_sync_at,
    }


def _schedules_block() -> dict[str, Any]:
    """Placeholder until schedule runner is wired into lifespan."""
    return {
        "enabled_count": 0,
        "runner_alive": False,
    }
