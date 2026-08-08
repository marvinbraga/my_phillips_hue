"""Scheduled lighting actions domain."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


class ScheduleValidationError(ValueError):
    """Invalid schedule data."""


class ScheduleNotFoundError(LookupError):
    """Schedule not found."""


# apply_config | power_on | power_off | apply_group (group apply uses group_id in payload)
VALID_ACTION_TYPES = frozenset(
    {
        "apply_config",
        "power_on",
        "power_off",
        "apply_group",
        # Aliases accepted at domain boundary (normalize to power_*)
        "turn_on",
        "turn_off",
    }
)

_ACTION_ALIASES = {
    "turn_on": "power_on",
    "turn_off": "power_off",
}

_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_days_of_week(value: str) -> str:
    """Normalize CSV weekdays 0=Mon..6=Sun; empty means every day."""
    text = (value or "").strip()
    if not text:
        return ""
    parts = [p.strip() for p in text.split(",") if p.strip()]
    days: list[int] = []
    for p in parts:
        try:
            day = int(p)
        except ValueError as exc:
            raise ScheduleValidationError(
                f"days_of_week entries must be integers 0-6, got {p!r}"
            ) from exc
        if day < 0 or day > 6:
            raise ScheduleValidationError(
                f"days_of_week entries must be 0-6 (Mon-Sun), got {day}"
            )
        if day not in days:
            days.append(day)
    return ",".join(str(d) for d in days)


def _normalize_time_hhmm(value: str) -> str:
    text = (value or "").strip()
    if not _HHMM_RE.match(text):
        raise ScheduleValidationError(
            f"time_hhmm must be HH:MM 24h format, got {value!r}"
        )
    return text


def _normalize_payload(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {}
    if isinstance(payload, str):
        if not payload.strip():
            return {}
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ScheduleValidationError("action_payload must be valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ScheduleValidationError("action_payload JSON must be an object")
        return parsed
    if isinstance(payload, dict):
        return dict(payload)
    raise ScheduleValidationError("action_payload must be a dict or JSON object string")


@dataclass
class Schedule:
    """A local wall-clock schedule that triggers a lighting action.

    Attributes:
        id: Stable app UUID (string).
        name: Display name.
        enabled: Whether the runner should fire this schedule.
        time_hhmm: Local wall-clock time HH:MM (24h).
        days_of_week: CSV of weekdays 0=Mon..6=Sun; empty = every day.
            (Also referred to as weekdays in some APIs.)
        action_type: apply_config | power_on | power_off | apply_group.
        action_payload: JSON object, e.g. {"config_name": "...", "group_id": "..."}.
        last_run_at: Last successful fire (UTC); used to avoid double-fire per minute.
        created_at / updated_at: UTC timestamps.
    """

    id: str
    name: str
    time_hhmm: str
    action_type: str
    enabled: bool = True
    days_of_week: str = ""
    action_payload: dict[str, Any] = field(default_factory=dict)
    last_run_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        name = (self.name or "").strip()
        if not name:
            raise ScheduleValidationError("name must be a non-empty string")
        self.name = name

        self.time_hhmm = _normalize_time_hhmm(self.time_hhmm)
        self.days_of_week = _normalize_days_of_week(self.days_of_week)

        action = (self.action_type or "").strip()
        if action not in VALID_ACTION_TYPES:
            raise ScheduleValidationError(
                f"action_type must be one of "
                f"{sorted(set(VALID_ACTION_TYPES) - set(_ACTION_ALIASES))}, got {action!r}"
            )
        self.action_type = _ACTION_ALIASES.get(action, action)

        self.action_payload = _normalize_payload(self.action_payload)

    @property
    def weekdays(self) -> str:
        """Alias for days_of_week (CSV 0=Mon..6=Sun)."""
        return self.days_of_week

    def allows_weekday(self, weekday: int) -> bool:
        """Return True if weekday (0=Mon..6=Sun) is allowed."""
        if not self.days_of_week:
            return True
        allowed = {int(p) for p in self.days_of_week.split(",") if p}
        return weekday in allowed
