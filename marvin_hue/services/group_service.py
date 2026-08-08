"""Light group application service: CRUD + power/config apply to members."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional, Protocol
from uuid import uuid4

from marvin_hue.basics import LightConfig
from marvin_hue.domain.groups import (
    GroupConflictError,
    GroupNotFoundError,
    GroupValidationError,
    LightGroup,
)
from marvin_hue.logging_config import get_logger
from marvin_hue.persistence.group_repository import GroupRepository

logger = get_logger("services.group")

_UNSET: object = object()


class HueGroupController(Protocol):
    """Minimal Hue port used by group apply/power."""

    def turn_on(self, light_name: str) -> bool: ...

    def turn_off(self, light_name: str) -> bool: ...

    def apply_light_config(
        self, light_config: LightConfig, transition_time_secs: float = 0
    ) -> object: ...


class GroupService:
    """CRUD and apply use cases over GroupRepository."""

    def __init__(self, repo: GroupRepository) -> None:
        self._repo = repo

    async def aclose(self) -> None:
        await self._repo.close()

    async def list_groups(self, *, include_deleted: bool = False) -> list[LightGroup]:
        return await self._repo.list_all(include_deleted=include_deleted)

    async def get_group(
        self, group_id: str, *, include_deleted: bool = False
    ) -> LightGroup:
        return await self._repo.get_by_id(group_id, include_deleted=include_deleted)

    async def create_group(
        self,
        *,
        name: str,
        room: Optional[str] = None,
        notes: Optional[str] = None,
        light_ids: Optional[list[str]] = None,
    ) -> LightGroup:
        now = datetime.now(timezone.utc)
        group = LightGroup(
            id=str(uuid4()),
            name=name,
            room=room,
            notes=notes,
            light_ids=list(light_ids or []),
            created_at=now,
            updated_at=now,
        )
        try:
            return await self._repo.create(group)
        except GroupValidationError as exc:
            msg = str(exc).lower()
            if "already exists" in msg or "unique" in msg:
                raise GroupConflictError(str(exc)) from exc
            raise

    async def update_group(
        self,
        group_id: str,
        *,
        name: object = _UNSET,
        room: object = _UNSET,
        notes: object = _UNSET,
        light_ids: object = _UNSET,
    ) -> LightGroup:
        group = await self._repo.get_by_id(group_id, include_deleted=False)

        if name is not _UNSET:
            if name is None:
                raise GroupValidationError("name must be non-empty")
            new_name = str(name).strip()
            if not new_name:
                raise GroupValidationError("name must be non-empty")
            group.name = new_name

        if room is not _UNSET:
            group.room = room  # type: ignore[assignment]
        if notes is not _UNSET:
            group.notes = notes  # type: ignore[assignment]
        if light_ids is not _UNSET:
            if light_ids is None:
                group.light_ids = []
            else:
                group.light_ids = [str(x) for x in light_ids]  # type: ignore[arg-type]

        # Re-validate via dataclass
        group = LightGroup(
            id=group.id,
            name=group.name,
            room=group.room,
            notes=group.notes,
            light_ids=list(group.light_ids),
            deleted_at=group.deleted_at,
            created_at=group.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        try:
            return await self._repo.update(group)
        except GroupValidationError as exc:
            msg = str(exc).lower()
            if "already exists" in msg or "unique" in msg:
                raise GroupConflictError(str(exc)) from exc
            raise

    async def delete_group(self, group_id: str) -> LightGroup:
        return await self._repo.soft_delete(group_id)

    async def set_members(self, group_id: str, light_ids: list[str]) -> LightGroup:
        try:
            return await self._repo.set_members(group_id, light_ids)
        except GroupValidationError:
            raise
        except GroupNotFoundError:
            raise

    async def member_names(self, group_id: str) -> list[str]:
        return await self._repo.list_member_light_names(group_id)

    async def set_power(
        self,
        group_id: str,
        on: bool,
        hue: HueGroupController,
    ) -> dict[str, object]:
        """Turn on/off each active member light by registry name."""
        # Ensure group exists
        group = await self._repo.get_by_id(group_id, include_deleted=False)
        names = await self._repo.list_member_light_names(group_id)

        def _apply() -> list[str]:
            affected: list[str] = []
            for name in names:
                ok = hue.turn_on(name) if on else hue.turn_off(name)
                if ok:
                    affected.append(name)
            return affected

        affected = await asyncio.to_thread(_apply)
        logger.info(
            f"Group power group_id={group.id} name={group.name!r} on={on} "
            f"members={len(names)} affected={len(affected)}"
        )
        return {
            "group_id": group.id,
            "group_name": group.name,
            "on": on,
            "member_names": names,
            "affected": affected,
        }

    async def apply_config(
        self,
        group_id: str,
        config: LightConfig,
        hue: HueGroupController,
        *,
        transition_time_secs: float = 0,
    ) -> dict[str, object]:
        """Apply a LightConfig filtered to group member light names."""
        group = await self._repo.get_by_id(group_id, include_deleted=False)
        names = set(await self._repo.list_member_light_names(group_id))
        filtered_settings = [s for s in config.settings if s.light_name in names]
        filtered = LightConfig(
            name=config.name,
            settings=filtered_settings,
            description=config.description,
        )

        def _apply() -> None:
            hue.apply_light_config(filtered, transition_time_secs)

        await asyncio.to_thread(_apply)
        applied_names = [s.light_name for s in filtered_settings]
        logger.info(
            f"Group apply_config group_id={group.id} config={config.name!r} "
            f"applied={applied_names}"
        )
        return {
            "group_id": group.id,
            "group_name": group.name,
            "config_name": config.name,
            "applied_lights": applied_names,
            "transition_time_secs": transition_time_secs,
        }
