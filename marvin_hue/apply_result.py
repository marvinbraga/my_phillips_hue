"""Per-light outcome of applying a LightConfig to the Hue bridge."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ApplyResult:
    """Outcome of applying a LightConfig.

    ``applied`` holds light names that succeeded. ``failed`` holds
    ``(light_name, error_message)`` pairs. Lights skipped because they are
    not enabled for the app appear in neither collection.
    """

    applied: tuple[str, ...]
    failed: tuple[tuple[str, str], ...]

    @property
    def ok(self) -> bool:
        return len(self.failed) == 0

    @property
    def partial(self) -> bool:
        return len(self.applied) > 0 and len(self.failed) > 0
