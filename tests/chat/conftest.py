"""Fixtures compartilhadas para os testes do módulo de chat."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from marvin_hue.basics import LightConfig, LightSetting
from marvin_hue.colors import Color


@pytest.fixture
def fake_controller() -> MagicMock:
    """HueController fake com API pública estável e sem bridge."""
    controller = MagicMock()
    controller.list_lights.return_value = ["Lâmpada 1", "Fita Led", "Led cima"]
    controller.get_lights_status.return_value = [
        {"name": "Lâmpada 1", "on": True, "brightness": 200,
         "reachable": True, "color": {"r": 255, "g": 244, "b": 229}},
        {"name": "Fita Led", "on": True, "brightness": 50,
         "reachable": True, "color": {"r": 255, "g": 0, "b": 0}},
        {"name": "Led cima", "on": False, "brightness": 0,
         "reachable": True, "color": {"r": 50, "g": 50, "b": 50}},
    ]
    return controller


@pytest.fixture
def fake_manager() -> MagicMock:
    """LightSetupsManager fake com alguns presets."""
    manager = MagicMock()
    cfg = LightConfig(
        name="noite_relaxante",
        settings=[LightSetting("Lâmpada 1", Color(0, 0, 255, 120))],
        description="Ambiente calmo azul",
    )
    manager.configs = [cfg]
    manager.get_config.side_effect = lambda n: next(
        (c for c in manager.configs if c.name == n), None
    )
    return manager
