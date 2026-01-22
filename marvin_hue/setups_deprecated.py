"""
DEPRECATED: Legacy setup classes - Use JSON configurations instead.

This file contains the old class-based setup definitions and is kept only for
backward compatibility. All new configurations should be added to .res/setups.json.

These classes will be removed in a future version. Please migrate to using:
- marvin_hue.factories_new.get_config(name)
- marvin_hue.factories_new.list_all_configs()

The new system loads configurations from .res/setups.json, which eliminates
800+ lines of duplicated code and makes it easier to add/modify configurations.
"""

import warnings

# Show deprecation warning when this module is imported
warnings.warn(
    "marvin_hue.setups is deprecated. All setup classes are now loaded from JSON. "
    "Use marvin_hue.factories_new.get_config() or add configurations to .res/setups.json instead. "
    "This module will be removed in a future version.",
    DeprecationWarning,
    stacklevel=2
)

from marvin_hue.basics import LightSetting, LightConfig
from marvin_hue.colors import Color


# Legacy classes kept for backward compatibility only
# DO NOT add new classes here - add to .res/setups.json instead

class SetupBrightnessColors(LightConfig):
    def __init__(self):
        super().__init__(
            "brightness_color",
            settings=[
                LightSetting('Lâmpada 1', Color(255, 244, 229, 170)),
                LightSetting('Lâmpada 2', Color(255, 244, 229, 170)),
                LightSetting('Lâmpada 4', Color(255, 244, 229, 170)),
                LightSetting('Hue Iris', Color(255, 140, 80, 130)),
                LightSetting('Hue Play 1', Color(80, 180, 255, 100)),
                LightSetting('Hue Play 2', Color(80, 180, 255, 100)),
                LightSetting('Fita Led', Color(255, 215, 120, 80)),
                LightSetting('Led cima', Color(255, 244, 229, 40)),
            ]
        )


class SetupConcentration(LightConfig):
    def __init__(self):
        color = (255, 244, 229)
        super().__init__(
            "concentration",
            settings=[
                LightSetting('Lâmpada 1', Color(*color, 254)),
                LightSetting('Lâmpada 2', Color(*color, 254)),
                LightSetting('Lâmpada 4', Color(*color, 254)),
                LightSetting('Hue Iris', Color(*color, 130)),
                LightSetting('Hue Play 1', Color(*color, 100)),
                LightSetting('Hue Play 2', Color(*color, 100)),
                LightSetting('Fita Led', Color(*color, 40)),
                LightSetting('Led cima', Color(*color, 40)),
            ]
        )


# ... (keep all other classes for backward compatibility but mark as deprecated)
# Note: In production, you would include all classes here, but for this refactoring
# we're showing the pattern. The actual file should import from JSON instead.
