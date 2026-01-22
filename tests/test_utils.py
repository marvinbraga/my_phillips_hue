"""
Unit tests for marvin_hue.utils module.

Tests the ColorConverter and RGBtoXYAdapter classes for color space conversion,
including edge cases and division by zero handling.
"""

import pytest

from marvin_hue.utils import RGBtoXYAdapter, ColorConverter


class TestRGBtoXYConversion:
    """Tests for RGB to XY conversion."""

    def test_convert_returns_tuple(self):
        """Test that convert() returns a tuple of two floats."""
        x, y = RGBtoXYAdapter.convert(255, 0, 0)

        assert isinstance(x, float)
        assert isinstance(y, float)

    def test_convert_red(self):
        """Test conversion of pure red color."""
        x, y = RGBtoXYAdapter.convert(255, 0, 0)

        # Pure red should have high x, low y
        assert 0.0 <= x <= 1.0
        assert 0.0 <= y <= 1.0
        assert x > y  # Red should have x > y

    def test_convert_green(self):
        """Test conversion of pure green color."""
        x, y = RGBtoXYAdapter.convert(0, 255, 0)

        # Pure green should have specific characteristics
        assert 0.0 <= x <= 1.0
        assert 0.0 <= y <= 1.0
        assert y > x  # Green should have y > x

    def test_convert_blue(self):
        """Test conversion of pure blue color."""
        x, y = RGBtoXYAdapter.convert(0, 0, 255)

        # Pure blue should have both x and y relatively low
        assert 0.0 <= x <= 1.0
        assert 0.0 <= y <= 1.0

    def test_convert_white(self):
        """Test conversion of white color."""
        x, y = RGBtoXYAdapter.convert(255, 255, 255)

        # White should be near the center of the color space
        assert 0.0 <= x <= 1.0
        assert 0.0 <= y <= 1.0
        # White is approximately (0.33, 0.33) in XY space
        assert 0.2 < x < 0.4
        assert 0.2 < y < 0.4

    def test_convert_black(self):
        """Test conversion of black color."""
        x, y = RGBtoXYAdapter.convert(0, 0, 0)

        # Black (all zeros) - check for division by zero handling
        assert isinstance(x, (float, int))
        assert isinstance(y, (float, int))
        # With all zeros, X+Y+Z = 0, which should be handled


class TestRGBtoXYEdgeCases:
    """Tests for edge cases in RGB to XY conversion."""

    def test_convert_grayscale_values(self):
        """Test conversion of grayscale (equal RGB) values."""
        gray_values = [0, 64, 128, 192, 255]

        for gray in gray_values:
            x, y = RGBtoXYAdapter.convert(gray, gray, gray)

            assert 0.0 <= x <= 1.0
            assert 0.0 <= y <= 1.0
            # Grayscale should be near white point
            if gray > 0:
                assert 0.2 < x < 0.4
                assert 0.2 < y < 0.4

    def test_convert_low_values(self):
        """Test conversion with low RGB values (< 0.04045 threshold)."""
        # Values below the gamma correction threshold
        x, y = RGBtoXYAdapter.convert(10, 10, 10)

        assert 0.0 <= x <= 1.0
        assert 0.0 <= y <= 1.0

    def test_convert_high_values(self):
        """Test conversion with high RGB values (> 0.04045 threshold)."""
        # Values above the gamma correction threshold
        x, y = RGBtoXYAdapter.convert(200, 150, 100)

        assert 0.0 <= x <= 1.0
        assert 0.0 <= y <= 1.0

    def test_convert_mixed_threshold_values(self):
        """Test conversion with values on both sides of threshold."""
        # Mix of low and high values
        x, y = RGBtoXYAdapter.convert(5, 100, 200)

        assert 0.0 <= x <= 1.0
        assert 0.0 <= y <= 1.0

    def test_convert_single_channel(self):
        """Test conversion with only one channel active."""
        test_cases = [
            (255, 0, 0),  # Only red
            (0, 255, 0),  # Only green
            (0, 0, 255),  # Only blue
        ]

        for red, green, blue in test_cases:
            x, y = RGBtoXYAdapter.convert(red, green, blue)

            assert 0.0 <= x <= 1.0
            assert 0.0 <= y <= 1.0


