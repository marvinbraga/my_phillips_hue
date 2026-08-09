"""REST/phue adapter implementing LightOutputPort via HueController."""

from __future__ import annotations

from marvin_hue.colors import Color
from marvin_hue.controllers import HueController
from marvin_hue.eye_safety import is_enabled_for_app
from marvin_hue.logging_config import get_logger
from marvin_hue.output.port import LightFrameColor, TransportName

logger = get_logger("output.rest")


class RestPhueAdapter:
    """Per-light REST color updates (existing HueController path)."""

    def __init__(self, hue: HueController, transition_time: int = 0) -> None:
        self._hue = hue
        self.transition_time = transition_time

    @property
    def transport(self) -> TransportName:
        return "rest"

    def begin_session(self) -> None:
        return None

    def end_session(self) -> None:
        return None

    def apply_frame(self, colors: list[LightFrameColor]) -> None:
        for c in colors:
            if not is_enabled_for_app(c.light_name):
                continue
            try:
                # HueController.set_light_color already clamps eye safety
                light = self._hue.set_light_color(
                    c.light_name,
                    Color(c.r, c.g, c.b, max(0, min(254, int(c.brightness)))),
                )
                if light is not None:
                    light.transitiontime = int(self.transition_time)
            except ValueError as e:
                logger.debug(f"REST light '{c.light_name}' unavailable: {e}")
            except Exception as e:
                logger.debug(f"REST apply_frame error for '{c.light_name}': {e}")
