"""Domain models and errors (framework-agnostic)."""

from marvin_hue.domain.lights import (
    LightConflictError,
    LightNotFoundError,
    LightValidationError,
    RegisteredLight,
)

__all__ = [
    "LightConflictError",
    "LightNotFoundError",
    "LightValidationError",
    "RegisteredLight",
]
