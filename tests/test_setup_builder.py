"""
Tests for the setup_builder module.

These tests verify that JSON-based configurations work with LightConfigBuilder
and LightSetupsManager (canonical catalog path).
"""

import json
import os

import pytest

from marvin_hue.basics import LightConfig, LightSetupsManager
from marvin_hue.colors import Color
from marvin_hue.setup_builder import (
    STANDARD_LIGHTS,
    LightConfigBuilder,
)


def _repo_setups_path() -> str:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, ".res", "setups.json")


def _production_manager() -> LightSetupsManager:
    return LightSetupsManager(_repo_setups_path())


class TestLightConfigBuilder:
    """Tests for the LightConfigBuilder class."""

    def test_from_dict_basic(self):
        """Test creating a config from a simple dictionary."""
        config_dict = {
            "name": "test_config",
            "description": "Test configuration",
            "settings": [
                {
                    "light_name": "Lâmpada 1",
                    "color": {"red": 255, "green": 200, "blue": 100, "brightness": 150},
                },
                {
                    "light_name": "Lâmpada 2",
                    "color": {"red": 100, "green": 255, "blue": 200, "brightness": 120},
                },
            ],
        }

        config = LightConfigBuilder.from_dict(config_dict)

        assert isinstance(config, LightConfig)
        assert config.name == "test_config"
        assert config.description == "Test configuration"
        assert len(config.settings) == 2
        assert config.settings[0].light_name == "Lâmpada 1"
        assert config.settings[0].color.red == 255
        assert config.settings[0].color.brightness == 150

    def test_from_dict_missing_fields(self):
        """Test handling of missing optional fields."""
        config_dict = {
            "name": "minimal_config",
            "settings": [
                {
                    "light_name": "Lâmpada 1",
                    "color": {"red": 255, "green": 255, "blue": 255, "brightness": 200},
                }
            ],
        }

        config = LightConfigBuilder.from_dict(config_dict)

        assert config.name == "minimal_config"
        assert config.description == ""
        assert len(config.settings) == 1

    def test_from_dict_invalid_data(self):
        """Test error handling for invalid configuration data."""
        invalid_config = {
            "name": "invalid",
            # Missing required 'settings' field
        }

        # Should not raise, but return config with empty settings
        config = LightConfigBuilder.from_dict(invalid_config)
        assert len(config.settings) == 0

    def test_create_uniform(self):
        """Test creating a uniform color configuration."""
        blue_color = Color(0, 0, 255, 200)
        config = LightConfigBuilder.create_uniform(
            "all_blue", blue_color, "Everything blue"
        )

        assert config.name == "all_blue"
        assert config.description == "Everything blue"
        assert len(config.settings) == len(STANDARD_LIGHTS)

        # All lights should have the same color
        for setting in config.settings:
            assert setting.color.red == 0
            assert setting.color.green == 0
            assert setting.color.blue == 255
            assert setting.color.brightness == 200

    def test_create_uniform_custom_lights(self):
        """Test creating uniform config with custom light list."""
        custom_lights = ["Light 1", "Light 2"]
        color = Color(255, 0, 0, 150)

        config = LightConfigBuilder.create_uniform(
            "custom_red", color, lights=custom_lights
        )

        assert len(config.settings) == 2
        assert config.settings[0].light_name == "Light 1"
        assert config.settings[1].light_name == "Light 2"

    def test_create_custom(self):
        """Test creating a custom color configuration."""
        light_colors = {
            "Lâmpada 1": Color(255, 0, 0, 200),
            "Lâmpada 2": Color(0, 255, 0, 200),
            "Hue Iris": Color(0, 0, 255, 150),
        }

        config = LightConfigBuilder.create_custom(
            "rgb_mix", light_colors, "Red, Green, Blue mix"
        )

        assert config.name == "rgb_mix"
        assert config.description == "Red, Green, Blue mix"
        assert len(config.settings) == 3

        # Check individual colors
        assert config.settings[0].light_name == "Lâmpada 1"
        assert config.settings[0].color.red == 255
        assert config.settings[1].color.green == 255
        assert config.settings[2].color.blue == 255

    def test_validate_config_valid(self):
        """Test validation of a valid configuration."""
        valid_config = {
            "name": "valid",
            "settings": [
                {
                    "light_name": "Lâmpada 1",
                    "color": {"red": 255, "green": 255, "blue": 255, "brightness": 200},
                }
            ],
        }

        assert LightConfigBuilder.validate_config(valid_config) is True

    def test_validate_config_invalid_structure(self):
        """Test validation of invalid configurations."""
        # Not a dict
        assert LightConfigBuilder.validate_config("not a dict") is False

        # Missing name
        assert LightConfigBuilder.validate_config({"settings": []}) is False

        # Missing settings
        assert LightConfigBuilder.validate_config({"name": "test"}) is False

        # Invalid settings structure
        invalid_settings = {
            "name": "test",
            "settings": [
                {"light_name": "Light 1"}  # Missing color
            ],
        }
        assert LightConfigBuilder.validate_config(invalid_settings) is False

        # Invalid color structure
        invalid_color = {
            "name": "test",
            "settings": [
                {
                    "light_name": "Light 1",
                    "color": {"red": 255},  # Missing green, blue, brightness
                }
            ],
        }
        assert LightConfigBuilder.validate_config(invalid_color) is False


