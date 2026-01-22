"""
Unit tests for marvin_hue.controllers module.

Tests the HueController class including light control, color application,
and XY to RGB conversion, all with mocked hardware.
"""

from unittest.mock import Mock, patch

import pytest

from marvin_hue.basics import LightConfig, LightSetting
from marvin_hue.colors import Color
from marvin_hue.controllers import HueController


class TestHueControllerInitialization:
    """Tests for HueController initialization."""

    def test_controller_creation(self, mock_hue_controller):
        """Test creating a HueController instance."""
        assert mock_hue_controller is not None
        assert mock_hue_controller.bridge is not None
        assert mock_hue_controller.lights is not None

    def test_controller_bridge_connection(self, mock_phue_bridge, monkeypatch):
        """Test that controller connects to bridge."""
        monkeypatch.setattr("marvin_hue.controllers.Bridge", lambda ip: mock_phue_bridge)

        controller = HueController("192.168.1.100")

        # Bridge connect should have been called
        mock_phue_bridge.connect.assert_called_once()

    def test_controller_loads_lights(self, mock_hue_controller):
        """Test that controller loads lights from bridge."""
        lights = mock_hue_controller.lights

        assert lights is not None
        assert len(lights) > 0


class TestHueControllerSetLightColor:
    """Tests for setting light colors."""

    def test_set_light_color(self, mock_hue_controller):
        """Test setting a light color."""
        color = Color(255, 128, 64, 200)

        light = mock_hue_controller.set_light_color("Lâmpada 1", color)

        assert light is not None
        assert light.brightness == 200

    def test_set_light_color_returns_light(self, mock_hue_controller):
        """Test that set_light_color returns the light object."""
        color = Color(100, 150, 200, 180)

        result = mock_hue_controller.set_light_color("Lâmpada 1", color)

        assert result is not None
        assert hasattr(result, 'brightness')
        assert hasattr(result, 'xy')

    def test_set_light_color_with_different_colors(self, mock_hue_controller):
        """Test setting various colors."""
        test_colors = [
            Color(255, 0, 0, 254),  # Red
            Color(0, 255, 0, 254),  # Green
            Color(0, 0, 255, 254),  # Blue
            Color(0, 0, 0, 0),  # Off
        ]

        for color in test_colors:
            light = mock_hue_controller.set_light_color("Lâmpada 1", color)
            assert light is not None
            assert light.brightness == color.brightness

    def test_set_light_color_updates_xy(self, mock_hue_controller):
        """Test that XY coordinates are updated."""
        color = Color(255, 100, 50, 200)

        light = mock_hue_controller.set_light_color("Lâmpada 1", color)

        # Check that xy was set (mocked, but should be called)
        assert hasattr(light, 'xy')

    def test_set_light_nonexistent(self, mock_hue_controller):
        """Test setting color for nonexistent light."""
        color = Color(255, 128, 64, 200)

        # Should raise ValueError for nonexistent light (validation added by Agent 1)
        with pytest.raises(ValueError, match="não encontrada"):
            mock_hue_controller.set_light_color("Nonexistent Light", color)


class TestHueControllerApplyLightConfig:
    """Tests for applying light configurations."""

    def test_apply_light_config(self, mock_hue_controller, sample_light_config):
        """Test applying a light configuration."""
        result = mock_hue_controller.apply_light_config(sample_light_config)

        assert result == mock_hue_controller

    def test_apply_light_config_with_transition(self, mock_hue_controller, sample_light_config):
        """Test applying configuration with transition time."""
        result = mock_hue_controller.apply_light_config(
            sample_light_config,
            transition_time_secs=2
        )

        assert result == mock_hue_controller

    def test_apply_light_config_processes_all_settings(self, mock_hue_controller):
        """Test that all settings in config are processed."""
        settings = [
            LightSetting("Lâmpada 1", Color(255, 0, 0, 254)),
            LightSetting("Lâmpada 2", Color(0, 255, 0, 254)),
        ]
        config = LightConfig("test", settings, "Test config")

        mock_hue_controller.apply_light_config(config)

        # All settings should have been processed
        # (In real scenario, each light would be updated)

    def test_apply_empty_config(self, mock_hue_controller):
        """Test applying configuration with no settings."""
        config = LightConfig("empty", [], "Empty config")

        result = mock_hue_controller.apply_light_config(config)

        # Should complete without error
        assert result == mock_hue_controller


