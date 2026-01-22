"""
Tests for the setup_builder module.

These tests verify that the new JSON-based configuration system works correctly
and is backward compatible with the old class-based system.
"""

import json
import os
import pytest
from marvin_hue.setup_builder import (
    LightConfigBuilder,
    STANDARD_LIGHTS,
)
from marvin_hue.basics import LightConfig
from marvin_hue.colors import Color


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


class TestBackwardCompatibility:
    """Tests for backward compatibility with legacy setup classes."""

    def test_legacy_class_import(self):
        """Test that legacy classes can still be imported and instantiated."""
        import warnings

        # Capture warnings during import
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from marvin_hue.setups import SetupConcentration

            config = SetupConcentration()

            # Check that a deprecation warning was issued
            assert len(w) >= 1
            assert any(
                issubclass(warning.category, DeprecationWarning) for warning in w
            )

        assert isinstance(config, LightConfig)
        assert config.name == "concentration"
        assert len(config.settings) > 0

    def test_legacy_enum_compatibility(self):
        """Test that the old LightConfigEnum still works."""
        import warnings

        # Capture warnings during import
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from marvin_hue.factories import LightConfigEnum

            # Check that a deprecation warning was issued
            assert len(w) >= 1
            assert any(
                issubclass(warning.category, DeprecationWarning) for warning in w
            )

        # Enum should still be functional
        assert hasattr(LightConfigEnum, "SETUP_CONCENTRATION")
        config = LightConfigEnum.SETUP_CONCENTRATION.get_instance()
        assert isinstance(config, LightConfig)

    def test_all_legacy_classes_load_from_json(self):
        """Test that legacy classes successfully load configurations from JSON."""
        import warnings

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            from marvin_hue.setups import (
                PurpleHome,
                CyberpunkNight,
                ArcoIrisAposChuva,
            )

            # These classes load from JSON internally
            config1 = PurpleHome()
            config2 = CyberpunkNight()
            config3 = ArcoIrisAposChuva()

        assert config1.name == "purple_home"
        assert config2.name == "cyberpunk_night"
        assert config3.name == "arco_iris_apos_chuva"

        # All should have settings
        assert len(config1.settings) > 0
        assert len(config2.settings) > 0
        assert len(config3.settings) > 0


class TestNewRegistry:
    """Tests for the new LightConfigRegistry."""

    def test_registry_loads_configs(self):
        """Test that the registry loads configurations from JSON."""
        from marvin_hue.factories_new import get_registry

        registry = get_registry()

        assert len(registry.config_names) > 0
        assert "concentration" in registry.config_names

    def test_get_config_by_name(self):
        """Test retrieving a configuration by name."""
        from marvin_hue.factories_new import get_config

        config = get_config("concentration")

        assert config is not None
        assert config.name == "concentration"
        assert isinstance(config, LightConfig)
        assert len(config.settings) > 0

    def test_get_nonexistent_config(self):
        """Test retrieving a non-existent configuration."""
        from marvin_hue.factories_new import get_config

        config = get_config("nonexistent_config_xyz")

        assert config is None

    def test_list_all_configs(self):
        """Test listing all available configurations."""
        from marvin_hue.factories_new import list_all_configs

        configs = list_all_configs()

        assert isinstance(configs, list)
        assert len(configs) > 0

        # Check structure
        first_config = configs[0]
        assert "name" in first_config
        assert "description" in first_config

        # Check for known configs
        config_names = [c["name"] for c in configs]
        assert "concentration" in config_names
        assert "cyberpunk_night" in config_names

    def test_registry_singleton(self):
        """Test that the registry is a singleton."""
        from marvin_hue.factories_new import LightConfigRegistry

        registry1 = LightConfigRegistry()
        registry2 = LightConfigRegistry()

        assert registry1 is registry2


class TestEquivalence:
    """Tests to verify that new system produces equivalent results to old system."""

    def test_concentration_equivalence(self):
        """Test that concentration config is equivalent in both systems."""
        import warnings

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            from marvin_hue.setups import SetupConcentration
            from marvin_hue.factories_new import get_config

            # Get from old system
            old_config = SetupConcentration()

            # Get from new system
            new_config = get_config("concentration")

        assert old_config.name == new_config.name

        # JSON may have more lights than the old class (e.g., Lâmpada 3)
        # Check that all lights from old config are in new config
        old_light_names = {s.light_name for s in old_config.settings}
        new_light_names = {s.light_name for s in new_config.settings}

        assert old_light_names.issubset(new_light_names), (
            f"Old config lights {old_light_names} not all in new config {new_light_names}"
        )

        # For lights that exist in both, check they have the same colors
        old_settings_by_name = {s.light_name: s for s in old_config.settings}
        new_settings_by_name = {s.light_name: s for s in new_config.settings}

        for light_name in old_light_names:
            old_setting = old_settings_by_name[light_name]
            new_setting = new_settings_by_name[light_name]

            assert old_setting.color.red == new_setting.color.red
            assert old_setting.color.green == new_setting.color.green
            assert old_setting.color.blue == new_setting.color.blue
            assert old_setting.color.brightness == new_setting.color.brightness

    def test_all_enum_configs_available_in_new_system(self):
        """Test that all configs from enum are available in new system."""
        import warnings

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            from marvin_hue.factories import LightConfigEnum
            from marvin_hue.factories_new import get_config

            # Check each enum member
            for enum_member in LightConfigEnum:
                old_config = enum_member.get_instance()
                new_config = get_config(old_config.name)

                assert new_config is not None, (
                    f"Config {old_config.name} not found in new system"
                )
                assert new_config.name == old_config.name


class TestStandardLights:
    """Tests for STANDARD_LIGHTS constant."""

    def test_standard_lights_list(self):
        """Test that STANDARD_LIGHTS contains expected light names."""
        assert isinstance(STANDARD_LIGHTS, list)
        assert len(STANDARD_LIGHTS) > 0

        # Check for known lights
        assert "Lâmpada 1" in STANDARD_LIGHTS
        assert "Hue Iris" in STANDARD_LIGHTS
        assert "Fita Led" in STANDARD_LIGHTS


class TestJSONIntegration:
    """Tests for JSON file integration."""

    def test_setups_json_exists(self):
        """Test that setups.json file exists."""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        json_path = os.path.join(base_dir, ".res", "setups.json")

        assert os.path.exists(json_path), "setups.json file not found"

    def test_setups_json_valid(self):
        """Test that setups.json contains valid data."""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        json_path = os.path.join(base_dir, ".res", "setups.json")

        with open(json_path, "r", encoding="utf-8") as f:
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
        from marvin_hue.factories_new import get_registry

        registry = get_registry()

        # Try to get each config - this will fail if structure is invalid
        for name in registry.config_names:
            config = registry.get_config(name)
            assert config is not None
            assert isinstance(config, LightConfig)
            assert len(config.settings) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
