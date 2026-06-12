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
