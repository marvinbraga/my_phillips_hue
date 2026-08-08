"""Schedules CRUD + HTML page + manual run."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from marvin_hue.api.dependencies import get_schedule_service
from marvin_hue.api.models import (
    ScheduleCreateRequest,
    ScheduleResponse,
    ScheduleUpdateRequest,
)
from marvin_hue.domain.schedules import (
    Schedule,
    ScheduleNotFoundError,
    ScheduleValidationError,
)
from marvin_hue.logging_config import get_logger
from marvin_hue.services.schedule_service import ScheduleService

router = APIRouter(tags=["Schedules"])
logger = get_logger("api.schedules")
templates = Jinja2Templates(directory="web/templates")


@router.get("/schedules", response_class=HTMLResponse)
async def schedules_page(request: Request):
    """Página HTML de agendamentos."""
    return templates.TemplateResponse(request, "schedules.html")


def _dt_iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat()


def to_response(schedule: Schedule) -> ScheduleResponse:
    return ScheduleResponse(
        id=schedule.id,
        name=schedule.name,
        enabled=schedule.enabled,
        time_hhmm=schedule.time_hhmm,
        days_of_week=schedule.days_of_week,
        action_type=schedule.action_type,
        action_payload=dict(schedule.action_payload or {}),
        last_run_at=_dt_iso(schedule.last_run_at),
        created_at=_dt_iso(schedule.created_at) or "",
        updated_at=_dt_iso(schedule.updated_at) or "",
    )


@router.get("/api/schedules", response_model=list[ScheduleResponse])
async def list_schedules(svc: ScheduleService = Depends(get_schedule_service)):
    items = await svc.list_schedules()
    return [to_response(s) for s in items]


@router.post(
    "/api/schedules",
    response_model=ScheduleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_schedule(
    body: ScheduleCreateRequest,
    svc: ScheduleService = Depends(get_schedule_service),
):
    try:
        schedule = await svc.create_schedule(
            name=body.name,
            time_hhmm=body.time_hhmm,
            action_type=body.action_type,
            enabled=body.enabled,
            days_of_week=body.days_of_week,
            action_payload=body.action_payload,
        )
    except ScheduleValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return to_response(schedule)


@router.get("/api/schedules/{schedule_id}", response_model=ScheduleResponse)
async def get_schedule(
    schedule_id: str,
    svc: ScheduleService = Depends(get_schedule_service),
):
    try:
        schedule = await svc.get_schedule(schedule_id)
    except ScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return to_response(schedule)


@router.patch("/api/schedules/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
    schedule_id: str,
    body: ScheduleUpdateRequest,
    svc: ScheduleService = Depends(get_schedule_service),
):
    data = body.model_dump(exclude_unset=True)
    try:
        schedule = await svc.update_schedule(schedule_id, **data)
    except ScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ScheduleValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return to_response(schedule)


@router.delete("/api/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    schedule_id: str,
    svc: ScheduleService = Depends(get_schedule_service),
):
    try:
        await svc.delete_schedule(schedule_id)
    except ScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/schedules/{schedule_id}/run")
async def run_schedule_now(
    schedule_id: str,
    svc: ScheduleService = Depends(get_schedule_service),
) -> dict[str, Any]:
    try:
        result = await svc.run_now(schedule_id)
    except ScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ScheduleValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(f"manual schedule run failed: {exc}")
        raise HTTPException(
            status_code=500, detail="Erro ao executar agendamento"
        ) from exc
    return result