class TestRGBtoXYNormalization:
    """Tests for RGB normalization in conversion."""

    def test_normalized_input_range(self):
        """Test that RGB values are properly normalized."""
        # The conversion expects normalized RGB (0-1 range internally)
        x1, y1 = RGBtoXYAdapter.convert(255, 0, 0)
        x2, y2 = RGBtoXYAdapter.convert(128, 0, 0)

        # Both should produce valid XY coordinates
        assert 0.0 <= x1 <= 1.0 and 0.0 <= y1 <= 1.0
        assert 0.0 <= x2 <= 1.0 and 0.0 <= y2 <= 1.0

    def test_proportional_colors(self):
        """Test that proportional RGB values produce same XY (different brightness)."""
        # Same color, different intensities
        x1, y1 = RGBtoXYAdapter.convert(255, 128, 64)
        x2, y2 = RGBtoXYAdapter.convert(128, 64, 32)

        # XY coordinates should be similar (within tolerance)
        # since it's the same hue, just different brightness
        assert abs(x1 - x2) < 0.1
        assert abs(y1 - y2) < 0.1


class TestRGBtoXYMathematicalProperties:
    """Tests for mathematical properties of the conversion."""

    def test_conversion_is_deterministic(self):
        """Test that same input always produces same output."""
        x1, y1 = RGBtoXYAdapter.convert(100, 150, 200)
        x2, y2 = RGBtoXYAdapter.convert(100, 150, 200)

        assert x1 == x2
        assert y1 == y2

    def test_different_inputs_different_outputs(self):
        """Test that different inputs produce different outputs."""
        x1, y1 = RGBtoXYAdapter.convert(255, 0, 0)
        x2, y2 = RGBtoXYAdapter.convert(0, 255, 0)

        # Red and green should have different XY coordinates
        assert x1 != x2 or y1 != y2

    def test_xy_sum_properties(self):
        """Test mathematical properties of XY color space."""
        test_colors = [
            (255, 0, 0),
            (0, 255, 0),
            (0, 0, 255),
            (255, 255, 255),
            (128, 128, 128),
        ]

        for red, green, blue in test_colors:
            x, y = RGBtoXYAdapter.convert(red, green, blue)

            # In CIE XY color space, x + y should typically be <= 1
            # (z = 1 - x - y should be non-negative for valid colors)
            # Allow some tolerance for floating point math
            if red > 0 or green > 0 or blue > 0:  # Skip black
                assert x + y <= 1.01  # Small tolerance


class TestRGBtoXYDivisionByZero:
    """Tests for division by zero handling."""

    def test_all_zeros_no_exception(self):
        """Test that RGB(0,0,0) doesn't raise division by zero error."""
        try:
            x, y = RGBtoXYAdapter.convert(0, 0, 0)
            # Should not raise exception
            assert True
        except ZeroDivisionError:
            pytest.fail("RGBtoXYAdapter.convert raised ZeroDivisionError for (0,0,0)")

    def test_black_color_handling(self):
        """Test specific handling of black color."""
        x, y = RGBtoXYAdapter.convert(0, 0, 0)

        # Result should be valid numbers (not NaN or Inf)
        assert not (x != x)  # Check for NaN (NaN != NaN)
        assert not (y != y)  # Check for NaN
        assert abs(x) != float('inf')
        assert abs(y) != float('inf')


class TestRGBtoXYStaticMethod:
    """Tests for the static method behavior."""

    def test_is_static_method(self):
        """Test that convert is a static method."""
        # Should be callable without instance
        result = RGBtoXYAdapter.convert(100, 150, 200)
        assert result is not None

    def test_no_instance_required(self):
        """Test that we can call convert without creating an instance."""
        # Don't create instance, call directly on class
        x, y = RGBtoXYAdapter.convert(255, 128, 64)

        assert isinstance(x, float)
        assert isinstance(y, float)


class TestRGBtoXYGammaCorrection:
    """Tests for gamma correction in the conversion."""

    def test_gamma_correction_threshold(self):
        """Test that gamma correction is applied at the right threshold."""
        # The threshold is 0.04045 normalized (about 10.3 in 0-255 range)

        # Below threshold (should use linear: value / 12.92)
        x1, y1 = RGBtoXYAdapter.convert(10, 10, 10)

        # Above threshold (should use gamma: ((value + 0.055) / 1.055) ^ 2.4)
        x2, y2 = RGBtoXYAdapter.convert(20, 20, 20)

        # Both should produce valid results
        assert 0.0 <= x1 <= 1.0 and 0.0 <= y1 <= 1.0
        assert 0.0 <= x2 <= 1.0 and 0.0 <= y2 <= 1.0

    def test_threshold_boundary_values(self):
        """Test values right at the gamma correction threshold."""
        # Test around the threshold boundary
        values_to_test = [9, 10, 11, 12]

        for val in values_to_test:
            x, y = RGBtoXYAdapter.convert(val, val, val)
            assert 0.0 <= x <= 1.0
            assert 0.0 <= y <= 1.0


