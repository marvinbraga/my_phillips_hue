"""Light groups routes: CRUD, power, apply config, HTML page."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from marvin_hue.api.dependencies import (
    get_group_service,
    get_hue_controller,
    get_manager,
    get_scene_history_service,
)
from marvin_hue.api.models import (
    GroupApplyRequest,
    GroupCreateRequest,
    GroupPowerRequest,
    GroupResponse,
    GroupUpdateRequest,
)
from marvin_hue.basics import LightSetupsManager
from marvin_hue.controllers import HueController
from marvin_hue.domain.groups import (
    GroupConflictError,
    GroupNotFoundError,
    GroupValidationError,
    LightGroup,
)
from marvin_hue.logging_config import get_logger
from marvin_hue.services.group_service import GroupService
from marvin_hue.services.scene_history import SceneHistoryService

router = APIRouter(tags=["Groups"])
logger = get_logger("api.groups")
templates = Jinja2Templates(directory="web/templates")


@router.get("/groups", response_class=HTMLResponse)
async def groups_page(request: Request):
    """Página HTML de grupos de lâmpadas."""
    return templates.TemplateResponse(request, "groups.html")


def _dt_iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat()


def to_response(group: LightGroup) -> GroupResponse:
    return GroupResponse(
        id=group.id,
        name=group.name,
        room=group.room,
        notes=group.notes,
        light_ids=list(group.light_ids),
        deleted_at=_dt_iso(group.deleted_at),
        created_at=_dt_iso(group.created_at) or "",
        updated_at=_dt_iso(group.updated_at) or "",
    )


def _http_from_validation(exc: GroupValidationError) -> HTTPException:
    if isinstance(exc, GroupConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/api/groups", response_model=list[GroupResponse])
async def list_groups(
    include_deleted: bool = Query(default=False),
    svc: GroupService = Depends(get_group_service),
):
    groups = await svc.list_groups(include_deleted=include_deleted)
    return [to_response(g) for g in groups]


@router.post(
    "/api/groups",
    response_model=GroupResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_group(
    body: GroupCreateRequest,
    svc: GroupService = Depends(get_group_service),
):
    try:
        group = await svc.create_group(
            name=body.name,
            room=body.room,
            notes=body.notes,
            light_ids=body.light_ids,
        )
    except GroupValidationError as exc:
        raise _http_from_validation(exc) from exc
    return to_response(group)


@router.get("/api/groups/{group_id}", response_model=GroupResponse)
async def get_group(
    group_id: str,
    svc: GroupService = Depends(get_group_service),
):
    try:
        group = await svc.get_group(group_id)
    except GroupNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return to_response(group)


@router.patch("/api/groups/{group_id}", response_model=GroupResponse)
async def update_group(
    group_id: str,
    body: GroupUpdateRequest,
    svc: GroupService = Depends(get_group_service),
):
    data = body.model_dump(exclude_unset=True)
    try:
        group = await svc.update_group(group_id, **data)
    except GroupNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GroupValidationError as exc:
        raise _http_from_validation(exc) from exc
    return to_response(group)


@router.delete("/api/groups/{group_id}", response_model=GroupResponse)
async def delete_group(
    group_id: str,
    svc: GroupService = Depends(get_group_service),
):
    try:
        group = await svc.delete_group(group_id)
    except GroupNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return to_response(group)


@router.post("/api/groups/{group_id}/power")
async def group_power(
    group_id: str,
    body: GroupPowerRequest,
    svc: GroupService = Depends(get_group_service),
    hue: HueController = Depends(get_hue_controller),
    history: SceneHistoryService = Depends(get_scene_history_service),
):
    try:
        await history.snapshot(
            hue,
            source="group_apply",
            label=f"before group power {'on' if body.on else 'off'}",
        )
        result = await svc.set_power(group_id, on=body.on, hue=hue)
    except GroupNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(f"group power failed: {exc}")
        raise HTTPException(
            status_code=500, detail="Erro ao alterar energia do grupo"
        ) from exc
    return {"message": "ok", **result}


@router.post("/api/groups/{group_id}/apply")
async def group_apply(
    group_id: str,
    body: GroupApplyRequest,
    svc: GroupService = Depends(get_group_service),
    hue: HueController = Depends(get_hue_controller),
    manager: LightSetupsManager = Depends(get_manager),
    history: SceneHistoryService = Depends(get_scene_history_service),
):
    config = manager.get_config(body.config_name)
    if config is None:
        raise HTTPException(
            status_code=404,
            detail=f"Configuração '{body.config_name}' não encontrada",
        )
    try:
        await history.snapshot(
            hue,
            source="group_apply",
            label=f"before apply {body.config_name}",
        )
        result = await svc.apply_config(
            group_id,
            config,
            hue,
            transition_time_secs=body.transition_time_secs,
        )
    except GroupNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(f"group apply failed: {exc}")
        raise HTTPException(
            status_code=500, detail="Erro ao aplicar configuração no grupo"
        ) from exc
    return {"message": "ok", **result}
