"""
Light Configuration Registry - New JSON-based system.

This module provides a registry for light configurations loaded from JSON,
replacing the old enum-based system with a more maintainable approach.
"""

import os

from marvin_hue.basics import LightConfig, LightSetupsManager
from marvin_hue.logging_config import get_logger

logger = get_logger("factories_new")


class LightConfigRegistry:
    """
    Registry for light configurations loaded from JSON.

    This replaces the old LightConfigEnum with a more flexible and maintainable
    system that doesn't require code changes for new configurations.
    """

    _instance: "LightConfigRegistry | None" = None
    _manager: LightSetupsManager | None = None
    _configs_by_name: dict[str, LightConfig] = {}

    def __new__(cls) -> "LightConfigRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if self._manager is None:
            self._load_configurations()

    def _load_configurations(self) -> None:
        """Load configurations from JSON file."""
        try:
            # Get path to setups.json
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            json_path = os.path.join(base_dir, ".res", "setups.json")

            if not os.path.exists(json_path):
                logger.error(f"Setups file not found: {json_path}")
                raise FileNotFoundError(f"Configuration file not found: {json_path}")

            # Load configurations using LightSetupsManager
            self._manager = LightSetupsManager(json_path)

            # Build index by name
            self._configs_by_name = {
                config.name: config for config in self._manager.configs
            }

            logger.info(f"Loaded {len(self._configs_by_name)} configurations from JSON")

        except Exception as e:
            logger.error(f"Error loading configurations: {e}", exc_info=True)
            raise

    def get_config(self, name: str) -> LightConfig | None:
        """
        Get a configuration by name.

        Args:
            name: Configuration name

        Returns:
            LightConfig instance or None if not found
        """
        return self._configs_by_name.get(name)

    def list_configs(self) -> list[dict[str, str]]:
        """
        List all available configurations.

        Returns:
            List of dicts with 'name' and 'description' keys
        """
        if self._manager is None:
            return []
        return [
            {"name": config.name, "description": config.description}
            for config in self._manager.configs
        ]

    def get_all_configs(self) -> list[LightConfig]:
        """
        Get all configurations.

        Returns:
            List of all LightConfig instances
        """
        return list(self._configs_by_name.values())

    @property
    def config_names(self) -> list[str]:
        """Get list of all configuration names."""
        return list(self._configs_by_name.keys())

    def reload(self) -> None:
        """Reload configurations from disk."""
        self._manager = None
        self._configs_by_name = {}
        self._load_configurations()


# Singleton instance
_registry = LightConfigRegistry()


def get_config(name: str) -> LightConfig | None:
    """
    Get a light configuration by name.

    Args:
        name: Configuration name

    Returns:
        LightConfig instance or None if not found

    Example:
        >>> config = get_config("concentration")
        >>> if config:
        ...     print(config.description)
    """
    return _registry.get_config(name)


def list_all_configs() -> list[dict[str, str]]:
    """
    List all available configurations.

    Returns:
        List of dicts with 'name' and 'description' keys

    Example:
        >>> configs = list_all_configs()
        >>> for cfg in configs:
        ...     print(f"{cfg['name']}: {cfg['description']}")
    """
    return _registry.list_configs()


def get_registry() -> LightConfigRegistry:
    """
    Get the singleton registry instance.

    Returns:
        LightConfigRegistry instance
    """
    return _registry
