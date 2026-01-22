"""
Setup Builder Module - Eliminates duplication in setup definitions.

This module provides a builder pattern for creating LightConfig instances
from JSON data, reducing the 808-line setups.py file to a simple JSON file.
"""

import warnings
from typing import Any

from marvin_hue.basics import LightConfig, LightSetting
from marvin_hue.colors import Color
from marvin_hue.logging_config import get_logger

logger = get_logger("setup_builder")

# Standard light names used across all configurations
STANDARD_LIGHTS = [
    'Lâmpada 1',
    'Lâmpada 2',
    'Lâmpada 4',
    'Hue Iris',
    'Hue Play 1',
    'Hue Play 2',
    'Fita Led',
    'Led cima',
]


class LightConfigBuilder:
    """
    Builder class for creating LightConfig instances from various sources.

    This eliminates the need for 50+ separate class definitions in setups.py.
    """

    @staticmethod
    def from_dict(config: dict[str, Any]) -> LightConfig:
        """
        Create a LightConfig from a dictionary (typically from JSON).

        Args:
            config: Dictionary with keys 'name', 'description', and 'settings'
                   where 'settings' is a list of dicts with 'light_name' and 'color'

        Returns:
            LightConfig instance

        Example:
            >>> config = {
            ...     "name": "concentration",
            ...     "description": "Focus mode",
            ...     "settings": [
            ...         {"light_name": "Lâmpada 1", "color": {"red": 255, "green": 244, "blue": 229, "brightness": 255}},
            ...     ]
            ... }
            >>> light_config = LightConfigBuilder.from_dict(config)
        """
        try:
            name = config.get("name", "unnamed")
            description = config.get("description", "")
            settings_data = config.get("settings", [])

            settings: list[LightSetting] = []
            for setting in settings_data:
                light_name = setting.get("light_name")
                color_data = setting.get("color", {})

                if not light_name or not color_data:
                    logger.warning(f"Skipping invalid setting in config '{name}': {setting}")
                    continue

                color = Color(
                    red=color_data.get("red", 0),
                    green=color_data.get("green", 0),
                    blue=color_data.get("blue", 0),
                    brightness=color_data.get("brightness", 0)
                )
                settings.append(LightSetting(light_name, color))

            return LightConfig(name=name, settings=settings, description=description)

        except Exception as e:
            logger.error(f"Error creating LightConfig from dict: {e}", exc_info=True)
            raise ValueError(f"Invalid configuration data: {e}")

    @staticmethod
    def create_uniform(
        name: str,
        color: Color,
        description: str = "",
        lights: list[str] | None = None
    ) -> LightConfig:
        """
        Create a LightConfig with the same color for all lights.

        Args:
            name: Configuration name
            color: Color to apply to all lights
            description: Configuration description
            lights: List of light names (defaults to STANDARD_LIGHTS)

        Returns:
            LightConfig instance

        Example:
            >>> config = LightConfigBuilder.create_uniform(
            ...     "all_blue",
            ...     Color(0, 0, 255, 200),
            ...     "Everything blue"
            ... )
        """
        if lights is None:
            lights = STANDARD_LIGHTS

        settings = [LightSetting(light_name, color) for light_name in lights]
        return LightConfig(name=name, settings=settings, description=description)

    @staticmethod
    def create_custom(
        name: str,
        light_colors: dict[str, Color],
        description: str = ""
    ) -> LightConfig:
        """
        Create a LightConfig with custom colors for each light.

        Args:
            name: Configuration name
            light_colors: Dict mapping light names to Color objects
            description: Configuration description

        Returns:
            LightConfig instance

        Example:
            >>> config = LightConfigBuilder.create_custom(
            ...     "custom_mix",
            ...     {
            ...         "Lâmpada 1": Color(255, 0, 0, 200),
            ...         "Lâmpada 2": Color(0, 255, 0, 200),
            ...     },
            ...     "Red and green mix"
            ... )
        """
        settings = [
            LightSetting(light_name, color)
            for light_name, color in light_colors.items()
        ]
        return LightConfig(name=name, settings=settings, description=description)

    @staticmethod
    def validate_config(config: dict[str, Any]) -> bool:
        """
        Validate a configuration dictionary structure.

        Args:
            config: Configuration dictionary to validate

        Returns:
            True if valid, False otherwise
        """
        if not isinstance(config, dict):
            return False

        if "name" not in config or not isinstance(config["name"], str):
            return False

        if "settings" not in config or not isinstance(config["settings"], list):
            return False

        for setting in config["settings"]:
            if not isinstance(setting, dict):
                return False
            if "light_name" not in setting or "color" not in setting:
                return False

            color = setting["color"]
            if not isinstance(color, dict):
                return False

            required_color_keys = {"red", "green", "blue", "brightness"}
            if not required_color_keys.issubset(color.keys()):
                return False

        return True


def create_config_from_legacy_class(legacy_class: Any) -> dict[str, Any]:
    """
    Convert a legacy setup class to a dictionary format.

    This is a compatibility function for migrating from the old class-based system
    to the new JSON-based system.

    Args:
        legacy_class: A class instance from the old setups.py module

    Returns:
        Dictionary representation of the configuration
    """
    warnings.warn(
        "Using legacy setup classes is deprecated. Please migrate to JSON-based configurations.",
        DeprecationWarning,
        stacklevel=2
    )

    instance = legacy_class()
    result: dict[str, Any] = instance.to_dict()
    return result
