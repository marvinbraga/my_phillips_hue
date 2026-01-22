"""
Unit tests for marvin_hue.basics module.

Tests the LightSetting, LightConfig, and LightSetupsManager classes
including file operations and configuration management.
"""

import json
from pathlib import Path

import pytest

from marvin_hue.basics import LightConfig, LightSetting, LightSetupsManager
from marvin_hue.colors import Color


class TestLightSetting:
    """Tests for LightSetting class."""

    def test_light_setting_creation(self):
        """Test creating a LightSetting instance."""
        color = Color(255, 128, 64, 200)
        setting = LightSetting("Test Light", color)

        assert setting.light_name == "Test Light"
        assert setting.color == color

    def test_light_setting_to_dict(self, sample_light_setting):
        """Test LightSetting serialization to dict."""
        result = sample_light_setting.to_dict()

        assert isinstance(result, dict)
        assert "light_name" in result
        assert "color" in result
        assert result["light_name"] == sample_light_setting.light_name
        assert isinstance(result["color"], dict)

    def test_light_setting_color_dict_structure(self, sample_light_setting):
        """Test that color in to_dict is properly structured."""
        result = sample_light_setting.to_dict()
        color_dict = result["color"]

        assert "red" in color_dict
        assert "green" in color_dict
        assert "blue" in color_dict
        assert "brightness" in color_dict

    def test_light_setting_with_different_colors(self):
        """Test LightSetting with various color values."""
        test_cases = [
            ("Light 1", Color(255, 0, 0, 254)),
            ("Light 2", Color(0, 255, 0, 200)),
            ("Light 3", Color(0, 0, 255, 150)),
            ("Light 4", Color(0, 0, 0, 0)),
        ]

        for light_name, color in test_cases:
            setting = LightSetting(light_name, color)
            assert setting.light_name == light_name
            assert setting.color == color


class TestLightConfig:
    """Tests for LightConfig class."""

    def test_light_config_creation(self, sample_light_config):
        """Test creating a LightConfig instance."""
        assert sample_light_config.name == "test_config"
        assert sample_light_config.description == "Test configuration for unit tests"
        assert isinstance(sample_light_config.settings, list)
        assert len(sample_light_config.settings) == 3

    def test_light_config_str_method(self, sample_light_config):
        """Test LightConfig string representation."""
        result = str(sample_light_config)
        assert result == sample_light_config.name

    def test_light_config_to_dict(self, sample_light_config):
        """Test LightConfig serialization to dict."""
        result = sample_light_config.to_dict()

        assert isinstance(result, dict)
        assert "name" in result
        assert "description" in result
        assert "settings" in result
        assert result["name"] == "test_config"
        assert isinstance(result["settings"], list)
        assert len(result["settings"]) == 3

    def test_light_config_settings_serialization(self, sample_light_config):
        """Test that settings are properly serialized in to_dict."""
        result = sample_light_config.to_dict()
        settings = result["settings"]

        for setting_dict in settings:
            assert "light_name" in setting_dict
            assert "color" in setting_dict
            assert isinstance(setting_dict["color"], dict)

    def test_light_config_empty_settings(self):
        """Test LightConfig with empty settings list."""
        config = LightConfig("empty_config", [], "Empty configuration")

        assert config.name == "empty_config"
        assert config.settings == []
        assert len(config.settings) == 0

    def test_light_config_without_description(self):
        """Test LightConfig without description (default empty string)."""
        settings = [LightSetting("Light 1", Color())]
        config = LightConfig("minimal_config", settings)

        assert config.name == "minimal_config"
        assert config.description == ""


class TestLightSetupsManager:
    """Tests for LightSetupsManager class."""

    def test_manager_creation(self, sample_setups_json):
        """Test creating a LightSetupsManager instance."""
        manager = LightSetupsManager(str(sample_setups_json))

        assert manager is not None
        assert isinstance(manager.data, dict)
        assert isinstance(manager.configs, list)

    def test_manager_loads_configs(self, sample_setups_json):
        """Test that manager loads configurations from JSON."""
        manager = LightSetupsManager(str(sample_setups_json))

        assert len(manager.configs) == 2
        assert any(cfg.name == "concentration" for cfg in manager.configs)
        assert any(cfg.name == "relax" for cfg in manager.configs)

    def test_manager_get_config(self, sample_setups_json):
        """Test getting a configuration by name."""
        manager = LightSetupsManager(str(sample_setups_json))

        config = manager.get_config("concentration")
        assert config is not None
        assert config.name == "concentration"

    def test_manager_get_nonexistent_config(self, sample_setups_json):
        """Test getting a configuration that doesn't exist."""
        manager = LightSetupsManager(str(sample_setups_json))

        config = manager.get_config("nonexistent")
        assert config is None

    def test_manager_config_structure(self, sample_setups_json):
        """Test that loaded configs have correct structure."""
        manager = LightSetupsManager(str(sample_setups_json))
        config = manager.get_config("concentration")

        assert isinstance(config, LightConfig)
        assert config.name == "concentration"
        assert config.description == "Ambiente que estimula a concentração"
        assert isinstance(config.settings, list)
        assert len(config.settings) == 2

    def test_manager_light_settings_structure(self, sample_setups_json):
        """Test that LightSettings are properly created from JSON."""
        manager = LightSetupsManager(str(sample_setups_json))
        config = manager.get_config("concentration")

        for setting in config.settings:
            assert isinstance(setting, LightSetting)
            assert isinstance(setting.light_name, str)
            assert isinstance(setting.color, Color)

    def test_manager_color_values(self, sample_setups_json):
        """Test that color values are correctly loaded."""
        manager = LightSetupsManager(str(sample_setups_json))
        config = manager.get_config("concentration")

        first_setting = config.settings[0]
        assert first_setting.color.red == 255
        assert first_setting.color.green == 244
        assert first_setting.color.blue == 229
        assert first_setting.color.brightness == 254  # Max valid brightness is 254


