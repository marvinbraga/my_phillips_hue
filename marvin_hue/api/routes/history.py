"""Scene history / undo API routes."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from marvin_hue.api.dependencies import (
    get_hue_controller,
    get_scene_history_service,
)
from marvin_hue.api.models import (
    HistorySnapshotRequest,
    HistoryUndoResponse,
    SceneSnapshotResponse,
)
from marvin_hue.controllers import HueController
from marvin_hue.domain.scene_history import (
    SceneHistoryNotFoundError,
    SceneHistoryValidationError,
    SceneSnapshot,
)
from marvin_hue.logging_config import get_logger
from marvin_hue.services.scene_history import SceneHistoryService

router = APIRouter(tags=["History"])
logger = get_logger("api.history")


def _dt_iso(value: Optional[datetime]) -> str:
    if value is None:
        return ""
    return value.isoformat()


def to_meta(snap: SceneSnapshot) -> SceneSnapshotResponse:
    return SceneSnapshotResponse(
        id=snap.id,
        label=snap.label,
        source=snap.source,
        created_at=_dt_iso(snap.created_at),
        light_count=len(snap.payload) if snap.payload else 0,
    )


@router.get("/api/history", response_model=list[SceneSnapshotResponse])
async def list_history(
    limit: int = Query(default=10, ge=1, le=100),
    svc: SceneHistoryService = Depends(get_scene_history_service),
):
    snaps = await svc.list_recent(limit=limit)
    return [to_meta(s) for s in snaps]


@router.post("/api/history/snapshot", response_model=SceneSnapshotResponse)
async def create_snapshot(
    body: HistorySnapshotRequest,
    svc: SceneHistoryService = Depends(get_scene_history_service),
    hue: HueController = Depends(get_hue_controller),
):
    source = (body.source or "manual").strip() or "manual"
    try:
        snap = await svc.snapshot(hue, source=source, label=body.label)
    except SceneHistoryValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(f"snapshot failed: {exc}")
        raise HTTPException(
            status_code=500, detail="Erro ao capturar snapshot"
        ) from exc
    return to_meta(snap)


@router.post("/api/history/undo", response_model=HistoryUndoResponse)
async def undo_last(
    svc: SceneHistoryService = Depends(get_scene_history_service),
    hue: HueController = Depends(get_hue_controller),
):
    try:
        result = await svc.restore_last(hue)
    except SceneHistoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(f"undo failed: {exc}")
        raise HTTPException(
            status_code=500, detail="Erro ao restaurar cena"
        ) from exc
    return HistoryUndoResponse(**result)
