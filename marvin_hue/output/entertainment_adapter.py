"""Entertainment DTLS stream adapter implementing LightOutputPort."""

from __future__ import annotations

from marvin_hue.entertainment.channel_map import MappedChannel
from marvin_hue.entertainment.client import EntertainmentClient
from marvin_hue.entertainment.models import ChannelColor
from marvin_hue.eye_safety import clamp_eye_safety, is_enabled_for_app
from marvin_hue.logging_config import get_logger
from marvin_hue.output.port import LightFrameColor, TransportName

logger = get_logger("output.entertainment")


def _apply_bri(r: int, g: int, b: int, bri: int) -> tuple[int, int, int]:
    """Scale RGB by Hue brightness (0–254) so absolute level is limited."""
    bri = max(0, min(254, int(bri)))
    if bri <= 0:
        return 0, 0, 0
    return (
        max(0, min(255, r * bri // 254)),
        max(0, min(255, g * bri // 254)),
        max(0, min(255, b * bri // 254)),
    )


class EntertainmentStreamAdapter:
    """Map light names → channels and stream via EntertainmentClient."""

    def __init__(
        self,
        client: EntertainmentClient,
        area_id: str,
        channels: list[MappedChannel],
        *,
        start_timeout: float = 15.0,
        stop_timeout: float = 10.0,
    ) -> None:
        self._client = client
        self._area_id = area_id
        self._channels = list(channels)
        self._name_to_channel: dict[str, int] = {
            m.light_name: m.channel_id for m in self._channels
        }
        self._start_timeout = start_timeout
        self._stop_timeout = stop_timeout

    @property
    def transport(self) -> TransportName:
        return "entertainment"

    @property
    def area_id(self) -> str:
        return self._area_id

    def begin_session(self) -> None:
        """Start stream from a worker thread, or no-op if already streaming.

        From the FastAPI event-loop thread, pre-start with
        ``await client.start_stream(area_id)`` before calling this.
        """
        if self._client.is_streaming and self._client.active_area == self._area_id:
            logger.debug(
                f"Entertainment session already active area={self._area_id}"
            )
            return
        try:
            self._client.run_coro(
                self._client.start_stream(self._area_id),
                timeout=self._start_timeout,
            )
        except RuntimeError as e:
            # Called from event loop without pre-start — surface clearly
            if "event loop" in str(e).lower() or "await" in str(e).lower():
                if self._client.is_streaming:
                    return
                raise RuntimeError(
                    "Entertainment stream not started: await "
                    "EntertainmentClient.start_stream() from the async route "
                    "before begin_session()"
                ) from e
            raise
        logger.info(f"Entertainment session begun area={self._area_id}")

    def apply_frame(self, colors: list[LightFrameColor]) -> None:
        cmds: list[ChannelColor] = []
        for c in colors:
            if not is_enabled_for_app(c.light_name):
                continue
            channel_id = self._name_to_channel.get(c.light_name)
            if channel_id is None:
                continue
            bri = clamp_eye_safety(c.light_name, int(c.brightness), scale="hue")
            r, g, b = _apply_bri(c.r, c.g, c.b, bri)
            cmds.append(ChannelColor(channel_id=channel_id, r=r, g=g, b=b))
        if cmds:
            self._client.send_frame(cmds)

    def end_session(self) -> None:
        if not self._client.is_streaming:
            return
        try:
            self._client.run_coro(
                self._client.stop_stream(),
                timeout=self._stop_timeout,
            )
        except RuntimeError as e:
            # Async route should await stop_stream; ignore same-loop case
            if "event loop" in str(e).lower() or "await" in str(e).lower():
                logger.debug(
                    "end_session skipped on event loop (await stop_stream in route)"
                )
                return
            logger.warning(f"Entertainment end_session error: {e}")
        except Exception as e:
            logger.warning(f"Entertainment end_session error: {e}")
