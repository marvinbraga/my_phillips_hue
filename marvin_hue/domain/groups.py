"""Light group domain: named sets of registry lights."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


class GroupValidationError(ValueError):
    """Invalid light group data."""


class GroupConflictError(GroupValidationError):
    """Active group name (or other unique constraint) conflict."""


class GroupNotFoundError(LookupError):
    """Group not found (or soft-deleted when not included)."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class LightGroup:
    """Named group of lights from the app registry.

    Attributes:
        id: Stable app UUID (string).
        name: Unique active group name.
        room: Optional room label.
        notes: Free-text notes.
        light_ids: Member light registry ids (order not guaranteed by DB).
        deleted_at: Soft-delete timestamp (UTC); None if active.
        created_at / updated_at: UTC timestamps.
    """

    id: str
    name: str
    room: Optional[str] = None
    notes: Optional[str] = None
    light_ids: list[str] = field(default_factory=list)
    deleted_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        name = (self.name or "").strip()
        if not name:
            raise GroupValidationError("name must be a non-empty string")
        self.name = name

        if self.room is not None:
            self.room = self.room.strip() or None
        if self.notes is not None:
            self.notes = self.notes.strip() or None

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique_ids: list[str] = []
        for lid in self.light_ids or []:
            text = str(lid).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            unique_ids.append(text)
        self.light_ids = unique_ids

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None
