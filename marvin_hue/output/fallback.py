"""Composite port: prefer Entertainment, degrade to REST on failure."""

from __future__ import annotations

from marvin_hue.logging_config import get_logger
from marvin_hue.output.port import LightFrameColor, LightOutputPort, TransportName

logger = get_logger("output.fallback")


class FallbackOutputPort:
    """Try primary (entertainment); on begin/apply failure, use secondary (REST)."""

    def __init__(self, primary: LightOutputPort, secondary: LightOutputPort) -> None:
        self._primary = primary
        self._secondary = secondary
        self._active: LightOutputPort = primary
        self._degraded = False

    @property
    def transport(self) -> TransportName:
        return self._active.transport

    @property
    def degraded(self) -> bool:
        return self._degraded

    def begin_session(self) -> None:
        try:
            self._primary.begin_session()
            self._active = self._primary
            self._degraded = False
        except Exception as e:
            logger.warning(f"Entertainment begin failed, falling back to REST: {e}")
            self._secondary.begin_session()
            self._active = self._secondary
            self._degraded = True

    def apply_frame(self, colors: list[LightFrameColor]) -> None:
        try:
            self._active.apply_frame(colors)
        except Exception as e:
            if self._active is self._primary:
                logger.warning(f"Entertainment apply failed, degrading to REST: {e}")
                try:
                    self._primary.end_session()
                except Exception:
                    pass
                self._secondary.begin_session()
                self._active = self._secondary
                self._degraded = True
                self._active.apply_frame(colors)
            else:
                raise

    def end_session(self) -> None:
        try:
            self._active.end_session()
        finally:
            # Also try to stop primary if we degraded mid-session
            if self._degraded and self._active is not self._primary:
                try:
                    if getattr(self._primary, "transport", None) == "entertainment":
                        # best-effort stop if stream was half-open
                        pass
                except Exception:
                    pass
            self._active = self._secondary