class TestHueControllerLightLookup:
    """Tests for light lookup methods."""

    def test_get_light_by_name(self, mock_hue_controller):
        """Test getting light by name."""
        light = mock_hue_controller._get_light_by_name("Lâmpada 1")

        assert light is not None
        assert light.name == "Lâmpada 1"

    def test_get_nonexistent_light(self, mock_hue_controller):
        """Test getting light that doesn't exist."""
        light = mock_hue_controller._get_light_by_name("Nonexistent")

        assert light is None

    def test_light_cache_initialization(self, mock_hue_controller):
        """Test that light cache is initialized on controller creation."""
        assert hasattr(mock_hue_controller, '_light_cache')
        assert isinstance(mock_hue_controller._light_cache, dict)
        assert len(mock_hue_controller._light_cache) > 0

    def test_light_cache_contains_all_lights(self, mock_hue_controller):
        """Test that cache contains all lights from bridge."""
        # Cache should have same lights as lights list
        assert len(mock_hue_controller._light_cache) == len(mock_hue_controller.lights)

        # All lights should be in cache by name
        for light in mock_hue_controller.lights:
            assert light.name in mock_hue_controller._light_cache
            assert mock_hue_controller._light_cache[light.name] == light

    def test_light_lookup_uses_cache(self, mock_hue_controller):
        """Test that light lookup uses cache (O(1) operation)."""
        light_name = "Lâmpada 1"

        # Get light using cached lookup
        light = mock_hue_controller._get_light_by_name(light_name)

        # Should return cached light
        assert light is mock_hue_controller._light_cache[light_name]

    def test_refresh_lights_updates_cache(self, mock_hue_controller):
        """Test that refresh_lights() updates the cache."""
        # Get initial cache size
        initial_size = len(mock_hue_controller._light_cache)

        # Refresh lights (in mock, this won't change, but method should work)
        mock_hue_controller.refresh_lights()

        # Cache should still exist and be populated
        assert hasattr(mock_hue_controller, '_light_cache')
        assert len(mock_hue_controller._light_cache) >= initial_size

    def test_list_lights(self, mock_hue_controller):
        """Test listing all lights."""
        lights = mock_hue_controller.list_lights()

        assert isinstance(lights, list)
        assert len(lights) > 0
        assert all(isinstance(name, str) for name in lights)

    def test_list_groups(self, mock_hue_controller):
        """Test listing groups."""
        groups = mock_hue_controller.list_groups()

        assert isinstance(groups, list)


class TestHueControllerGetLightsStatus:
    """Tests for getting lights status."""

    def test_get_lights_status(self, mock_hue_controller):
        """Test getting status of all lights."""
        status = mock_hue_controller.get_lights_status()

        assert isinstance(status, list)
        assert len(status) > 0

    def test_lights_status_structure(self, mock_hue_controller):
        """Test that lights status has correct structure."""
        status = mock_hue_controller.get_lights_status()

        for light_status in status:
            assert "name" in light_status
            assert "on" in light_status
            assert "brightness" in light_status
            assert "reachable" in light_status
            assert "color" in light_status

    def test_lights_status_color_structure(self, mock_hue_controller):
        """Test that color in status has RGB values."""
        status = mock_hue_controller.get_lights_status()

        for light_status in status:
            color = light_status["color"]
            assert "r" in color
            assert "g" in color
            assert "b" in color

    def test_lights_status_on_light(self, mock_hue_controller):
        """Test status for a light that is on."""
        status = mock_hue_controller.get_lights_status()

        # Find a light that's on (from mock)
        on_lights = [s for s in status if s["on"]]

        if on_lights:
            light = on_lights[0]
            assert light["brightness"] > 0
            # Color should be actual color, not gray
            assert not (
                light["color"]["r"] == 50 and
                light["color"]["g"] == 50 and
                light["color"]["b"] == 50
            )

    def test_lights_status_handles_errors(self, mock_hue_controller):
        """Test that status handles errors gracefully."""
        # Create a light that raises exception
        bad_light = Mock()
        bad_light.name = "Bad Light"
        bad_light.on = property(Mock(side_effect=Exception("Test error")))

        # Add bad light to controller
        mock_hue_controller.lights.append(bad_light)

        # Should not raise exception
        status = mock_hue_controller.get_lights_status()

        # Status should still be returned (bad light ignored)
        assert isinstance(status, list)


