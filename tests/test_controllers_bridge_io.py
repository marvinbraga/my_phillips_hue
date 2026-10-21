"""Bridge I/O budget of HueController (issue #9 perf review).

``get_lights_status`` must use ONE ``GET /lights/`` instead of ~5 GETs per
light (every ``phue.Light`` property is a GET), ``list_lights`` must answer
from the name cache, and turning off with a transition must be a one-shot
``set_light(..., transitiontime=...)`` that never mutates the persistent
``Light.transitiontime``.

The fake bridge serves real ``phue.Light`` objects from one dict, so the
legacy per-property path and the new single-GET path read the same state.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from phue import Light

from marvin_hue import eye_safety
from marvin_hue.controllers import HueController
from marvin_hue.utils import ColorConverter

_BRIDGE_LIGHTS: dict[str, dict[str, Any]] = {
    "1": {
        "name": "Lâmpada 1",
        "state": {"on": True, "bri": 200, "xy": [0.4573, 0.41], "reachable": True},
    },
    "2": {
        "name": "Lâmpada 2",
        "state": {"on": False, "bri": 120, "xy": [0.3, 0.3], "reachable": True},
    },
    "3": {
        "name": "Hue Iris",
        "state": {"on": True, "bri": 254, "xy": [0.1691, 0.0441], "reachable": True},
    },
    "4": {
        "name": "Fita Led",
        "state": {"on": True, "bri": 64, "xy": [0.6915, 0.3083], "reachable": False},
    },
    "5": {
        "name": "Led cima",
        "state": {"on": True, "bri": 1, "xy": [0.3227, 0.329], "reachable": True},
    },
}


class CountingBridge:
    """Minimal phue ``Bridge`` double that counts every bridge round-trip."""

    def __init__(self, lights: dict[str, dict[str, Any]]) -> None:
        self.data = copy.deepcopy(lights)
        self.get_calls: list[tuple[Any, Any]] = []
        self.set_calls: list[tuple[Any, Any, Any, dict[str, Any]]] = []

    def connect(self) -> None:
        return None

    def get_light_objects(self) -> list[Light]:
        return [Light(self, int(light_id)) for light_id in self.data]

    def get_light(self, light_id: Any = None, parameter: Any = None) -> Any:
        self.get_calls.append((light_id, parameter))
        if light_id is None:
            return copy.deepcopy(self.data)
        state = self.data[str(light_id)]
        if parameter is None:
            return copy.deepcopy(state)
        if parameter in ("name", "type", "uniqueid", "swversion"):
            return state[parameter]
        return state["state"][parameter]

    def set_light(
        self, light_id: Any, parameter: Any, value: Any = None, **kwargs: Any
    ) -> list[list[dict[str, Any]]]:
        self.set_calls.append((light_id, parameter, value, kwargs))
        self.data[str(light_id)]["state"][parameter] = value
        return [[{"success": {f"/lights/{light_id}/state/{parameter}": value}}]]

    @property
    def round_trips(self) -> int:
        return len(self.get_calls) + len(self.set_calls)

    def reset_counts(self) -> None:
        self.get_calls.clear()
        self.set_calls.clear()


def _legacy_get_lights_status(controller: HueController) -> list[dict[str, Any]]:
    """Reference: the pre-#9 implementation (one GET per property access)."""
    lights_status: list[dict[str, Any]] = []
    for light in controller.lights:
        try:
            status: dict[str, Any] = {
                "name": light.name,
                "on": light.on,
                "brightness": light.brightness if light.on else 0,
                "reachable": light.reachable,
            }
            if light.on and hasattr(light, "xy") and light.xy:
                rgb = ColorConverter.xy_to_rgb(light.xy, light.brightness)
                status["color"] = {"r": rgb[0], "g": rgb[1], "b": rgb[2]}
            else:
                status["color"] = {"r": 50, "g": 50, "b": 50}
            lights_status.append(status)
        except Exception as e:  # noqa: BLE001 — legacy behaviour under test
            lights_status.append(
                {
                    "name": light.name,
                    "on": False,
                    "brightness": 0,
                    "reachable": False,
                    "color": {"r": 50, "g": 50, "b": 50},
                    "error": str(e),
                }
            )
    return lights_status


@pytest.fixture
def clean_policy() -> Any:
    eye_safety.clear_runtime_policy()
    yield
    eye_safety.clear_runtime_policy()


@pytest.fixture
def fake_bridge() -> CountingBridge:
    return CountingBridge(_BRIDGE_LIGHTS)


@pytest.fixture
def controller(
    fake_bridge: CountingBridge, monkeypatch: pytest.MonkeyPatch
) -> HueController:
    monkeypatch.setattr("marvin_hue.controllers.Bridge", lambda ip: fake_bridge)
    hue = HueController("192.168.1.100")
    fake_bridge.reset_counts()
    return hue


def test_get_lights_status_matches_legacy_output(
    controller: HueController, fake_bridge: CountingBridge
) -> None:
    expected = _legacy_get_lights_status(controller)
    legacy_calls = fake_bridge.round_trips
    fake_bridge.reset_counts()

    actual = controller.get_lights_status()

    assert actual == expected
    assert [row["name"] for row in actual] == [
        "Lâmpada 1",
        "Lâmpada 2",
        "Hue Iris",
        "Fita Led",
        "Led cima",
    ]
    # Legacy: a lit light costs 10 GETs (name, on x3, bri x2, reachable, xy x3)
    # and an off one 5 (name, on x3, reachable): 4 lit + 1 off = 45.
    assert legacy_calls == 45
    assert fake_bridge.get_calls == [(None, None)]
    assert fake_bridge.round_trips == 1


