"""Schedule CRUD and tick execution (local wall-clock HH:MM + weekdays)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional, Protocol
from uuid import uuid4

from marvin_hue.basics import LightConfig, LightSetupsManager
from marvin_hue.domain.schedules import (
    Schedule,
    ScheduleNotFoundError,
    ScheduleValidationError,
)
from marvin_hue.logging_config import get_logger
from marvin_hue.persistence.schedule_repository import ScheduleRepository
from marvin_hue.services.group_service import GroupService

logger = get_logger("services.schedule")

_UNSET: object = object()


class HueScheduleController(Protocol):
    def turn_on(self, light_name: str) -> bool: ...

    def turn_off(self, light_name: str) -> bool: ...

    def apply_light_config(
        self, light_config: LightConfig, transition_time_secs: float = 0
    ) -> object: ...

    def get_lights_status(self) -> list[dict[str, Any]]: ...


class ScheduleService:
    """CRUD + tick for local wall-clock schedules."""

    def __init__(
        self,
        repo: ScheduleRepository,
        *,
        hue: Optional[HueScheduleController] = None,
        manager: Optional[LightSetupsManager] = None,
        group_service: Optional[GroupService] = None,
    ) -> None:
        self._repo = repo
        self._hue = hue
        self._manager = manager
        self._group_service = group_service

    def bind(
        self,
        *,
        hue: Optional[HueScheduleController] = None,
        manager: Optional[LightSetupsManager] = None,
        group_service: Optional[GroupService] = None,
    ) -> None:
        """Late-bind runtime deps (lifespan / tests)."""
        if hue is not None:
            self._hue = hue
        if manager is not None:
            self._manager = manager
        if group_service is not None:
            self._group_service = group_service

    async def aclose(self) -> None:
        await self._repo.close()

    async def list_schedules(self) -> list[Schedule]:
        return await self._repo.list_all()

    async def get_schedule(self, schedule_id: str) -> Schedule:
        return await self._repo.get_by_id(schedule_id)

    async def create_schedule(
        self,
        *,
        name: str,
        time_hhmm: str,
        action_type: str,
        enabled: bool = True,
        days_of_week: str = "",
        action_payload: Optional[dict[str, Any]] = None,
    ) -> Schedule:
        now = datetime.now(timezone.utc)
        schedule = Schedule(
            id=str(uuid4()),
            name=name,
            time_hhmm=time_hhmm,
            action_type=action_type,
            enabled=enabled,
            days_of_week=days_of_week,
            action_payload=dict(action_payload or {}),
            created_at=now,
            updated_at=now,
        )
        return await self._repo.create(schedule)

    async def update_schedule(
        self,
        schedule_id: str,
        *,
        name: object = _UNSET,
        time_hhmm: object = _UNSET,
        action_type: object = _UNSET,
        enabled: object = _UNSET,
        days_of_week: object = _UNSET,
        action_payload: object = _UNSET,
    ) -> Schedule:
        schedule = await self._repo.get_by_id(schedule_id)

        new_name = schedule.name if name is _UNSET else name
        new_time = schedule.time_hhmm if time_hhmm is _UNSET else time_hhmm
        new_action = schedule.action_type if action_type is _UNSET else action_type
        new_enabled = schedule.enabled if enabled is _UNSET else enabled
        new_days = schedule.days_of_week if days_of_week is _UNSET else days_of_week
        new_payload = (
            schedule.action_payload if action_payload is _UNSET else action_payload
        )

        if new_name is None or (isinstance(new_name, str) and not str(new_name).strip()):
            raise ScheduleValidationError("name must be non-empty")
        if new_time is None:
            raise ScheduleValidationError("time_hhmm is required")
        if new_action is None:
            raise ScheduleValidationError("action_type is required")
        if new_enabled is None:
            raise ScheduleValidationError("enabled cannot be null")

        updated = Schedule(
            id=schedule.id,
            name=str(new_name),
            time_hhmm=str(new_time),
            action_type=str(new_action),
            enabled=bool(new_enabled),
            days_of_week="" if new_days is None else str(new_days),
            action_payload=dict(new_payload or {})  # type: ignore[arg-type]
            if not isinstance(new_payload, dict)
            else dict(new_payload),
            last_run_at=schedule.last_run_at,
            created_at=schedule.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        return await self._repo.update(updated)

    async def delete_schedule(self, schedule_id: str) -> None:
        await self._repo.delete(schedule_id)

    def _already_ran_this_minute(
        self, schedule: Schedule, local_now: datetime
    ) -> bool:
        if schedule.last_run_at is None:
            return False
        last = schedule.last_run_at
        # Compare in local wall clock of local_now
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        local_last = last.astimezone(local_now.tzinfo) if local_now.tzinfo else last
        return (
            local_last.year == local_now.year
            and local_last.month == local_now.month
            and local_last.day == local_now.day
            and local_last.hour == local_now.hour
            and local_last.minute == local_now.minute
        )

    def _matches_now(self, schedule: Schedule, local_now: datetime) -> bool:
        hhmm = local_now.strftime("%H:%M")
        if schedule.time_hhmm != hhmm:
            return False
        # Python weekday: Mon=0 .. Sun=6 — matches domain
        return schedule.allows_weekday(local_now.weekday())

    async def tick(self, local_now: datetime) -> list[dict[str, Any]]:
        """Evaluate enabled schedules against local wall-clock time.

        Fires at most once per local minute per schedule (last_run_at guard).
        """
        if local_now.tzinfo is None:
            # Treat naive as local system time (caller should pass aware).
            local_now = local_now.astimezone()

        enabled = await self._repo.list_enabled()
        results: list[dict[str, Any]] = []
        for schedule in enabled:
            if not self._matches_now(schedule, local_now):
                continue
            if self._already_ran_this_minute(schedule, local_now):
                continue
            try:
                detail = await self.execute(schedule)
                # Stamp with the tick's local wall-clock (as UTC) so the
                # per-minute guard works under frozen clocks in tests.
                run_at = local_now.astimezone(timezone.utc)
                await self._repo.mark_last_run(schedule.id, when=run_at)
                results.append(
                    {
                        "schedule_id": schedule.id,
                        "name": schedule.name,
                        "status": "ok",
                        "detail": detail,
                    }
                )
            except Exception as exc:
                logger.exception(
                    f"Schedule tick failed id={schedule.id} name={schedule.name!r}: {exc}"
                )
                results.append(
                    {
                        "schedule_id": schedule.id,
                        "name": schedule.name,
                        "status": "error",
                        "error": str(exc),
                    }
                )
        return results

    async def run_now(self, schedule_id: str) -> dict[str, Any]:
        schedule = await self._repo.get_by_id(schedule_id)
        detail = await self.execute(schedule)
        await self._repo.mark_last_run(schedule.id, when=datetime.now(timezone.utc))
        return {
            "schedule_id": schedule.id,
            "name": schedule.name,
            "status": "ok",
            "detail": detail,
        }

    async def execute(self, schedule: Schedule) -> dict[str, Any]:
        """Execute one schedule action (used by tick and manual run)."""
        if self._hue is None:
            raise ScheduleValidationError("Hue controller is not configured")

        action = schedule.action_type
        payload = schedule.action_payload or {}

        if action == "apply_config":
            return await self._exec_apply_config(payload)
        if action == "power_on":
            return await self._exec_power(on=True, payload=payload)
        if action == "power_off":
            return await self._exec_power(on=False, payload=payload)
        if action == "apply_group":
            return await self._exec_apply_group(payload)
        raise ScheduleValidationError(f"Unsupported action_type: {action!r}")

    async def _exec_apply_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._manager is None:
            raise ScheduleValidationError("Light setups manager is not configured")
        config_name = str(payload.get("config_name") or "").strip()
        if not config_name:
            raise ScheduleValidationError(
                "action_payload.config_name is required for apply_config"
            )
        config = self._manager.get_config(config_name)
        if config is None:
            raise ScheduleValidationError(f"Unknown config_name: {config_name!r}")
        transition = float(payload.get("transition_time_secs") or 0)
        hue = self._hue
        assert hue is not None

        def _apply() -> None:
            hue.apply_light_config(config, transition)

        await asyncio.to_thread(_apply)
        return {"action": "apply_config", "config_name": config_name}

    async def _exec_power(self, *, on: bool, payload: dict[str, Any]) -> dict[str, Any]:
        group_id = payload.get("group_id")
        if group_id:
            if self._group_service is None:
                raise ScheduleValidationError("Group service is not configured")
            result = await self._group_service.set_power(
                str(group_id), on=on, hue=self._hue  # type: ignore[arg-type]
            )
            return {"action": "power_on" if on else "power_off", **result}

        hue = self._hue
        assert hue is not None

        def _all_power() -> list[str]:
            status = hue.get_lights_status()
            affected: list[str] = []
            for item in status:
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                ok = hue.turn_on(name) if on else hue.turn_off(name)
                if ok:
                    affected.append(name)
            return affected

        affected = await asyncio.to_thread(_all_power)
        return {
            "action": "power_on" if on else "power_off",
            "affected": affected,
            "scope": "all",
        }

    async def _exec_apply_group(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._group_service is None:
            raise ScheduleValidationError("Group service is not configured")
        if self._manager is None:
            raise ScheduleValidationError("Light setups manager is not configured")
        group_id = str(payload.get("group_id") or "").strip()
        config_name = str(payload.get("config_name") or "").strip()
        if not group_id:
            raise ScheduleValidationError(
                "action_payload.group_id is required for apply_group"
            )
        if not config_name:
            raise ScheduleValidationError(
                "action_payload.config_name is required for apply_group"
            )
        config = self._manager.get_config(config_name)
        if config is None:
            raise ScheduleValidationError(f"Unknown config_name: {config_name!r}")
        transition = float(payload.get("transition_time_secs") or 0)
        result = await self._group_service.apply_config(
            group_id,
            config,
            self._hue,  # type: ignore[arg-type]
            transition_time_secs=transition,
        )
        return {"action": "apply_group", **result}
