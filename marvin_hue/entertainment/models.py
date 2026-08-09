"""Domain models for Entertainment areas / channels (library-agnostic)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ChannelInfo:
    channel_id: int
    name: str = ""
    service_id: str = ""
    light_ids: tuple[str, ...] = ()
    position: tuple[float, float, float] | None = None  # x,y,z if available


@dataclass(frozen=True, slots=True)
class EntertainmentAreaInfo:
    id: str
    name: str
    channels: tuple[ChannelInfo, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ChannelColor:
    channel_id: int
    r: int  # 0-255
    g: int
    b: int
