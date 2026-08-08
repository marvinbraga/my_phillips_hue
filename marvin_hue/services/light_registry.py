"""Light registry application service: CRUD + bridge sync.

SQLite owns app-side catalog metadata. Philips Hue bridge remains the
source of truth for physical device presence; this service upserts rows
from bridge inventory without hard-deleting Hue lights.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional, Protocol
from uuid import uuid4

from marvin_hue.domain.lights import (
    LightConflictError,
    LightValidationError,
    RegisteredLight,
)
from marvin_hue.persistence.light_repository import LightRegistryRepository

# Sentinel for PATCH: missing key = leave unchanged; explicit None = clear nullable.
_UNSET: object = object()


class BridgeLightInventory(Protocol):
    """Minimal port for reading lights from HueController."""

    def list_bridge_lights(self) -> list[dict[str, Any]]:
        """Return list of {name, bridge_light_id?} from the physical bridge."""
        ...


class LightRegistryService:
    """CRUD and bridge-sync use cases over a LightRegistryRepository."""

    def __init__(
        self,
        repo: LightRegistryRepository,
        bridge: Optional[BridgeLightInventory] = None,
    ) -> None:
        self._repo = repo
        self._bridge = bridge

    async def aclose(self) -> None:
        await self._repo.close()

    async def list_lights(
        self, *, include_deleted: bool = False
    ) -> list[RegisteredLight]:
        return await self._repo.list_all(include_deleted=include_deleted)

    async def get_light(
        self, light_id: str, *, include_deleted: bool = False
    ) -> RegisteredLight:
        return await self._repo.get_by_id(light_id, include_deleted=include_deleted)

    async def create_light(
        self,
        *,
        name: str,
        nickname: Optional[str] = None,
        room: Optional[str] = None,
        notes: Optional[str] = None,
        bridge_light_id: Optional[str] = None,
        eye_safety_limit_pct: Optional[int] = None,
        enabled_for_app: bool = True,
    ) -> RegisteredLight:
        existing = await self._repo.get_by_name(name.strip(), include_deleted=False)
        if existing is not None:
            raise LightConflictError(
                f"Active light with name {name!r} already exists"
            )

        now = datetime.now(timezone.utc)
        light = RegisteredLight(
            id=str(uuid4()),
            name=name,
            nickname=nickname,
            room=room,
            notes=notes,
            bridge_light_id=bridge_light_id,
            eye_safety_limit_pct=eye_safety_limit_pct,
            enabled_for_app=enabled_for_app,
            created_at=now,
            updated_at=now,
        )
        try:
            return await self._repo.create(light)
        except LightValidationError as exc:
            # Repo maps IntegrityError → LightValidationError; promote conflicts.
            msg = str(exc).lower()
            if "already exists" in msg or "unique" in msg:
                raise LightConflictError(str(exc)) from exc
            raise

    async def update_light(
        self,
        light_id: str,
        *,
        name: object = _UNSET,
        nickname: object = _UNSET,
        room: object = _UNSET,
        notes: object = _UNSET,
        bridge_light_id: object = _UNSET,
        eye_safety_limit_pct: object = _UNSET,
        enabled_for_app: object = _UNSET,
    ) -> RegisteredLight:
        light = await self._repo.get_by_id(light_id, include_deleted=False)

        if name is not _UNSET:
            if name is None:
                raise LightValidationError("name must be non-empty")
            new_name = str(name).strip()
            if not new_name:
                raise LightValidationError("name must be non-empty")
            other = await self._repo.get_by_name(new_name, include_deleted=False)
            if other is not None and other.id != light.id:
                raise LightConflictError(
                    f"Active light with name {new_name!r} already exists"
                )
            light.name = new_name

        if nickname is not _UNSET:
            light.nickname = nickname  # type: ignore[assignment]
        if room is not _UNSET:
            light.room = room  # type: ignore[assignment]
        if notes is not _UNSET:
            light.notes = notes  # type: ignore[assignment]
        if bridge_light_id is not _UNSET:
            light.bridge_light_id = (
                str(bridge_light_id).strip() or None
                if bridge_light_id is not None
                else None
            )
        if eye_safety_limit_pct is not _UNSET:
            light.eye_safety_limit_pct = eye_safety_limit_pct  # type: ignore[assignment]
        if enabled_for_app is not _UNSET:
            if enabled_for_app is None:
                raise LightValidationError("enabled_for_app cannot be null")
            light.enabled_for_app = bool(enabled_for_app)

        light = RegisteredLight(
            id=light.id,
            name=light.name,
            nickname=light.nickname,
            room=light.room,
            notes=light.notes,
            bridge_light_id=light.bridge_light_id,
            eye_safety_limit_pct=light.eye_safety_limit_pct,
            enabled_for_app=light.enabled_for_app,
            deleted_at=light.deleted_at,
            created_at=light.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        try:
            return await self._repo.update(light)
        except LightValidationError as exc:
            msg = str(exc).lower()
            if "already exists" in msg or "unique" in msg:
                raise LightConflictError(str(exc)) from exc
            raise

    async def delete_light(self, light_id: str) -> RegisteredLight:
        """Soft-delete catalog entry only. Never deletes on Hue bridge."""
        return await self._repo.soft_delete(light_id)

    async def sync_from_bridge(
        self, *, reactivate_deleted: bool = False
    ) -> dict[str, int]:
        """Upsert catalog rows from bridge inventory.

        Identity: bridge_light_id first (active), then name (active).
        Soft-deleted rows are not reactivated unless reactivate_deleted=True.
        Soft-deleted matches without reactivate are skipped (no create).

        Returns counts: created, updated, unchanged, skipped_deleted, total_bridge.
        """
        if self._bridge is None:
            raise LightValidationError("Bridge inventory is not configured")

        inventory = self._bridge.list_bridge_lights()
        created = updated = unchanged = skipped_deleted = 0

        for item in inventory:
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            raw_bid = item.get("bridge_light_id")
            bridge_id_str = str(raw_bid).strip() if raw_bid is not None else None
            if bridge_id_str == "":
                bridge_id_str = None

            active: Optional[RegisteredLight] = None
            if bridge_id_str is not None:
                active = await self._repo.get_by_bridge_light_id(
                    bridge_id_str, include_deleted=False
                )
            if active is None:
                active = await self._repo.get_by_name(name, include_deleted=False)

            if active is not None:
                changed = False
                if active.name != name:
                    active.name = name
                    changed = True
                if (
                    bridge_id_str is not None
                    and active.bridge_light_id != bridge_id_str
                ):
                    active.bridge_light_id = bridge_id_str
                    changed = True
                if changed:
                    active.updated_at = datetime.now(timezone.utc)
                    try:
                        await self._repo.update(active)
                    except LightValidationError as exc:
                        msg = str(exc).lower()
                        if "already exists" in msg or "unique" in msg:
                            raise LightConflictError(str(exc)) from exc
                        raise
                    updated += 1
                else:
                    unchanged += 1
                continue

            # No active match: consider soft-deleted
            deleted: Optional[RegisteredLight] = None
            if bridge_id_str is not None:
                candidate = await self._repo.get_by_bridge_light_id(
                    bridge_id_str, include_deleted=True
                )
                if candidate is not None and candidate.deleted_at is not None:
                    deleted = candidate
            if deleted is None:
                candidate = await self._repo.get_by_name(name, include_deleted=True)
                if candidate is not None and candidate.deleted_at is not None:
                    deleted = candidate

            if deleted is not None:
                if not reactivate_deleted:
                    skipped_deleted += 1
                    continue
                deleted.deleted_at = None
                deleted.name = name
                if bridge_id_str is not None:
                    deleted.bridge_light_id = bridge_id_str
                deleted.updated_at = datetime.now(timezone.utc)
                try:
                    await self._repo.update(deleted)
                except LightValidationError as exc:
                    msg = str(exc).lower()
                    if "already exists" in msg or "unique" in msg:
                        raise LightConflictError(str(exc)) from exc
                    raise
                updated += 1
                continue

            # Unknown: create
            await self.create_light(name=name, bridge_light_id=bridge_id_str)
            created += 1

        return {
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
            "skipped_deleted": skipped_deleted,
            "total_bridge": len(inventory),
        }

    async def refresh_and_sync(
        self, *, reactivate_deleted: bool = False
    ) -> dict[str, int]:
        """Refresh bridge topology if available, then sync.

        Raises LightValidationError if bridge missing.
        Propagates refresh failures as LightValidationError with generic message
        (no exception string leakage for API layer).
        """
        if self._bridge is None:
            raise LightValidationError("Bridge inventory is not configured")
        refresh = getattr(self._bridge, "refresh_lights", None)
        if callable(refresh):
            try:
                # refresh_lights is sync network I/O — keep the event loop free
                await asyncio.to_thread(refresh)
            except Exception as exc:
                raise LightValidationError(
                    "Unable to refresh lights from bridge"
                ) from exc
        return await self.sync_from_bridge(reactivate_deleted=reactivate_deleted)
