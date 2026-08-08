"""HueController skips lights marked disabled_for_app in runtime policy."""

from unittest.mock import MagicMock

import pytest

from marvin_hue import eye_safety as es
from marvin_hue.basics import LightConfig, LightSetting
from marvin_hue.colors import Color
from marvin_hue.controllers import HueController


def _make_controller():
    c = HueController.__new__(HueController)
    play = MagicMock()
    play.name = "Hue Play 1"
    play.brightness = 0
    play.on = False
    c.lights = [play]
    c._light_cache = {play.name: play}
    return c, play


def setup_function() -> None:
    es.clear_runtime_policy()


def teardown_function() -> None:
    es.clear_runtime_policy()


def test_set_light_color_skips_disabled() -> None:
    c, play = _make_controller()
    es.set_runtime_policy(limits_pct={}, disabled_names={"Hue Play 1"})
    with pytest.raises(ValueError, match="desabilitada"):
        c.set_light_color("Hue Play 1", Color(255, 0, 0, 200))
    assert play.brightness == 0


def test_apply_config_skips_disabled_without_raising() -> None:
    c, play = _make_controller()
    es.set_runtime_policy(limits_pct={}, disabled_names={"Hue Play 1"})
    cfg = LightConfig(
        name="x",
        settings=[LightSetting("Hue Play 1", Color(1, 2, 3, 200))],
        description="d",
    )
    c.apply_light_config(cfg)
    assert play.brightness == 0


def test_set_brightness_skips_disabled() -> None:
    c, play = _make_controller()
    es.set_runtime_policy(limits_pct={}, disabled_names={"Hue Play 1"})
    assert c.set_brightness("Hue Play 1", 200) is False
    assert play.brightness == 0


def test_turn_on_off_skips_disabled() -> None:
    c, play = _make_controller()
    es.set_runtime_policy(limits_pct={}, disabled_names={"Hue Play 1"})
    assert c.turn_on("Hue Play 1") is False
    assert c.turn_off("Hue Play 1") is False
    assert play.on is False


def test_set_all_skips_disabled() -> None:
    c, play = _make_controller()
    other = MagicMock()
    other.name = "Lâmpada 1"
    other.on = False
    c.lights = [play, other]
    c._light_cache = {play.name: play, other.name: other}
    es.set_runtime_policy(limits_pct={}, disabled_names={"Hue Play 1"})
    c.set_all(True)
    assert play.on is False
    assert other.on is True
