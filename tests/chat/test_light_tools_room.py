"""Room-aware light tools (registry snapshot + disabled filter + locations fallback)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from marvin_hue import eye_safety as es
from marvin_hue.chat.tools.light_tools import (
    build_light_tools,
    build_room_index_from_registry_rows,
)


@dataclass
class _FakeLight:
    name: str
    room: str | None = None
    enabled_for_app: bool = True


@pytest.fixture(autouse=True)
def _clear_policy():
    es.clear_runtime_policy()
    yield
    es.clear_runtime_policy()


@pytest.fixture
def room_index() -> dict[str, list[str]]:
    return {
        "escritorio": ["Lâmpada 1", "Fita Led"],
        "sala": ["Led cima"],
    }


def test_build_room_index_from_registry_rows_skips_disabled():
    lights = [
        _FakeLight("A", room="sala"),
        _FakeLight("B", room="sala", enabled_for_app=False),
        _FakeLight("C", room=None),
        _FakeLight("  ", room="x"),  # empty name skipped
    ]
    idx = build_room_index_from_registry_rows(lights)
    assert idx == {"sala": ["A"], "sem_sala": ["C"]}


def test_get_rooms_and_list_by_room(fake_controller, fake_manager, room_index):
    tools = {
        t.name: t
        for t in build_light_tools(fake_controller, fake_manager, room_index=room_index)
    }
    assert "get_rooms" in tools
    assert "list_lights_by_room" in tools

    rooms_out = tools["get_rooms"].invoke({})
    assert "escritorio" in rooms_out and "sala" in rooms_out
    assert "2 lâmpada" in rooms_out  # escritorio has 2

    all_rooms = tools["list_lights_by_room"].invoke({"room": ""})
    assert "escritorio" in all_rooms and "sala" in all_rooms

    one = tools["list_lights_by_room"].invoke({"room": "escritorio"})
    assert "Lâmpada 1" in one and "Fita Led" in one
    assert "Led cima" not in one

    # Case-insensitive room match
    one_ci = tools["list_lights_by_room"].invoke({"room": "ESCRITORIO"})
    assert "Lâmpada 1" in one_ci

    missing = tools["list_lights_by_room"].invoke({"room": "banheiro"})
    assert "não encontrada" in missing


def test_list_lights_excludes_disabled(fake_controller, fake_manager):
    es.set_runtime_policy(limits_pct={}, disabled_names={"Fita Led"})
    tools = {t.name: t for t in build_light_tools(fake_controller, fake_manager)}
    out = tools["list_lights"].invoke({})
    assert "Lâmpada 1" in out
    assert "Fita Led" not in out
    assert "Led cima" in out


def test_get_light_status_excludes_disabled(fake_controller, fake_manager):
    es.set_runtime_policy(limits_pct={}, disabled_names={"Fita Led"})
    tools = {t.name: t for t in build_light_tools(fake_controller, fake_manager)}
    out = tools["get_light_status"].invoke({})
    assert "Lâmpada 1" in out
    assert "Fita Led" not in out


def test_list_lights_by_room_filters_runtime_disabled(
    fake_controller, fake_manager, room_index
):
    es.set_runtime_policy(limits_pct={}, disabled_names={"Fita Led"})
    tools = {
        t.name: t
        for t in build_light_tools(fake_controller, fake_manager, room_index=room_index)
    }
    out = tools["list_lights_by_room"].invoke({"room": "escritorio"})
    assert "Lâmpada 1" in out
    assert "Fita Led" not in out


def test_set_room_power_and_brightness(fake_controller, fake_manager, room_index):
    fake_controller.turn_on.return_value = True
    fake_controller.turn_off.return_value = True
    fake_controller.set_brightness.return_value = True
    tools = {
        t.name: t
        for t in build_light_tools(fake_controller, fake_manager, room_index=room_index)
    }

    on_out = tools["set_room_power"].invoke({"room": "escritorio", "on": True})
    assert "escritorio" in on_out and "2 lâmpada" in on_out
    assert fake_controller.turn_on.call_count == 2

    off_out = tools["set_room_power"].invoke({"room": "sala", "on": False})
    assert "desligadas" in off_out
    fake_controller.turn_off.assert_called_with("Led cima")

    br_out = tools["set_room_brightness"].invoke(
        {"room": "escritorio", "brightness": 50}
    )
    assert "50%" in br_out
    # 50% -> 127 hue scale
    assert fake_controller.set_brightness.call_count == 2
    assert fake_controller.set_brightness.call_args_list[0][0][1] == int(
        (50 / 100) * 254
    )


def test_set_room_power_unknown_room(fake_controller, fake_manager, room_index):
    tools = {
        t.name: t
        for t in build_light_tools(fake_controller, fake_manager, room_index=room_index)
    }
    out = tools["set_room_power"].invoke({"room": "nada", "on": True})
    assert "não encontrada" in out
    fake_controller.turn_on.assert_not_called()


def test_room_index_fallback_from_locations_json(
    fake_controller, fake_manager, tmp_path: Path
):
    loc = tmp_path / "locs.json"
    loc.write_text(
        """
        {
          "lights": [
            {"name": "A", "room": "cozinha", "location": "x"},
            {"name": "B", "location": "Teto, centro"}
          ]
        }
        """,
        encoding="utf-8",
    )
    tools = {
        t.name: t
        for t in build_light_tools(
            fake_controller, fake_manager, locations_path=str(loc)
        )
    }
    rooms = tools["get_rooms"].invoke({})
    assert "cozinha" in rooms
    assert "Teto, centro" in rooms
    by = tools["list_lights_by_room"].invoke({"room": "cozinha"})
    assert "A" in by


def test_build_light_tools_includes_room_tool_names(fake_controller, fake_manager):
    names = {t.name for t in build_light_tools(fake_controller, fake_manager)}
    expected = {
        "list_lights",
        "get_light_status",
        "set_light_color",
        "apply_config",
        "list_configs",
        "turn_off_lights",
        "turn_on_lights",
        "set_brightness",
        "save_current_config",
        "get_light_locations",
        "get_rooms",
        "list_lights_by_room",
        "set_room_power",
        "set_room_brightness",
    }
    assert expected <= names
    assert len(names) >= 14