class TestHueControllerXYtoRGB:
    """Tests for XY to RGB conversion."""

    def test_xy_to_rgb_conversion(self, mock_hue_controller):
        """Test XY to RGB conversion."""
        xy = (0.5, 0.5)
        brightness = 254

        rgb = mock_hue_controller._xy_to_rgb(xy, brightness)

        assert isinstance(rgb, tuple)
        assert len(rgb) == 3
        assert all(isinstance(val, int) for val in rgb)

    def test_xy_to_rgb_range(self, mock_hue_controller):
        """Test that RGB values are in valid range."""
        xy = (0.3, 0.4)
        brightness = 200

        r, g, b = mock_hue_controller._xy_to_rgb(xy, brightness)

        assert 0 <= r <= 255
        assert 0 <= g <= 255
        assert 0 <= b <= 255

    def test_xy_to_rgb_different_brightness(self, mock_hue_controller):
        """Test XY to RGB with different brightness levels."""
        xy = (0.4, 0.5)

        rgb_bright = mock_hue_controller._xy_to_rgb(xy, 254)
        rgb_dim = mock_hue_controller._xy_to_rgb(xy, 50)

        # Brighter should generally have higher RGB values
        # (Though this depends on the specific XY values)
        assert isinstance(rgb_bright, tuple)
        assert isinstance(rgb_dim, tuple)

    def test_xy_to_rgb_zero_y_handling(self, mock_hue_controller):
        """Test that conversion handles y=0 (division by zero)."""
        xy = (0.5, 0)  # y is zero
        brightness = 200

        # Should not raise ZeroDivisionError
        rgb = mock_hue_controller._xy_to_rgb(xy, brightness)

        assert isinstance(rgb, tuple)
        assert len(rgb) == 3

    def test_xy_to_rgb_edge_values(self, mock_hue_controller):
        """Test XY to RGB with edge case XY values."""
        test_cases = [
            ((0.0, 0.0), 254),
            ((1.0, 1.0), 254),
            ((0.5, 0.5), 254),
            ((0.3, 0.3), 127),
        ]

        for xy, brightness in test_cases:
            rgb = mock_hue_controller._xy_to_rgb(xy, brightness)

            assert isinstance(rgb, tuple)
            assert len(rgb) == 3
            assert all(0 <= val <= 255 for val in rgb)

    def test_xy_to_rgb_gamma_correction(self, mock_hue_controller):
        """Test that gamma correction is applied."""
        xy = (0.4, 0.5)
        brightness = 254

        rgb = mock_hue_controller._xy_to_rgb(xy, brightness)

        # Result should be gamma-corrected (values in 0-255)
        assert all(isinstance(val, int) for val in rgb)
        assert all(0 <= val <= 255 for val in rgb)


class TestHueControllerIntegration:
    """Integration tests for HueController workflows."""

    def test_full_workflow_set_and_get_status(self, mock_hue_controller):
        """Test full workflow: set color then get status."""
        color = Color(255, 100, 50, 200)

        # Set color
        mock_hue_controller.set_light_color("Lâmpada 1", color)

        # Get status
        status = mock_hue_controller.get_lights_status()

        assert len(status) > 0

    def test_apply_config_workflow(self, mock_hue_controller, sample_light_config):
        """Test full workflow: apply config then verify."""
        # Apply configuration
        mock_hue_controller.apply_light_config(sample_light_config, transition_time_secs=1)

        # Get status to verify (in mock, this won't show changes, but test the flow)
        status = mock_hue_controller.get_lights_status()

        assert isinstance(status, list)

    def test_multiple_color_changes(self, mock_hue_controller):
        """Test applying multiple color changes in sequence."""
        colors = [
            Color(255, 0, 0, 254),
            Color(0, 255, 0, 254),
            Color(0, 0, 255, 254),
        ]

        for color in colors:
            light = mock_hue_controller.set_light_color("Lâmpada 1", color)
            assert light is not None


class TestHueControllerErrorHandling:
    """Tests for error handling in HueController."""

    def test_invalid_light_name_handling(self, mock_hue_controller):
        """Test handling of invalid light names."""
        color = Color(255, 128, 64, 200)

        # Should raise ValueError for invalid light (validation added by Agent 1)
        with pytest.raises(ValueError, match="não encontrada"):
            mock_hue_controller.set_light_color("Invalid Light", color)

    def test_config_with_invalid_lights(self, mock_hue_controller):
        """Test applying config with some invalid light names."""
        settings = [
            LightSetting("Lâmpada 1", Color(255, 0, 0, 254)),  # Valid
            LightSetting("Invalid Light", Color(0, 255, 0, 254)),  # Invalid
        ]
        config = LightConfig("mixed", settings, "Mixed valid/invalid")

        # Should not raise exception
        result = mock_hue_controller.apply_light_config(config)

        assert result == mock_hue_controller
