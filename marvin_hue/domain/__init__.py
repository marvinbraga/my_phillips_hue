"""Domain models and errors (framework-agnostic)."""

from marvin_hue.domain.groups import (
    GroupConflictError,
    GroupNotFoundError,
    GroupValidationError,
    LightGroup,
)
from marvin_hue.domain.lights import (
    LightConflictError,
    LightNotFoundError,
    LightValidationError,
    RegisteredLight,
)
from marvin_hue.domain.scene_history import (
    SceneHistoryNotFoundError,
    SceneHistoryValidationError,
    SceneSnapshot,
)
from marvin_hue.domain.schedules import (
    Schedule,
    ScheduleNotFoundError,
    ScheduleValidationError,
)

__all__ = [
    "GroupConflictError",
    "GroupNotFoundError",
    "GroupValidationError",
    "LightConflictError",
    "LightGroup",
    "LightNotFoundError",
    "LightValidationError",
    "RegisteredLight",
    "SceneHistoryNotFoundError",
    "SceneHistoryValidationError",
    "SceneSnapshot",
    "Schedule",
    "ScheduleNotFoundError",
    "ScheduleValidationError",
]
