"""Lights registry routes (app catalog CRUD + bridge sync).

Live Hue state remains at GET /api/lights/status (status router).
Static paths (/api/lights, /api/lights/sync) must be declared before /{light_id}.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from marvin_hue.api.dependencies import get_light_registry_service
from marvin_hue.api.models import (
    LightCreateRequest,
    LightResponse,
    LightUpdateRequest,
    LightsSyncResponse,
)
from marvin_hue.domain.lights import (
    LightConflictError,
    LightNotFoundError,
    LightValidationError,
    RegisteredLight,
)
from marvin_hue.logging_config import get_logger
from marvin_hue.services.light_registry import LightRegistryService

router = APIRouter(tags=["Lights Registry"])
logger = get_logger("api.lights")
templates = Jinja2Templates(directory="web/templates")


@router.get("/lights", response_class=HTMLResponse)
async def lights_registry_page(request: Request):
    """Página HTML de cadastro/listagem de lâmpadas (não confunde com /api/lights)."""
    return templates.TemplateResponse(request, "lights.html", {"active": "lampadas"})


def _dt_iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat()


def to_response(light: RegisteredLight) -> LightResponse:
    return LightResponse(
        id=light.id,
        name=light.name,
        nickname=light.nickname,
        room=light.room,
        notes=light.notes,
        bridge_light_id=light.bridge_light_id,
        eye_safety_limit_pct=light.eye_safety_limit_pct,
        enabled_for_app=light.enabled_for_app,
        deleted_at=_dt_iso(light.deleted_at),
        created_at=_dt_iso(light.created_at) or "",
        updated_at=_dt_iso(light.updated_at) or "",
    )


def _http_from_validation(exc: LightValidationError) -> HTTPException:
    if isinstance(exc, LightConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/api/lights", response_model=list[LightResponse])
async def list_registered_lights(
    include_deleted: bool = Query(default=False),
    svc: LightRegistryService = Depends(get_light_registry_service),
):
    lights = await svc.list_lights(include_deleted=include_deleted)
    return [to_response(x) for x in lights]


@router.post(
    "/api/lights",
    response_model=LightResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_registered_light(
    body: LightCreateRequest,
    svc: LightRegistryService = Depends(get_light_registry_service),
):
    try:
        light = await svc.create_light(
            name=body.name,
            nickname=body.nickname,
            room=body.room,
            notes=body.notes,
            bridge_light_id=body.bridge_light_id,
            eye_safety_limit_pct=body.eye_safety_limit_pct,
            enabled_for_app=body.enabled_for_app,
        )
    except LightValidationError as exc:
        raise _http_from_validation(exc) from exc
    return to_response(light)


@router.post("/api/lights/sync", response_model=LightsSyncResponse)
async def sync_lights_from_bridge(
    reactivate_deleted: bool = Query(default=False),
    svc: LightRegistryService = Depends(get_light_registry_service),
):
    """Upsert registry from Hue bridge inventory.

    Soft-deleted rows are not reactivated unless reactivate_deleted=true.
    """
    try:
        result = await svc.refresh_and_sync(reactivate_deleted=reactivate_deleted)
    except LightConflictError as exc:
        # LightConflictError subclasses LightValidationError — must be caught first
        raise HTTPException(
            status_code=409,
            detail="Light name conflict during sync",
        ) from exc
    except LightValidationError as exc:
        # Missing bridge / refresh failure — generic 503, no raw internal strings
        raise HTTPException(
            status_code=503,
            detail="Light registry sync unavailable",
        ) from exc
    except Exception:
        logger.exception("Unexpected error during light registry sync")
        raise HTTPException(
            status_code=500,
            detail="Internal error during light registry sync",
        )
    return LightsSyncResponse(**result)


@router.get("/api/lights/{light_id}", response_model=LightResponse)
async def get_registered_light(
    light_id: str,
    svc: LightRegistryService = Depends(get_light_registry_service),
):
    try:
        light = await svc.get_light(light_id)
    except LightNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return to_response(light)


@router.patch("/api/lights/{light_id}", response_model=LightResponse)
async def update_registered_light(
    light_id: str,
    body: LightUpdateRequest,
    svc: LightRegistryService = Depends(get_light_registry_service),
):
    # Only pass fields explicitly set by client (null clears nullables)
    data = body.model_dump(exclude_unset=True)
    try:
        light = await svc.update_light(light_id, **data)
    except LightNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LightValidationError as exc:
        raise _http_from_validation(exc) from exc
    return to_response(light)


@router.delete("/api/lights/{light_id}", response_model=LightResponse)
async def delete_registered_light(
    light_id: str,
    svc: LightRegistryService = Depends(get_light_registry_service),
):
    try:
        light = await svc.delete_light(light_id)
    except LightNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return to_response(light)