class TestLightSetupsManagerFileOperations:
    """Tests for file operations in LightSetupsManager."""

    def test_manager_file_not_found(self, tmp_path):
        """Test that FileNotFoundError is raised for nonexistent file."""
        nonexistent_file = tmp_path / "nonexistent.json"

        with pytest.raises(FileNotFoundError):
            LightSetupsManager(str(nonexistent_file))

    def test_manager_load_invalid_json(self, tmp_path):
        """Test loading invalid JSON file."""
        invalid_json_file = tmp_path / "invalid.json"
        invalid_json_file.write_text("{invalid json content")

        # Manager should handle JSONDecodeError gracefully
        # (prints error but doesn't crash)
        try:
            manager = LightSetupsManager(str(invalid_json_file))
            # Should have empty data
            assert manager.data == {"setups": []}
            assert manager.configs == []
        except Exception as e:
            pytest.fail(f"Manager should handle invalid JSON gracefully: {e}")

    def test_manager_save(self, sample_setups_json, tmp_path):
        """Test saving configurations to file."""
        manager = LightSetupsManager(str(sample_setups_json))

        # Create a new save location
        save_file = tmp_path / "saved_setups.json"
        manager._filename = str(save_file)

        # Save
        result = manager.save()

        # Check that file was created
        assert save_file.exists()

        # Verify saved content
        with open(save_file, 'r', encoding='utf-8') as f:
            saved_data = json.load(f)

        assert "setups" in saved_data
        assert len(saved_data["setups"]) == 2

    def test_manager_save_and_reload(self, sample_setups_json, tmp_path):
        """Test that saved data can be reloaded correctly."""
        manager1 = LightSetupsManager(str(sample_setups_json))

        # Save to new location
        save_file = tmp_path / "test_save.json"
        manager1._filename = str(save_file)
        manager1.save()

        # Create new manager from saved file
        manager2 = LightSetupsManager(str(save_file))

        # Should have same configs
        assert len(manager2.configs) == len(manager1.configs)
        assert manager2.get_config("concentration") is not None
        assert manager2.get_config("relax") is not None

    def test_manager_data_property(self, sample_setups_json):
        """Test the data property returns correct structure."""
        manager = LightSetupsManager(str(sample_setups_json))

        data = manager.data
        assert isinstance(data, dict)
        assert "setups" in data
        assert isinstance(data["setups"], list)

    def test_manager_configs_property(self, sample_setups_json):
        """Test the configs property returns list of LightConfig."""
        manager = LightSetupsManager(str(sample_setups_json))

        configs = manager.configs
        assert isinstance(configs, list)
        for config in configs:
            assert isinstance(config, LightConfig)


class TestLightSetupsManagerUpdate:
    """Tests for the update method in LightSetupsManager."""

    def test_manager_update_method(self, sample_setups_json):
        """Test that update() rebuilds configs from data."""
        manager = LightSetupsManager(str(sample_setups_json))

        original_count = len(manager.configs)

        # Call update again
        manager.update()

        # Should have same number of configs
        assert len(manager.configs) == original_count

    def test_manager_update_creates_new_instances(self, sample_setups_json):
        """Test that update() creates new LightConfig instances."""
        manager = LightSetupsManager(str(sample_setups_json))

        config1 = manager.get_config("concentration")
        config1_id = id(config1)

        # Update configs
        manager.update()

        config2 = manager.get_config("concentration")
        config2_id = id(config2)

        # Should be different instances (new objects)
        assert config1_id != config2_id


class TestLightSetupsManagerEdgeCases:
    """Tests for edge cases in LightSetupsManager."""

    def test_manager_empty_setups(self, tmp_path):
        """Test manager with empty setups list."""
        empty_file = tmp_path / "empty.json"
        empty_file.write_text('{"setups": []}')

        manager = LightSetupsManager(str(empty_file))

        assert len(manager.configs) == 0
        assert manager.get_config("any") is None

    def test_manager_missing_setups_key(self, tmp_path):
        """Test manager with JSON missing 'setups' key."""
        no_setups_file = tmp_path / "no_setups.json"
        no_setups_file.write_text('{"other_key": []}')

        manager = LightSetupsManager(str(no_setups_file))

        # Should handle gracefully with empty list
        assert len(manager.configs) == 0

    def test_manager_unicode_content(self, tmp_path):
        """Test manager with Unicode characters in names/descriptions."""
        unicode_file = tmp_path / "unicode.json"
        data = {
            "setups": [
                {
                    "name": "café_☕",
                    "description": "Configuração com café ☕ e acentuação",
                    "settings": [
                        {
                            "light_name": "Lâmpada 1",
                            "color": {"red": 255, "green": 200, "blue": 150, "brightness": 200}
                        }
                    ]
                }
            ]
        }
        unicode_file.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')

        manager = LightSetupsManager(str(unicode_file))

        config = manager.get_config("café_☕")
        assert config is not None
        assert "café" in config.name
        assert "☕" in config.description