def test_get_lights_status_off_light_is_gray_with_zero_brightness(
    controller: HueController,
) -> None:
    row = next(r for r in controller.get_lights_status() if r["name"] == "Lâmpada 2")
    assert row == {
        "name": "Lâmpada 2",
        "on": False,
        "brightness": 0,
        "reachable": True,
        "color": {"r": 50, "g": 50, "b": 50},
    }


def test_get_lights_status_on_light_without_xy_is_gray(
    controller: HueController, fake_bridge: CountingBridge
) -> None:
    del fake_bridge.data["3"]["state"]["xy"]  # white-ambiance bulb

    row = next(r for r in controller.get_lights_status() if r["name"] == "Hue Iris")

    assert row["on"] is True
    assert row["brightness"] == 254
    assert row["color"] == {"r": 50, "g": 50, "b": 50}
    assert "error" not in row


def test_get_lights_status_light_missing_from_bridge_gets_error_row(
    controller: HueController, fake_bridge: CountingBridge
) -> None:
    del fake_bridge.data["4"]

    status = controller.get_lights_status()

    row = next(r for r in status if r["name"] == "Fita Led")
    assert row["on"] is False
    assert row["brightness"] == 0
    assert row["reachable"] is False
    assert row["color"] == {"r": 50, "g": 50, "b": 50}
    assert row["error"]
    assert len(status) == 5
    assert fake_bridge.round_trips == 1


def test_get_lights_status_missing_state_key_gets_error_row(
    controller: HueController, fake_bridge: CountingBridge
) -> None:
    del fake_bridge.data["1"]["state"]["reachable"]

    row = next(r for r in controller.get_lights_status() if r["name"] == "Lâmpada 1")

    assert row["on"] is False
    assert "reachable" in row["error"]


def test_get_lights_status_propagates_bridge_failure(
    controller: HueController,
    fake_bridge: CountingBridge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def down(*args: Any, **kwargs: Any) -> Any:
        raise OSError("bridge unreachable")

    monkeypatch.setattr(fake_bridge, "get_light", down)

    with pytest.raises(OSError, match="bridge unreachable"):
        controller.get_lights_status()


def test_list_lights_uses_cache_without_bridge_calls(
    controller: HueController, fake_bridge: CountingBridge
) -> None:
    names = controller.list_lights()

    assert names == ["Lâmpada 1", "Lâmpada 2", "Hue Iris", "Fita Led", "Led cima"]
    assert fake_bridge.round_trips == 0


def test_turn_off_with_transition_is_one_shot(
    controller: HueController, fake_bridge: CountingBridge, clean_policy: None
) -> None:
    assert controller.turn_off_with_transition("Lâmpada 1", 10) is True

    assert fake_bridge.set_calls == [(1, "on", False, {"transitiontime": 10})]
    light = controller._get_light_by_name("Lâmpada 1")
    assert light is not None
    assert light.transitiontime is None  # persistent transition untouched
    assert fake_bridge.data["1"]["state"]["on"] is False


def test_turn_off_with_zero_transition_omits_transitiontime(
    controller: HueController, fake_bridge: CountingBridge, clean_policy: None
) -> None:
    assert controller.turn_off_with_transition("Lâmpada 1", 0) is True

    assert fake_bridge.set_calls == [(1, "on", False, {})]


def test_turn_off_with_transition_unknown_or_disabled_returns_false(
    controller: HueController, fake_bridge: CountingBridge, clean_policy: None
) -> None:
    eye_safety.set_runtime_policy(limits_pct={}, disabled_names={"Lâmpada 2"})

    assert controller.turn_off_with_transition("Nope", 10) is False
    assert controller.turn_off_with_transition("Lâmpada 2", 10) is False
    assert fake_bridge.set_calls == []


def test_turn_off_with_transition_rejects_negative(
    controller: HueController, clean_policy: None
) -> None:
    with pytest.raises(ValueError):
        controller.turn_off_with_transition("Lâmpada 1", -1)


def test_turn_off_with_transition_raises_on_bridge_error_entry(
    controller: HueController,
    fake_bridge: CountingBridge,
    monkeypatch: pytest.MonkeyPatch,
    clean_policy: None,
) -> None:
    def error_reply(*args: Any, **kwargs: Any) -> Any:
        return [[{"error": {"description": "device is set to off"}}]]

    monkeypatch.setattr(fake_bridge, "set_light", error_reply)

    with pytest.raises(RuntimeError, match="device is set to off"):
        controller.turn_off_with_transition("Lâmpada 1", 10)


def test_turn_on_after_transition_off_restores_cached_brightness(
    controller: HueController, fake_bridge: CountingBridge, clean_policy: None
) -> None:
    """phue's bri=1 workaround needs ``Light._brightness``: the single-GET status
    must hydrate it like the legacy per-property reads did (never send null)."""
    controller.get_lights_status()  # e.g. the lights_off snapshot
    controller.turn_off_with_transition("Lâmpada 1", 10)
    fake_bridge.reset_counts()

    assert controller.turn_on("Lâmpada 1") is True

    sent = [(c[1], c[2]) for c in fake_bridge.set_calls]
    assert ("bri", None) not in sent
    assert sent == [("on", True), ("bri", 200)]
