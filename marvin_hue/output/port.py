"""Light output port: push per-frame RGB without knowing REST vs Entertainment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class LightFrameColor:
    light_name: str
    r: int
    g: int
    b: int
    brightness: int  # 0-254 Hue scale (before or after eye-safety clamp)


TransportName = Literal["rest", "entertainment"]


@runtime_checkable
class LightOutputPort(Protocol):
    @property
    def transport(self) -> TransportName: ...

    def begin_session(self) -> None:
        """Prepare transport (no-op for REST)."""
        ...

    def apply_frame(self, colors: list[LightFrameColor]) -> None:
        """Push one full frame. Must be safe to call from mirror thread."""
        ...

    def end_session(self) -> None:
        """Release transport (stop DTLS stream)."""
        ...
