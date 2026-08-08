"""ScreenMirror excludes lights disabled via runtime enabled_for_app policy."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from marvin_hue import eye_safety as es
from marvin_hue.screen_mirror import ScreenMirror


def setup_function() -> None:
    es.clear_runtime_policy()


def teardown_function() -> None:
    es.clear_runtime_policy()


def test_load_positions_filters_disabled(tmp_path: Path) -> None:
    es.set_runtime_policy(limits_pct={}, disabled_names={"Hue Play 1"})
    path = tmp_path / "pos.json"
    path.write_text(
        json.dumps(
            {
                "lights": [
                    {"name": "Hue Play 1", "position": "left", "enabled": True},
                    {"name": "Hue Play 2", "position": "right", "enabled": True},
                ]
            }
        ),
        encoding="utf-8",
    )
    mirror = ScreenMirror(MagicMock(), str(path))
    lights = mirror.load_light_positions()
    names = {x["name"] for x in lights}
    assert "Hue Play 1" not in names
    assert "Hue Play 2" in names


def test_apply_color_to_light_skips_disabled() -> None:
    es.set_runtime_policy(limits_pct={}, disabled_names={"Hue Play 1"})
    hue = MagicMock()
    mirror = ScreenMirror(hue, "unused.json")
    mirror._apply_color_to_light("Hue Play 1", 255, 0, 0)
    hue.set_light_color.assert_not_called()
