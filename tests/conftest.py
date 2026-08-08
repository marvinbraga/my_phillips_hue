"""
Pytest configuration and shared fixtures for Marvin Hue tests.

This module provides reusable fixtures for testing the Marvin Hue application,
including mocks for hardware interactions and test clients for the API.
"""

import json
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import Mock

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
        description="Test configuration for unit tests",
    )


@pytest.fixture
def temp_json_file() -> Generator[Path, None, None]:
    """Provides a temporary JSON file path for testing file operations."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
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
                        "color": {
                            "red": 255,
                            "green": 244,
                            "blue": 229,
                            "brightness": 254,
                        },
                    },
                    {
                        "light_name": "Lâmpada 2",
                        "color": {
                            "red": 255,
                            "green": 244,
                            "blue": 229,
                            "brightness": 254,
                        },
                    },
                ],
            },
            {
                "name": "relax",
                "description": "Ambiente relaxante",
                "settings": [
                    {
                        "light_name": "Lâmpada 1",
                        "color": {
                            "red": 255,
                            "green": 147,
                            "blue": 41,
                            "brightness": 180,
                        },
                    }
                ],
            },
        ]
    }

    with open(temp_json_file, "w", encoding="utf-8") as f:
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
        "colors": {},
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
def mock_audio_mirror():
    """Provides a mock AudioMirror object."""
    mirror = Mock()
    mirror.is_running.return_value = False
    mirror.get_status.return_value = {
        "running": False,
        "mode": "audio",
        "fps": 30,
        "brightness": 200,
        "colors": {},
        "bass": 0.0,
        "mid": 0.0,
        "treble": 0.0,
    }
    mirror.start = Mock()
    mirror.stop = Mock()
    mirror.fps = 30
    mirror.brightness = 200
    mirror.smoothing_factor = 0.45
    mirror.transition_time = 1
    mirror.energy_gain = 1.2
    return mirror


@pytest.fixture
def fastapi_test_client(
    mock_hue_controller,
    mock_light_setups_manager,
    mock_screen_mirror,
    mock_audio_mirror,
    monkeypatch,
    tmp_path,
) -> Generator:
    """Provides a FastAPI TestClient for integration tests.

    Bootstraps light registry on a temp SQLite via asyncio.run (sync fixture;
    no running loop under TestClient setup).
    """
    import asyncio

    monkeypatch.setenv("BRIDGE_IP", "192.168.1.100")
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "test_marvin_hue.sqlite"))

    from marvin_hue.api import dependencies
    import app

    original_hue = dependencies._hue_controller
    original_manager = dependencies._manager
    original_mirror = dependencies._screen_mirror
    original_audio = getattr(dependencies, "_audio_mirror", None)
    original_chat = dependencies._chat_agent
    original_chat_reason = dependencies._chat_unavailable_reason
    original_registry = getattr(dependencies, "_light_registry_service", None)

    dependencies.set_hue_controller(mock_hue_controller)
    dependencies.set_manager(mock_light_setups_manager)
    dependencies.set_screen_mirror(mock_screen_mirror)
    dependencies.set_audio_mirror(mock_audio_mirror)
    # Disable chat agent; reason simula falha de init sem secrets
    dependencies.set_chat_agent(
        None, reason="Provider 'xai' sem XAI_API_KEY configurada."
    )

    db_path = str(tmp_path / "test_marvin_hue.sqlite")

    original_group = getattr(dependencies, "_group_service", None)
    original_history = getattr(dependencies, "_scene_history_service", None)
    original_schedule = getattr(dependencies, "_schedule_service", None)
    original_runner = getattr(dependencies, "_schedule_runner", None)

    async def _bootstrap():
        from marvin_hue.persistence.schema import init_db
        from marvin_hue.persistence.light_repository import (
            SqliteLightRegistryRepository,
        )
        from marvin_hue.persistence.group_repository import SqliteGroupRepository
        from marvin_hue.persistence.scene_history_repository import (
            SqliteSceneHistoryRepository,
        )
        from marvin_hue.persistence.schedule_repository import SqliteScheduleRepository
        from marvin_hue.services.light_registry import LightRegistryService
        from marvin_hue.services.group_service import GroupService
        from marvin_hue.services.scene_history import SceneHistoryService
        from marvin_hue.services.schedule_service import ScheduleService

        await init_db(db_path)
        light_repo = await SqliteLightRegistryRepository.open(db_path)
        group_repo = await SqliteGroupRepository.open(db_path)
        history_repo = await SqliteSceneHistoryRepository.open(db_path)
        schedule_repo = await SqliteScheduleRepository.open(db_path)
        light_svc = LightRegistryService(light_repo, bridge=mock_hue_controller)
        group_svc = GroupService(group_repo)
        history_svc = SceneHistoryService(history_repo)
        schedule_svc = ScheduleService(
            schedule_repo,
            hue=mock_hue_controller,
            manager=mock_light_setups_manager,
            group_service=group_svc,
        )
        return light_svc, group_svc, history_svc, schedule_svc

    light_svc, group_svc, history_svc, schedule_svc = asyncio.run(_bootstrap())
    dependencies.set_light_registry_service(light_svc)
    dependencies.set_group_service(group_svc)
    dependencies.set_scene_history_service(history_svc)
    dependencies.set_schedule_service(schedule_svc)

    client = TestClient(app.app)
    yield client

    async def _teardown():
        await schedule_svc.aclose()
        await history_svc.aclose()
        await group_svc.aclose()
        await light_svc.aclose()

    asyncio.run(_teardown())
    dependencies._hue_controller = original_hue
    dependencies._manager = original_manager
    dependencies._screen_mirror = original_mirror
    dependencies._audio_mirror = original_audio
    dependencies._chat_agent = original_chat
    dependencies._chat_unavailable_reason = original_chat_reason
    dependencies._light_registry_service = original_registry
    dependencies._group_service = original_group
    dependencies._scene_history_service = original_history
    dependencies._schedule_service = original_schedule
    dependencies._schedule_runner = original_runner


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
