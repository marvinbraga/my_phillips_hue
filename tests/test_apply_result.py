"""ApplyResult and HueController.apply_light_config per-light outcomes."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from loguru import logger as loguru_logger

from marvin_hue import eye_safety as es
from marvin_hue.apply_result import ApplyResult
from marvin_hue.basics import LightConfig, LightSetting
from marvin_hue.colors import Color
from marvin_hue.controllers import HueController


@pytest.fixture(autouse=True)
def _clear_runtime_policy() -> Iterator[None]:
    es.clear_runtime_policy()
    yield
    es.clear_runtime_policy()


def _make_controller(*names: str) -> HueController:
    controller = HueController.__new__(HueController)
    lights: list[MagicMock] = []
    cache: dict[str, MagicMock] = {}
    for name in names:
        light = MagicMock()
        light.name = name
        light.brightness = 0
        light.on = False
        lights.append(light)
        cache[name] = light
    controller.lights = lights
    controller._light_cache = cache
    return controller


def _scene(*names: str) -> LightConfig:
    settings = [LightSetting(name, Color(255, 0, 0, 200)) for name in names]
    return LightConfig(name="test_scene", settings=settings, description="d")


class TestApplyResultValueObject:
    def test_ok_when_failed_empty(self) -> None:
        result = ApplyResult(applied=("Lâmpada 1",), failed=())
        assert result.ok is True
        assert result.partial is False

    def test_partial_when_mixed_outcomes(self) -> None:
        result = ApplyResult(
            applied=("Lâmpada 1",),
            failed=(("Lâmpada 2", "bridge timeout"),),
        )
        assert result.ok is False
        assert result.partial is True

    def test_all_failed_is_not_ok_and_not_partial(self) -> None:
        result = ApplyResult(applied=(), failed=(("Lâmpada 1", "missing"),))
        assert result.ok is False
        assert result.partial is False

    def test_zero_lights_is_ok(self) -> None:
        result = ApplyResult(applied=(), failed=())
        assert result.ok is True
        assert result.partial is False


class TestApplyLightConfigResult:
    def test_all_lights_succeed(self) -> None:
        controller = _make_controller("Lâmpada 1", "Lâmpada 2")
        result = controller.apply_light_config(_scene("Lâmpada 1", "Lâmpada 2"))

        assert isinstance(result, ApplyResult)
        assert result.ok is True
        assert result.applied == ("Lâmpada 1", "Lâmpada 2")
        assert result.failed == ()
        assert result.partial is False

    def test_one_light_raises_partial_and_does_not_raise(self) -> None:
        controller = _make_controller("Lâmpada 1")
        result = controller.apply_light_config(_scene("Lâmpada 1", "Missing Light"))

        assert result.partial is True
        assert result.ok is False
        assert "Lâmpada 1" in result.applied
        failed_names = tuple(name for name, _ in result.failed)
        assert "Missing Light" in failed_names
        assert all(message for _, message in result.failed)

    def test_unexpected_exception_recorded_as_failed(self) -> None:
        controller = _make_controller("Lâmpada 1", "Lâmpada 2")
        original = controller.set_light_color

        def boom(light_name: str, color: Color) -> object:
            if light_name == "Lâmpada 2":
                raise RuntimeError("bridge timeout")
            return original(light_name, color)

        controller.set_light_color = boom  # type: ignore[method-assign]
        result = controller.apply_light_config(_scene("Lâmpada 1", "Lâmpada 2"))

        assert result.partial is True
        assert result.applied == ("Lâmpada 1",)
        assert result.failed[0][0] == "Lâmpada 2"
        assert "bridge timeout" in result.failed[0][1]

    def test_disabled_light_skipped_not_in_applied_or_failed(self) -> None:
        controller = _make_controller("Lâmpada 1", "Hue Play 1")
        es.set_runtime_policy(limits_pct={}, disabled_names={"Hue Play 1"})

        result = controller.apply_light_config(_scene("Lâmpada 1", "Hue Play 1"))

        assert "Hue Play 1" not in result.applied
        assert all(name != "Hue Play 1" for name, _ in result.failed)
        assert result.applied == ("Lâmpada 1",)
        assert result.failed == ()
        assert result.ok is True
        assert result.partial is False

    def test_all_disabled_is_ok_with_empty_applied(self) -> None:
        controller = _make_controller("Hue Play 1")
        es.set_runtime_policy(limits_pct={}, disabled_names={"Hue Play 1"})

        result = controller.apply_light_config(_scene("Hue Play 1"))

        assert result.applied == ()
        assert result.failed == ()
        assert result.ok is True
        assert result.partial is False

    def test_success_log_not_emitted_when_failures(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        captured: list[str] = []
        sink_id = loguru_logger.add(
            lambda message: captured.append(message.record["message"])
        )
        handler_id = loguru_logger.add(caplog.handler, format="{message}")
        caplog.set_level(logging.INFO)
        try:
            controller = _make_controller("Lâmpada 1")
            controller.apply_light_config(_scene("Lâmpada 1", "Ghost"))
        finally:
            loguru_logger.remove(sink_id)
            loguru_logger.remove(handler_id)

        combined = f"{caplog.text}\n" + "\n".join(captured)
        assert "applied successfully" not in combined
