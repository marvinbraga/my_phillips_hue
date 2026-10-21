"""Backup import/export routes (ZIP bundle of lights, groups, schedules, JSON)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from marvin_hue.api.dependencies import get_backup_service, get_manager
from marvin_hue.config import settings  # noqa: F401  # tests patch backup.settings
from marvin_hue.logging_config import get_logger
from marvin_hue.services.backup import BackupService, BackupValidationError

router = APIRouter(tags=["Backup"])
logger = get_logger("api.backup")

ImportStrategyForm = Literal["merge", "replace"]


class BackupImportResponse(BaseModel):
    """Summary returned after a successful import."""

    strategy: str
    lights: dict[str, int]
    groups: dict[str, int]
    schedules: dict[str, int]
    favorites: dict[str, int | bool] | None = Field(
        default=None,
        description=(
            "Scene favorites summary: {added, removed, total} computed from the "
            "before/after sets, plus skipped=true when the bundle has no "
            "favorites.json member (older export) or no favorites repo is wired."
        ),
    )
    files_written: list[str] = Field(default_factory=list)


def _reload_setups_manager() -> None:
    """Keep in-memory setups in sync with disk after import."""
    try:
        get_manager().load().update()
    except (RuntimeError, FileNotFoundError, OSError) as exc:
        logger.warning(f"setups_manager_reload_skipped error={exc}")


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
    file: UploadFile = File(
        ..., description="ZIP backup produced by /api/backup/export"
    ),
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
    except BackupValidationError:
        raise
    except Exception as exc:
        logger.exception("backup_import_failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to import backup archive",
        ) from exc

    _reload_setups_manager()
    return BackupImportResponse.model_validate(summary)
