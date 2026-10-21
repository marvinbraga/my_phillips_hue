"""Health dashboard routes — JSON aggregation + HTML page."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from marvin_hue.api import dependencies as deps
from marvin_hue.api.dependencies import (
    get_chat_agent,
    get_chat_unavailable_reason,
    get_hue_controller,
    get_schedule_runner,
    get_screen_mirror,
)
from marvin_hue.chat import HueLightAgent
from marvin_hue.controllers import HueController
from marvin_hue.logging_config import get_logger
from marvin_hue.screen_mirror import ScreenMirror
from marvin_hue.services.health import collect_health
from marvin_hue.services.schedule_runner import ScheduleRunner

router = APIRouter(tags=["Health"])
logger = get_logger("api.health")
templates = Jinja2Templates(directory="web/templates")


T = TypeVar("T")


def _optional(getter: Callable[[], T]) -> T | None:
    """Optional lifespan service: None instead of RuntimeError when not wired."""
    try:
        return getter()
    except RuntimeError:
        return None


@router.get("/api/health")
async def api_health(
    hue: HueController = Depends(get_hue_controller),
    screen_mirror: ScreenMirror = Depends(get_screen_mirror),
    chat_agent: HueLightAgent | None = Depends(get_chat_agent),
    schedule_runner: ScheduleRunner | None = Depends(get_schedule_runner),
) -> dict[str, Any]:
    """Aggregated health: bridge, lights, mirror, chat, registry, schedules."""
    payload = await collect_health(
        hue=hue,
        screen_mirror=screen_mirror,
        chat_agent=chat_agent,
        chat_reason=get_chat_unavailable_reason(),
        registry=_optional(deps.get_light_registry_service),
        schedule_runner=schedule_runner,
        schedule_service=_optional(deps.get_schedule_service),
        audio_mirror=_optional(deps.get_audio_mirror),
    )
    return payload


@router.get("/health", response_class=HTMLResponse)
async def health_page(request: Request) -> HTMLResponse:
    """HTML dashboard that polls GET /api/health."""
    return templates.TemplateResponse(
        request,
        "health.html",
        {"active": "saude"},
    )
