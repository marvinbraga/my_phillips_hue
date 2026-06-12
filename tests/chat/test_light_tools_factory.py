"""build_light_tools deve criar tools com closures, sem estado global."""
from __future__ import annotations

import pytest


def test_build_light_tools_returns_bound_tools(fake_controller, fake_manager):
    from marvin_hue.chat.tools.light_tools import build_light_tools
    from langchain_core.tools import BaseTool

    tools = build_light_tools(fake_controller, fake_manager)
    expected = {
        "list_lights", "get_light_status", "set_light_color", "apply_config",
        "list_configs", "turn_off_lights", "turn_on_lights", "set_brightness",
        "save_current_config", "get_light_locations",
    }
    assert expected <= {t.name for t in tools}  # âncora por NOME, não por contagem exata
    assert len(tools) >= 10                     # sanity
    assert all(isinstance(t, BaseTool) for t in tools)

    by_name = {t.name: t for t in tools}
    out = by_name["list_lights"].invoke({})
    assert "Lâmpada 1" in out
    fake_controller.list_lights.assert_called_once()


def test_no_global_state_required(fake_controller, fake_manager):
    """Duas instâncias de tools usam controllers independentes (sem global)."""
    from marvin_hue.chat.tools.light_tools import build_light_tools

    c2 = type(fake_controller)()
    c2.list_lights.return_value = ["Outra"]
    tools_a = {t.name: t for t in build_light_tools(fake_controller, fake_manager)}
    tools_b = {t.name: t for t in build_light_tools(c2, fake_manager)}

    assert "Lâmpada 1" in tools_a["list_lights"].invoke({})
    assert "Outra" in tools_b["list_lights"].invoke({})


def _tools(fake_controller, fake_manager):
    from marvin_hue.chat.tools.light_tools import build_light_tools
    return {t.name: t for t in build_light_tools(fake_controller, fake_manager)}


def test_set_light_color_uses_controller(fake_controller, fake_manager):
    tools = _tools(fake_controller, fake_manager)
    out = tools["set_light_color"].invoke(
        {"light_name": "Lâmpada 1", "red": 255, "green": 0, "blue": 0, "brightness": 200}
    )
    assert "Lâmpada 1" in out
    fake_controller.set_light_color.assert_called_once()


def test_set_brightness_all_delegates_to_set_all_brightness(fake_controller, fake_manager):
    tools = _tools(fake_controller, fake_manager)
    tools["set_brightness"].invoke({"light_name": "all", "brightness": 100})
    # 100% -> 254 em escala hue; delega ao método público (clamp por lâmpada no controller).
    fake_controller.set_all_brightness.assert_called_once_with(254)


def test_turn_on_all_delegates_to_set_all(fake_controller, fake_manager):
    tools = _tools(fake_controller, fake_manager)
    tools["turn_on_lights"].invoke({"light_name": "all"})
    fake_controller.set_all.assert_called_once_with(True)


def test_save_current_config_dedup_blocks_existing(fake_controller, fake_manager):
    """Se já existe um preset com o nome, NÃO salva (dedup)."""
    tools = _tools(fake_controller, fake_manager)
    out = tools["save_current_config"].invoke(
        {"config_name": "noite_relaxante", "description": "x"}  # já existe no fake_manager
    )
    assert "Já existe" in out
    fake_manager.save.assert_not_called()


def test_save_current_config_saves_new(fake_controller, fake_manager):
    """Nome novo: captura lâmpadas ligadas e salva via manager.save()."""
    tools = _tools(fake_controller, fake_manager)
    out = tools["save_current_config"].invoke(
        {"config_name": "cena_nova", "description": "uma cena"}
    )
    assert "salva com sucesso" in out
    fake_manager.save.assert_called_once()
