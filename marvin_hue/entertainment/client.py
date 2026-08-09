"""Mockable facade over hue_entertainment.EntertainmentSession."""

from __future__ import annotations

import asyncio
from typing import Any, Coroutine, TypeVar

from marvin_hue.entertainment.credentials import EntertainmentCredentials
from marvin_hue.entertainment.models import (
    ChannelColor,
    ChannelInfo,
    EntertainmentAreaInfo,
)
from marvin_hue.logging_config import get_logger

logger = get_logger("entertainment.client")

T = TypeVar("T")


def _rgb8_to_16(v: int) -> int:
    """Map 0–255 → 0–65535 (``v * 257`` ≡ ``(v << 8) | v``)."""
    v = max(0, min(255, int(v)))
    return (v << 8) | v


class EntertainmentClient:
    """
    Thin wrapper around ``hue_entertainment`` for pairing, area listing,
    and DTLS streaming. Safe to construct without a bridge; network only
    happens on pair/list/start.
    """

    def __init__(
        self,
        host: str,
        credentials: EntertainmentCredentials | None = None,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self.host = host
        self.credentials = credentials
        self._session: Any | None = None
        self._streaming = False
        self._area_id: str | None = None
        self._loop: asyncio.AbstractEventLoop | None = loop

    # --- loop bridge (mirror threads → app asyncio loop) ---

    def set_loop(self, loop: asyncio.AbstractEventLoop | None) -> None:
        """Store the app event loop (call from FastAPI lifespan)."""
        self._loop = loop

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        return self._loop

    def run_coro(self, coro: Coroutine[Any, Any, T], timeout: float = 15.0) -> T:
        """
        Run an async coroutine from a sync context (e.g. mirror thread).

        Uses ``run_coroutine_threadsafe`` when a loop is set; otherwise
        ``asyncio.run`` for one-shot scripts (never call from inside a loop).
        """
        loop = self._loop
        if loop is not None and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(coro, loop)
            return future.result(timeout=timeout)
        return asyncio.run(coro)

    # --- state ---

    @property
    def is_ready(self) -> bool:
        """True when host + credentials are present (can list/start)."""
        return bool(self.host) and self.credentials is not None

    @property
    def is_streaming(self) -> bool:
        if self._session is not None:
            try:
                return bool(getattr(self._session, "is_streaming", self._streaming))
            except Exception:
                return self._streaming
        return self._streaming

    @property
    def active_area(self) -> str | None:
        return self._area_id

    @property
    def active_area_id(self) -> str | None:
        return self._area_id

    # --- session helpers ---

    async def _ensure_session(self) -> Any:
        if self.credentials is None:
            raise RuntimeError("Entertainment credentials missing")
        if self._session is None:
            from hue_entertainment import EntertainmentSession

            self._session = EntertainmentSession(
                self.host,
                self.credentials.username,
                self.credentials.clientkey,
            )
        return self._session

    async def pair(self, device_type: str = "marvin_hue#entertainment") -> EntertainmentCredentials:
        """Press bridge link button first. Returns and stores credentials."""
        from hue_entertainment import HueEntertainmentAPI

        api = HueEntertainmentAPI(self.host)
        try:
            creds = await api.pair(device_type=device_type)
        finally:
            close = getattr(api, "close", None)
            if callable(close):
                await close()
        self.credentials = EntertainmentCredentials(
            username=str(creds["username"]),
            clientkey=str(creds["clientkey"]),
        )
        # Drop any session bound to old credentials
        self._session = None
        logger.info(
            f"Entertainment paired username_suffix=…{self.credentials.username[-4:]}"
        )
        return self.credentials

    async def list_areas(self) -> list[EntertainmentAreaInfo]:
        session = await self._ensure_session()
        raw_areas = await session.get_entertainment_areas()
        out: list[EntertainmentAreaInfo] = []
        for area in raw_areas:
            channels: list[ChannelInfo] = []
            for ch in getattr(area, "channels", []) or []:
                pos = getattr(ch, "position", None)
                if pos is not None and not isinstance(pos, tuple):
                    try:
                        pos = tuple(pos)  # type: ignore[assignment]
                    except TypeError:
                        pos = None
                name = str(getattr(ch, "name", "") or "")
                service_id = str(getattr(ch, "service_id", "") or "")
                light_ids_raw = (
                    getattr(ch, "light_ids", None)
                    or getattr(ch, "members", None)
                    or ()
                )
                light_ids = tuple(str(x) for x in light_ids_raw)
                if service_id and service_id not in light_ids:
                    light_ids = light_ids + (service_id,)
                if name and name not in light_ids:
                    light_ids = light_ids + (name,)
                channels.append(
                    ChannelInfo(
                        channel_id=int(ch.channel_id),
                        name=name,
                        service_id=service_id,
                        light_ids=light_ids,
                        position=pos if isinstance(pos, tuple) else None,
                    )
                )
            out.append(
                EntertainmentAreaInfo(
                    id=str(area.id),
                    name=str(getattr(area, "name", "") or area.id),
                    channels=tuple(channels),
                )
            )
        return out

    async def start_stream(self, area_id: str) -> None:
        session = await self._ensure_session()
        self._session = session  # keep even when _ensure_session is mocked in tests
        await session.start(area_id)
        self._area_id = area_id
        self._streaming = True
        logger.info(f"Entertainment stream started area={area_id}")

    def send_frame(self, colors: list[ChannelColor]) -> None:
        """Non-blocking send of one full RGB frame (0–255 → 16-bit)."""
        if not self._streaming or self._session is None:
            raise RuntimeError("Entertainment stream not active")
        from hue_entertainment import LightColorCommand

        cmds = [
            LightColorCommand(
                channel_id=c.channel_id,
                red=_rgb8_to_16(c.r),
                green=_rgb8_to_16(c.g),
                blue=_rgb8_to_16(c.b),
            )
            for c in colors
        ]
        self._session.send(cmds)

    async def stop_stream(self) -> None:
        if self._session is not None:
            stop = getattr(self._session, "stop", None)
            if callable(stop):
                res = stop()
                if hasattr(res, "__await__"):
                    await res
            aclose = getattr(self._session, "aclose", None)
            if callable(aclose):
                await aclose()
        self._session = None
        self._streaming = False
        self._area_id = None
        logger.info("Entertainment stream stopped")
