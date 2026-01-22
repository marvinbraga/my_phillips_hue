"""
Unit tests for marvin_hue.colors module.

Tests the Color class including initialization, validation,
serialization, and random color generation.
"""

import pytest

from marvin_hue.colors import Color


class TestColorInitialization:
    """Tests for Color class initialization."""

    def test_color_default_values(self):
        """Test Color initialization with default values."""
        color = Color()
        assert color.red == 254
        assert color.green == 254
        assert color.blue == 254
        assert color.brightness == 254

    def test_color_custom_values(self):
        """Test Color initialization with custom values."""
        color = Color(red=100, green=150, blue=200, brightness=180)
        assert color.red == 100
        assert color.green == 150
        assert color.blue == 200
        assert color.brightness == 180

    def test_color_partial_values(self):
        """Test Color initialization with partial custom values."""
        color = Color(red=50, green=100)
        assert color.red == 50
        assert color.green == 100
        assert color.blue == 254  # Default
        assert color.brightness == 254  # Default


class TestColorValidation:
    """Tests for Color value validation."""

    def test_valid_rgb_values(self, edge_case_colors):
        """Test that valid RGB values are accepted."""
        for red, green, blue, brightness in edge_case_colors:
            color = Color(red, green, blue, brightness)
            assert color.red == red
            assert color.green == green
            assert color.blue == blue
            assert color.brightness == brightness

    def test_zero_values(self):
        """Test that zero values are valid."""
        color = Color(0, 0, 0, 0)
        assert color.red == 0
        assert color.green == 0
        assert color.blue == 0
        assert color.brightness == 0

    def test_max_rgb_values(self):
        """Test maximum RGB values (255)."""
        color = Color(255, 255, 255, 254)
        assert color.red == 255
        assert color.green == 255
        assert color.blue == 255
        assert color.brightness == 254

    def test_max_brightness_value(self):
        """Test maximum brightness value (254, not 255)."""
        color = Color(100, 100, 100, 254)
        assert color.brightness == 254


class TestColorSerialization:
    """Tests for Color serialization methods."""

    def test_to_dict(self, sample_color):
        """Test Color.to_dict() method."""
        result = sample_color.to_dict()

        assert isinstance(result, dict)
        assert "red" in result
        assert "green" in result
        assert "blue" in result
        assert "brightness" in result
        assert result["red"] == sample_color.red
        assert result["green"] == sample_color.green
        assert result["blue"] == sample_color.blue
        assert result["brightness"] == sample_color.brightness

    def test_to_dict_with_zero_values(self):
        """Test to_dict() with zero values."""
        color = Color(0, 0, 0, 0)
        result = color.to_dict()

        assert result["red"] == 0
        assert result["green"] == 0
        assert result["blue"] == 0
        assert result["brightness"] == 0

    def test_to_dict_structure(self):
        """Test that to_dict() returns exactly 4 keys."""
        color = Color(100, 150, 200, 180)
        result = color.to_dict()

        assert len(result) == 4
        assert set(result.keys()) == {"red", "green", "blue", "brightness"}


class TestColorStringRepresentation:
    """Tests for Color string representation."""

    def test_str_method(self, sample_color):
        """Test Color.__str__() method."""
        result = str(sample_color)

        assert isinstance(result, str)
        assert "R:" in result or "red" in result.lower()
        assert "G:" in result or "green" in result.lower()
        assert "B:" in result or "blue" in result.lower()
        assert "Brightness:" in result or "brightness" in result.lower()

    def test_str_contains_values(self):
        """Test that __str__ contains actual color values."""
        color = Color(123, 45, 67, 89)
        result = str(color)

        assert "123" in result
        assert "45" in result
        assert "67" in result
        assert "89" in result


class TestColorRandomGeneration:
    """Tests for random color generation."""

    def test_random_color_creation(self):
        """Test that random_color() creates a Color instance."""
        color = Color.random_color()

        assert isinstance(color, Color)
        assert 0 <= color.red <= 255
        assert 0 <= color.green <= 255
        assert 0 <= color.blue <= 255
        assert 0 <= color.brightness <= 254

    def test_random_color_with_fixed_brightness(self):
        """Test random_color() with fixed brightness."""
        brightness = 100
        color = Color.random_color(brightness=brightness)

        assert color.brightness == brightness
        assert 0 <= color.red <= 255
        assert 0 <= color.green <= 255
        assert 0 <= color.blue <= 255

    def test_random_color_variability(self):
        """Test that random_color() produces different colors."""
        colors = [Color.random_color() for _ in range(10)]

        # Check that not all colors are identical
        # (extremely unlikely with random generation)
        unique_colors = {
            (c.red, c.green, c.blue, c.brightness) for c in colors
        }
        assert len(unique_colors) > 1

    def test_random_color_with_random_brightness(self):
        """Test random_color() with random brightness (default)."""
        color = Color.random_color()

        # When brightness=254 (default), it should randomize
        # This is probabilistic, so we just check it's valid
        assert 0 <= color.brightness <= 254


class TestColorEquality:
    """Tests for Color comparison (if implemented)."""

    def test_same_values_different_instances(self):
        """Test that colors with same values can be compared."""
        color1 = Color(100, 150, 200, 180)
        color2 = Color(100, 150, 200, 180)

        # Even without __eq__, we can compare attributes
        assert color1.red == color2.red
        assert color1.green == color2.green
        assert color1.blue == color2.blue
        assert color1.brightness == color2.brightness

    def test_different_values(self):
        """Test that colors with different values are distinguishable."""
        color1 = Color(100, 150, 200, 180)
        color2 = Color(50, 75, 100, 90)

        assert color1.red != color2.red
        assert color1.green != color2.green
        assert color1.blue != color2.blue
        assert color1.brightness != color2.brightness


class TestColorEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_pure_colors(self):
        """Test pure primary colors."""
        red = Color(255, 0, 0, 254)
        green = Color(0, 255, 0, 254)
        blue = Color(0, 0, 255, 254)

        assert red.red == 255 and red.green == 0 and red.blue == 0
        assert green.red == 0 and green.green == 255 and green.blue == 0
        assert blue.red == 0 and blue.green == 0 and blue.blue == 255

    def test_grayscale_values(self):
        """Test grayscale colors (equal RGB values)."""
        black = Color(0, 0, 0, 0)
        gray = Color(128, 128, 128, 128)
        white = Color(255, 255, 255, 254)

        assert black.red == black.green == black.blue == 0
        assert gray.red == gray.green == gray.blue == 128
        assert white.red == white.green == white.blue == 255

    def test_brightness_zero_vs_nonzero(self):
        """Test difference between brightness 0 and non-zero."""
        off = Color(255, 255, 255, 0)
        on = Color(255, 255, 255, 254)

        assert off.brightness == 0
        assert on.brightness == 254
        # RGB values should be preserved even with brightness 0
        assert off.red == on.red
        assert off.green == on.green
        assert off.blue == on.blue
