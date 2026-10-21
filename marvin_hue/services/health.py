"""Health aggregation for dashboard and GET /api/health.

Collects bridge connectivity, light reachability, mirror state, chat
availability, and lights-registry stats into a single JSON payload.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

from marvin_hue.audio_mirror import AudioMirror
from marvin_hue.chat import HueLightAgent
from marvin_hue.config import settings
from marvin_hue.controllers import HueController
from marvin_hue.logging_config import get_logger
from marvin_hue.screen_mirror import ScreenMirror
from marvin_hue.services.light_registry import LightRegistryService
from marvin_hue.services.mirror_control import active_mode
from marvin_hue.services.schedule_runner import ScheduleRunner
from marvin_hue.services.schedule_service import ScheduleService

logger = get_logger("services.health")


async def collect_health(
    *,
    hue: HueController,
    screen_mirror: ScreenMirror,
    chat_agent: HueLightAgent | None,
    chat_reason: str | None,
    registry: LightRegistryService | None,
    schedule_runner: ScheduleRunner | None = None,
    schedule_service: ScheduleService | None = None,
    audio_mirror: AudioMirror | None = None,
) -> dict[str, Any]:
    """Build the health snapshot for API and dashboard.

    Bridge and light status use thread offload (sync phue I/O). Registry and
    chat are async/local. Failures degrade to connected=false / zero counts
    rather than raising, so the dashboard always returns 200.
    """
    now = datetime.now(timezone.utc)
    bridge_block = await _bridge_block(hue)
    lights_block = await _lights_block(hue, registry)
    mirror_block = _mirror_block(screen_mirror, audio_mirror)
    chat_block = {
        "available": chat_agent is not None,
        "reason": None if chat_agent is not None else chat_reason,
    }
    registry_block = await _registry_block(registry)
    schedules_block = await _schedules_block(schedule_runner, schedule_service)

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
            disabled_in_app = sum(
                1 for light in registered if not light.enabled_for_app
            )
        except Exception as exc:
            logger.warning(f"Health registry disabled count failed: {exc}")

    return {
        "total": total,
        "unreachable": unreachable,
        "disabled_in_app": disabled_in_app,
    }


_AUDIO_LEVEL_KEYS = ("bass", "mid", "treble", "beat")
_MIRROR_STOPPED: dict[str, Any] = {
    "running": False,
    "mode": None,
    "fps": None,
    "profile": None,
    "audio": None,
}


def _running_block(
    mode: str, status: dict[str, Any], audio: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "running": True,
        "mode": mode,
        "fps": status.get("fps"),
        "profile": status.get("active_profile"),
        "audio": audio,
    }


def _audio_block(
    audio_mirror: AudioMirror | None, screen_mirror: ScreenMirror
) -> dict[str, Any] | None:
    """Block for a running audio mirror, or None (not running / probe failed).

    Own try: an audio error must fall back to the screen path, never mask a
    running screen mirror.
    """
    if audio_mirror is None:
        return None
    try:
        if active_mode(screen_mirror, audio_mirror) != "audio":
            return None
        status = audio_mirror.get_status()
        if not status.get("running"):
            return None
        levels: dict[str, Any] = {
            key: float(status.get(key) or 0.0) for key in _AUDIO_LEVEL_KEYS
        }
        levels["config_name"] = status.get("config_name")
        return _running_block("audio", status, levels)
    except Exception as exc:
        logger.warning(f"Health audio mirror status failed: {exc}")
        return None


def _mirror_block(
    screen_mirror: ScreenMirror, audio_mirror: AudioMirror | None
) -> dict[str, Any]:
    """State of the active mirror (audio wins, like ``unified_status``).

    Keeps the legacy keys (``running``/``fps``/``profile``) and adds ``mode``
    (``"screen"`` | ``"audio"`` | None) plus a compact ``audio`` block.
    ``fps``/``profile`` are only reported while a mirror is running.
    """
    audio = _audio_block(audio_mirror, screen_mirror)
    if audio is not None:
        return audio
    try:
        # Screen keeps the legacy source of truth: its own status payload.
        status = screen_mirror.get_status()
    except Exception as exc:
        logger.warning(f"Health mirror status failed: {exc}")
        return dict(_MIRROR_STOPPED)
    if not status.get("running"):
        return dict(_MIRROR_STOPPED)
    return _running_block("screen", status)


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


def _runner_alive(runner: ScheduleRunner | None) -> bool:
    if runner is None:
        return False
    return bool(runner.is_running)


async def _schedules_block(
    runner: ScheduleRunner | None,
    schedule_service: ScheduleService | None,
) -> dict[str, Any]:
    enabled_count = 0
    if schedule_service is not None:
        try:
            schedules = await schedule_service.list_schedules()
            enabled_count = sum(1 for item in schedules if item.enabled)
        except Exception as exc:
            logger.warning(f"Health schedules count failed: {exc}")

    return {
        "enabled_count": enabled_count,
        "runner_alive": _runner_alive(runner),
    }
