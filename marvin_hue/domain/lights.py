"""Light registry domain: catalog entity and errors.

SQLite owns app-side metadata. Philips Hue bridge remains source of truth
for physical device presence and live state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


class LightValidationError(ValueError):
    """Invalid light registry data."""


class LightConflictError(LightValidationError):
    """Active name (or other unique constraint) conflict."""


class LightNotFoundError(LookupError):
    """Registered light not found (or soft-deleted when not included)."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class RegisteredLight:
    """App catalog entry for a lamp/light.

    Attributes:
        id: Stable app UUID (string).
        name: Bridge/display name used to match Hue lights and setups JSON.
        nickname: Optional friendly name for UI/chat.
        room: Optional room label.
        notes: Free-text notes.
        bridge_light_id: Optional stable Hue id (prefer uniqueid, else light_id).
        eye_safety_limit_pct: Optional max brightness percent (0-100) stored for
            app use; v1 does not replace marvin_hue.eye_safety.EYE_SAFETY_LIMITS.
        enabled_for_app: If False, app features may skip this light.
        deleted_at: Soft-delete timestamp (UTC); None if active.
        created_at / updated_at: UTC timestamps.
    """

    id: str
    name: str
    nickname: Optional[str] = None
    room: Optional[str] = None
    notes: Optional[str] = None
    bridge_light_id: Optional[str] = None
    eye_safety_limit_pct: Optional[int] = None
    enabled_for_app: bool = True
    deleted_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        name = (self.name or "").strip()
        if not name:
            raise LightValidationError("name must be a non-empty string")
        self.name = name

        if self.nickname is not None:
            self.nickname = self.nickname.strip() or None
        if self.room is not None:
            self.room = self.room.strip() or None
        if self.notes is not None:
            self.notes = self.notes.strip() or None
        if self.bridge_light_id is not None:
            self.bridge_light_id = str(self.bridge_light_id).strip() or None

        if self.eye_safety_limit_pct is not None:
            if not isinstance(self.eye_safety_limit_pct, int) or isinstance(
                self.eye_safety_limit_pct, bool
            ):
                raise LightValidationError("eye_safety_limit_pct must be int or None")
            if self.eye_safety_limit_pct < 0 or self.eye_safety_limit_pct > 100:
                raise LightValidationError(
                    "eye_safety_limit_pct must be between 0 and 100"
                )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None
