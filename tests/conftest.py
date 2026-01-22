"""
Pytest configuration and shared fixtures for Marvin Hue tests.

This module provides reusable fixtures for testing the Marvin Hue application,
including mocks for hardware interactions and test clients for the API.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, Mock

import pytest
from fastapi.testclient import TestClient

from marvin_hue.basics import LightConfig, LightSetting
from marvin_hue.colors import Color


@pytest.fixture
def sample_color() -> Color:
    """Provides a sample Color instance for testing."""
    return Color(red=255, green=128, blue=64, brightness=200)


@pytest.fixture
def sample_colors() -> list[Color]:
    """Provides a list of sample Color instances for testing."""
    return [
        Color(255, 0, 0, 254),  # Red
        Color(0, 255, 0, 254),  # Green
        Color(0, 0, 255, 254),  # Blue
        Color(255, 255, 255, 254),  # White
        Color(0, 0, 0, 0),  # Black/Off
    ]


@pytest.fixture
def sample_light_setting() -> LightSetting:
    """Provides a sample LightSetting instance for testing."""
    return LightSetting("Test Light", Color(255, 200, 150, 200))


@pytest.fixture
def sample_light_config() -> LightConfig:
    """Provides a sample LightConfig instance for testing."""
    settings = [
        LightSetting("Lâmpada 1", Color(255, 244, 229, 254)),
        LightSetting("Lâmpada 2", Color(255, 244, 229, 254)),
        LightSetting("Hue Iris", Color(255, 147, 41, 180)),
    ]
    return LightConfig(
        name="test_config",
        settings=settings,
        description="Test configuration for unit tests"
    )


@pytest.fixture
def temp_json_file() -> Generator[Path, None, None]:
    """Provides a temporary JSON file path for testing file operations."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        filepath = Path(f.name)

    yield filepath

    # Cleanup
    if filepath.exists():
        filepath.unlink()


@pytest.fixture
def sample_setups_json(temp_json_file: Path) -> Path:
    """Creates a temporary setups.json file with sample data."""
    data = {
        "setups": [
            {
                "name": "concentration",
                "description": "Ambiente que estimula a concentração",
                "settings": [
                    {
                        "light_name": "Lâmpada 1",
                        "color": {"red": 255, "green": 244, "blue": 229, "brightness": 254}
                    },
                    {
                        "light_name": "Lâmpada 2",
                        "color": {"red": 255, "green": 244, "blue": 229, "brightness": 254}
                    }
                ]
            },
            {
                "name": "relax",
                "description": "Ambiente relaxante",
                "settings": [
                    {
                        "light_name": "Lâmpada 1",
                        "color": {"red": 255, "green": 147, "blue": 41, "brightness": 180}
                    }
                ]
            }
        ]
    }

    with open(temp_json_file, 'w', encoding='utf-8') as f:
        json.dump(data, f)

    return temp_json_file


@pytest.fixture
def mock_phue_light() -> Mock:
    """Provides a mock phue Light object."""
    light = Mock()
    light.name = "Test Light"
    light.on = True
    light.brightness = 254
    light.xy = [0.5, 0.5]
    light.reachable = True
    light.transitiontime = 0
    return light


@pytest.fixture
def mock_phue_bridge() -> Mock:
    """Provides a mock phue Bridge object."""
    bridge = Mock()
    bridge.ip = "192.168.1.100"

    # Create mock lights
    light1 = Mock()
    light1.name = "Lâmpada 1"
    light1.on = True
    light1.brightness = 254
    light1.xy = [0.5, 0.5]
    light1.reachable = True

    light2 = Mock()
    light2.name = "Lâmpada 2"
    light2.on = False
    light2.brightness = 0
    light2.xy = [0.3, 0.3]
    light2.reachable = True

    bridge.get_light_objects.return_value = [light1, light2]
    bridge.connect = Mock()
    bridge.groups = []

    return bridge


@pytest.fixture
def mock_hue_controller(mock_phue_bridge: Mock, monkeypatch):
    """Provides a mock HueController that doesn't connect to real hardware."""
    from marvin_hue.controllers import HueController

    # Patch the Bridge constructor to return our mock
    def mock_bridge_init(ip_address):
        return mock_phue_bridge

    monkeypatch.setattr("marvin_hue.controllers.Bridge", lambda ip: mock_phue_bridge)

    # Create controller (will use mocked bridge)
    controller = HueController("192.168.1.100")

    return controller


@pytest.fixture
def mock_light_setups_manager(sample_setups_json: Path, monkeypatch):
    """Provides a LightSetupsManager with test data."""
    from marvin_hue.basics import LightSetupsManager

    manager = LightSetupsManager(str(sample_setups_json))
    return manager


@pytest.fixture
def mock_screen_mirror():
    """Provides a mock ScreenMirror object."""
    mirror = Mock()
    mirror.is_running.return_value = False
    mirror.get_status.return_value = {
        "running": False,
        "fps": 25,
        "brightness": 200,
        "colors": {}
    }
    mirror.start = Mock()
    mirror.stop = Mock()
    mirror.fps = 25
    mirror.brightness = 200
    mirror.saturation_boost = 1.0
    mirror.smoothing_factor = 0.3
    mirror.transition_time = 0.1
    return mirror


@pytest.fixture
def fastapi_test_client(mock_hue_controller, mock_light_setups_manager, mock_screen_mirror, monkeypatch) -> TestClient:
    """Provides a FastAPI TestClient for integration tests."""
    # Set environment variables
    monkeypatch.setenv("BRIDGE_IP", "192.168.1.100")

    # Mock the dependencies in the new architecture
    from marvin_hue.api import dependencies
    import app

    # Store original values
    original_hue = dependencies._hue_controller
    original_manager = dependencies._manager
    original_mirror = dependencies._screen_mirror
    original_chat = dependencies._chat_agent

    # Set mocked instances using dependency setters
    dependencies.set_hue_controller(mock_hue_controller)
    dependencies.set_manager(mock_light_setups_manager)
    dependencies.set_screen_mirror(mock_screen_mirror)
    dependencies.set_chat_agent(None)  # Disable chat agent for tests

    # Create test client
    client = TestClient(app.app)

    yield client

    # Restore original values
    dependencies._hue_controller = original_hue
    dependencies._manager = original_manager
    dependencies._screen_mirror = original_mirror
    dependencies._chat_agent = original_chat


@pytest.fixture
def edge_case_colors() -> list[tuple[int, int, int, int]]:
    """Provides edge case color values for testing validation."""
    return [
        (0, 0, 0, 0),  # Minimum values
        (255, 255, 255, 254),  # Maximum valid values
        (128, 128, 128, 127),  # Mid values
        (255, 0, 0, 254),  # Pure red
        (0, 255, 0, 254),  # Pure green
        (0, 0, 255, 254),  # Pure blue
    ]


@pytest.fixture
def invalid_color_values() -> list[tuple[int, int, int, int, str]]:
    """Provides invalid color values for validation testing."""
    return [
        (-1, 0, 0, 0, "negative red"),
        (0, -1, 0, 0, "negative green"),
        (0, 0, -1, 0, "negative blue"),
        (0, 0, 0, -1, "negative brightness"),
        (256, 0, 0, 0, "red too high"),
        (0, 256, 0, 0, "green too high"),
        (0, 0, 256, 0, "blue too high"),
        (0, 0, 0, 255, "brightness too high"),
    ]