class TestJsonSetupsCatalog:
    """JSON catalog via LightSetupsManager (replaces class/enum catalogs)."""

    def test_concentration_loads_from_json(self):
        config = _production_manager().get_config("concentration")

        assert config is not None
        assert isinstance(config, LightConfig)
        assert config.name == "concentration"
        assert len(config.settings) > 0

    def test_named_setups_load_from_json(self):
        manager = _production_manager()
        for name in ("purple_home", "cyberpunk_night", "arco_iris_apos_chuva"):
            config = manager.get_config(name)
            assert config is not None
            assert config.name == name
            assert len(config.settings) > 0

    def test_manager_loads_configs(self):
        manager = _production_manager()
        names = [config.name for config in manager.configs]

        assert len(names) > 0
        assert "concentration" in names

    def test_get_config_by_name(self):
        config = _production_manager().get_config("concentration")

        assert config is not None
        assert config.name == "concentration"
        assert isinstance(config, LightConfig)
        assert len(config.settings) > 0

    def test_get_nonexistent_config(self):
        config = _production_manager().get_config("nonexistent_config_xyz")
        assert config is None

    def test_list_all_configs(self):
        configs = _production_manager().configs

        assert isinstance(configs, list)
        assert len(configs) > 0
        assert configs[0].name
        assert isinstance(configs[0].description, str)

        names = [config.name for config in configs]
        assert "concentration" in names
        assert "cyberpunk_night" in names


class TestJsonCoversStandardLights:
    """Production JSON scenes cover the physical STANDARD_LIGHTS set."""

    def test_concentration_includes_standard_lights(self):
        config = _production_manager().get_config("concentration")
        assert config is not None
        light_names = {setting.light_name for setting in config.settings}
        assert set(STANDARD_LIGHTS).issubset(light_names)
        assert "Lâmpada 3" in light_names

    def test_known_setups_available_in_json(self):
        manager = _production_manager()
        for name in (
            "concentration",
            "cyberpunk_night",
            "purple_home",
            "arco_iris_apos_chuva",
        ):
            config = manager.get_config(name)
            assert config is not None, f"Config {name} not found in JSON catalog"
            assert config.name == name


class TestStandardLights:
    """Tests for STANDARD_LIGHTS constant."""

    def test_standard_lights_list(self):
        """STANDARD_LIGHTS is the 9 physical lights, ceiling order 1–4."""
        assert isinstance(STANDARD_LIGHTS, list)
        assert len(STANDARD_LIGHTS) == 9
        assert STANDARD_LIGHTS[:4] == [
            "Lâmpada 1",
            "Lâmpada 2",
            "Lâmpada 3",
            "Lâmpada 4",
        ]
        assert "Lâmpada 3" in STANDARD_LIGHTS
        assert "Hue Iris" in STANDARD_LIGHTS
        assert "Fita Led" in STANDARD_LIGHTS
        assert STANDARD_LIGHTS[4:] == [
            "Hue Iris",
            "Hue Play 1",
            "Hue Play 2",
            "Fita Led",
            "Led cima",
        ]


class TestJSONIntegration:
    """Tests for JSON file integration."""

    def test_setups_json_exists(self):
        """Test that setups.json file exists."""
        assert os.path.exists(_repo_setups_path()), "setups.json file not found"

    def test_setups_json_valid(self):
        """Test that setups.json contains valid data."""
        with open(_repo_setups_path(), "r", encoding="utf-8") as f:
            data = json.load(f)

        assert "setups" in data
        assert isinstance(data["setups"], list)
        assert len(data["setups"]) > 0

        # Validate first setup structure
        first_setup = data["setups"][0]
        assert "name" in first_setup
        assert "description" in first_setup
        assert "settings" in first_setup
        assert isinstance(first_setup["settings"], list)

    def test_all_setups_valid_structure(self):
        """Test that all setups in JSON have valid structure."""
        manager = _production_manager()

        for config in manager.configs:
            assert isinstance(config, LightConfig)
            assert config.name
            assert len(config.settings) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
