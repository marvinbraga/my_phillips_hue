"""Exercita as 10 closures de build_light_tools (cobertura + comportamento)."""
from __future__ import annotations

import pytest


@pytest.fixture
def tools(fake_controller, fake_manager):
    from marvin_hue.chat.tools.light_tools import build_light_tools
    return {t.name: t for t in build_light_tools(fake_controller, fake_manager)}


def test_get_light_status_formats_rows(tools):
    out = tools["get_light_status"].invoke({})
    assert "Fita Led" in out and "%" in out and "Ligada" in out


def test_apply_config_found(tools, fake_controller, fake_manager):
    out = tools["apply_config"].invoke({"config_name": "noite_relaxante"})
    assert "aplicada" in out
    fake_controller.apply_light_config.assert_called_once()


def test_apply_config_not_found(tools):
    out = tools["apply_config"].invoke({"config_name": "inexistente"})
    assert "não encontrada" in out


def test_list_configs_all_and_search(tools):
    assert "noite_relaxante" in tools["list_configs"].invoke({})
    assert "Nenhuma" in tools["list_configs"].invoke({"search": "zzz"})
    assert "noite_relaxante" in tools["list_configs"].invoke({"search": "noite"})


def test_turn_off_specific_found_and_missing(tools, fake_controller):
    fake_controller.turn_off.return_value = True
    assert "desligada" in tools["turn_off_lights"].invoke({"light_name": "Fita Led"})
    fake_controller.turn_off.return_value = False
    assert "não encontrada" in tools["turn_off_lights"].invoke({"light_name": "X"})


def test_turn_on_specific(tools, fake_controller):
    fake_controller.turn_on.return_value = True
    assert "ligada" in tools["turn_on_lights"].invoke({"light_name": "Fita Led"})


def test_set_brightness_specific(tools, fake_controller):
    fake_controller.set_brightness.return_value = True
    out = tools["set_brightness"].invoke({"light_name": "Lâmpada 1", "brightness": 50})
    assert "50%" in out
    # 50% -> 127 em escala hue
    fake_controller.set_brightness.assert_called_once()
    assert fake_controller.set_brightness.call_args[0][1] == int((50 / 100) * 254)


def test_get_light_locations_all_specific_and_missing(fake_controller, fake_manager):
    from marvin_hue.chat.tools.light_tools import build_light_tools
    t = {x.name: x for x in build_light_tools(fake_controller, fake_manager)}
    all_out = t["get_light_locations"].invoke({"light_name": "all"})
    assert "Fita Led" in all_out and "25%" in all_out
    one = t["get_light_locations"].invoke({"light_name": "Fita Led"})
    assert "Fita Led" in one

    t_missing = {
        x.name: x
        for x in build_light_tools(fake_controller, fake_manager, locations_path="/nao/existe.json")
    }
    assert "não encontrado" in t_missing["get_light_locations"].invoke({"light_name": "all"})


def test_save_current_config_no_lights_on(fake_controller, fake_manager):
    """Sem lâmpadas ligadas: não salva."""
    from marvin_hue.chat.tools.light_tools import build_light_tools
    fake_controller.get_lights_status.return_value = [
        {"name": "Fita Led", "on": False, "brightness": 0, "reachable": True,
         "color": {"r": 0, "g": 0, "b": 0}},
    ]
    fake_manager.get_config.side_effect = lambda n: None
    t = {x.name: x for x in build_light_tools(fake_controller, fake_manager)}
    out = t["save_current_config"].invoke({"config_name": "vazia", "description": "x"})
    assert "Nenhuma lâmpada ligada" in out