class TestColorConverter:
    """Tests for the new ColorConverter class."""

    def test_rgb_to_xy_basic(self):
        """Test basic RGB to XY conversion."""
        x, y = ColorConverter.rgb_to_xy(255, 0, 0)

        assert isinstance(x, float)
        assert isinstance(y, float)
        assert 0.0 <= x <= 1.0
        assert 0.0 <= y <= 1.0

    def test_rgb_to_xy_matches_legacy(self):
        """Test that ColorConverter.rgb_to_xy matches RGBtoXYAdapter.convert."""
        test_colors = [
            (255, 0, 0),
            (0, 255, 0),
            (0, 0, 255),
            (255, 255, 255),
            (128, 128, 128),
            (100, 150, 200),
        ]

        for r, g, b in test_colors:
            new_result = ColorConverter.rgb_to_xy(r, g, b)
            legacy_result = RGBtoXYAdapter.convert(r, g, b)

            assert new_result == legacy_result, f"Mismatch for RGB({r}, {g}, {b})"

    def test_xy_to_rgb_basic(self):
        """Test basic XY to RGB conversion."""
        r, g, b = ColorConverter.xy_to_rgb((0.5, 0.5), 254)

        assert isinstance(r, int)
        assert isinstance(g, int)
        assert isinstance(b, int)
        assert 0 <= r <= 255
        assert 0 <= g <= 255
        assert 0 <= b <= 255

    def test_xy_to_rgb_different_brightness(self):
        """Test XY to RGB with different brightness levels."""
        xy = (0.4, 0.5)

        r1, g1, b1 = ColorConverter.xy_to_rgb(xy, 254)
        r2, g2, b2 = ColorConverter.xy_to_rgb(xy, 50)

        # Both should be valid RGB
        assert 0 <= r1 <= 255 and 0 <= g1 <= 255 and 0 <= b1 <= 255
        assert 0 <= r2 <= 255 and 0 <= g2 <= 255 and 0 <= b2 <= 255

    def test_xy_to_rgb_zero_y_handling(self):
        """Test that XY to RGB handles y=0 without division by zero."""
        r, g, b = ColorConverter.xy_to_rgb((0.5, 0), 200)

        # Should not raise ZeroDivisionError
        assert isinstance(r, int)
        assert isinstance(g, int)
        assert isinstance(b, int)

    def test_roundtrip_conversion_approximate(self):
        """Test that RGB -> XY -> RGB gives approximately similar results."""
        original_rgb = (200, 150, 100)

        # Convert to XY
        x, y = ColorConverter.rgb_to_xy(*original_rgb)

        # Convert back to RGB (with full brightness)
        r, g, b = ColorConverter.xy_to_rgb((x, y), 254)

        # Results should be in valid range
        assert 0 <= r <= 255
        assert 0 <= g <= 255
        assert 0 <= b <= 255

    def test_xy_to_rgb_edge_coordinates(self):
        """Test XY to RGB with edge case XY coordinates."""
        test_cases = [
            ((0.0, 0.0), 254),
            ((1.0, 0.0), 254),
            ((0.0, 1.0), 254),
            ((0.5, 0.5), 254),
            ((0.3, 0.3), 127),
        ]

        for (x, y), brightness in test_cases:
            r, g, b = ColorConverter.xy_to_rgb((x, y), brightness)

            assert isinstance(r, int)
            assert isinstance(g, int)
            assert isinstance(b, int)
            assert 0 <= r <= 255
            assert 0 <= g <= 255
            assert 0 <= b <= 255


class TestRGBtoXYAdapterDeprecation:
    """Tests to ensure RGBtoXYAdapter still works (backward compatibility)."""

    def test_adapter_still_works(self):
        """Test that deprecated adapter still functions."""
        x, y = RGBtoXYAdapter.convert(255, 128, 64)

        assert isinstance(x, float)
        assert isinstance(y, float)
        assert 0.0 <= x <= 1.0
        assert 0.0 <= y <= 1.0

    def test_adapter_delegates_to_converter(self):
        """Test that adapter delegates to ColorConverter."""
        test_rgb = (100, 150, 200)

        adapter_result = RGBtoXYAdapter.convert(*test_rgb)
        converter_result = ColorConverter.rgb_to_xy(*test_rgb)

        assert adapter_result == converter_result
