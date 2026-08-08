"""Health dashboard routes — JSON aggregation + HTML page."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from marvin_hue.api.dependencies import (
    get_chat_agent,
    get_chat_unavailable_reason,
    get_hue_controller,
    get_screen_mirror,
)
from marvin_hue.api import dependencies as deps
from marvin_hue.chat import HueLightAgent
from marvin_hue.controllers import HueController
from marvin_hue.logging_config import get_logger
from marvin_hue.screen_mirror import ScreenMirror
from marvin_hue.services.health import collect_health
from marvin_hue.services.light_registry import LightRegistryService

router = APIRouter(tags=["Health"])
logger = get_logger("api.health")
templates = Jinja2Templates(directory="web/templates")


def _optional_registry() -> LightRegistryService | None:
    try:
        return deps.get_light_registry_service()
    except RuntimeError:
        return None


@router.get("/api/health")
async def api_health(
    hue: HueController = Depends(get_hue_controller),
    screen_mirror: ScreenMirror = Depends(get_screen_mirror),
    chat_agent: HueLightAgent | None = Depends(get_chat_agent),
):
    """Aggregated health: bridge, lights, mirror, chat, registry, schedules."""
    payload = await collect_health(
        hue=hue,
        screen_mirror=screen_mirror,
        chat_agent=chat_agent,
        chat_reason=get_chat_unavailable_reason(),
        registry=_optional_registry(),
    )
    return payload


@router.get("/health", response_class=HTMLResponse)
async def health_page(request: Request):
    """HTML dashboard that polls GET /api/health."""
    return templates.TemplateResponse(
        request,
        "health.html",
        {"active": "saude"},
    )
