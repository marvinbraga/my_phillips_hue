"""Backup import/export routes (ZIP bundle of lights, groups, schedules, JSON)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from marvin_hue.api.dependencies import get_light_registry_service
from marvin_hue.config import settings
from marvin_hue.logging_config import get_logger
from marvin_hue.persistence.group_repository import SqliteGroupRepository
from marvin_hue.persistence.schedule_repository import SqliteScheduleRepository
from marvin_hue.services.backup import (
    BackupService,
    BackupValidationError,
)
from marvin_hue.services.light_registry import LightRegistryService

router = APIRouter(tags=["Backup"])
logger = get_logger("api.backup")

ImportStrategyForm = Literal["merge", "replace"]


class BackupImportResponse(BaseModel):
    """Summary returned after a successful import."""

    strategy: str
    lights: dict[str, int]
    groups: dict[str, int]
    schedules: dict[str, int]
    files_written: list[str] = Field(default_factory=list)


async def get_backup_service(
    light_svc: LightRegistryService = Depends(get_light_registry_service),
) -> AsyncIterator[BackupService]:
    """Yield a BackupService; close short-lived group/schedule connections after."""
    db_path = settings.app_db_path
    group_repo = await SqliteGroupRepository.open(db_path)
    schedule_repo = await SqliteScheduleRepository.open(db_path)

    async def _refresh() -> None:
        await light_svc.refresh_runtime_policy()

    service = BackupService(
        light_svc.repository,
        group_repo=group_repo,
        schedule_repo=schedule_repo,
        setups_path=settings.setups_file,
        positions_path=settings.positions_file,
        physical_locations_path=".res/light_physical_locations.json",
        on_lights_changed=_refresh,
        app_version="2.0.0",
    )
    try:
        yield service
    finally:
        await group_repo.close()
        await schedule_repo.close()


@router.get("/api/backup/export")
async def export_backup(
    svc: BackupService = Depends(get_backup_service),
) -> StreamingResponse:
    """Download a ZIP backup of lights, groups, schedules, and config JSON."""
    try:
        payload = await svc.export_zip()
    except Exception as exc:
        logger.exception("backup_export_failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to build backup archive",
        ) from exc

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"marvin_hue_backup_{stamp}.zip"

    return StreamingResponse(
        iter([payload]),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(payload)),
        },
    )


@router.post(
    "/api/backup/import",
    response_model=BackupImportResponse,
    status_code=status.HTTP_200_OK,
)
async def import_backup(
    file: UploadFile = File(..., description="ZIP backup produced by /api/backup/export"),
    strategy: ImportStrategyForm = Form(default="merge"),
    svc: BackupService = Depends(get_backup_service),
) -> BackupImportResponse:
    """Upload a ZIP backup and merge/replace into the local catalog + JSON files."""
    if strategy not in ("merge", "replace"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="strategy must be 'merge' or 'replace'",
        )

    content_type = (file.content_type or "").lower()
    filename = file.filename or ""
    if content_type and content_type not in (
        "application/zip",
        "application/x-zip-compressed",
        "application/octet-stream",
    ):
        if not filename.lower().endswith(".zip"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file must be a ZIP archive",
            )

    try:
        data = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not read uploaded file",
        ) from exc

    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty backup file",
        )

    try:
        summary = await svc.import_zip(data, strategy=strategy)
    except BackupValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("backup_import_failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to import backup archive",
        ) from exc

    return BackupImportResponse.model_validate(summary)
