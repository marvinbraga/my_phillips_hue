"""Scene history / undo domain: snapshots of full light states."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


class SceneHistoryValidationError(ValueError):
    """Invalid scene snapshot data."""


class SceneHistoryNotFoundError(LookupError):
    """Scene snapshot not found."""


VALID_SCENE_SOURCES = frozenset(
    {
        "apply",
        "mirror_stop",
        "manual",
        "group_apply",
    }
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SceneSnapshot:
    """A point-in-time capture of light states for undo / history.

    Attributes:
        id: Auto-increment DB id (None before insert).
        label: Optional human label.
        source: Origin of the snapshot (apply, mirror_stop, manual, group_apply).
        payload: List of light status dicts (JSON-serializable).
        created_at: UTC timestamp when captured.
    """

    source: str
    payload: list[dict[str, Any]]
    label: Optional[str] = None
    id: Optional[int] = None
    created_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        source = (self.source or "").strip()
        if not source:
            raise SceneHistoryValidationError("source must be a non-empty string")
        if source not in VALID_SCENE_SOURCES:
            raise SceneHistoryValidationError(
                f"source must be one of {sorted(VALID_SCENE_SOURCES)}, got {source!r}"
            )
        self.source = source

        if self.label is not None:
            self.label = self.label.strip() or None

        if not isinstance(self.payload, list):
            raise SceneHistoryValidationError("payload must be a list")
