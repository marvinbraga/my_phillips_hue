"""CLI scene resolution uses LightSetupsManager JSON, not LightConfigEnum."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from main import (
    DEFAULT_SETUP_NAME,
    EmptySetupsError,
    UnknownSetupError,
    apply_setup,
    format_apply_result,
    parse_setup_name,
    resolve_config,
)
from marvin_hue.apply_result import ApplyResult
from marvin_hue.basics import LightConfig, LightSetupsManager


def _write_setups(path: Path, names: list[str]) -> LightSetupsManager:
    setups: list[dict[str, Any]] = []
    for name in names:
        setups.append(
            {
                "name": name,
                "description": f"{name} scene",
                "settings": [
                    {
                        "light_name": "Lâmpada 1",
                        "color": {
                            "red": 1,
                            "green": 2,
                            "blue": 3,
                            "brightness": 4,
                        },
                    }
                ],
            }
        )
    path.write_text(json.dumps({"setups": setups}), encoding="utf-8")
    return LightSetupsManager(str(path))


class TestParseSetupName:
    def test_missing_arg_is_none(self) -> None:
        assert parse_setup_name(["main.py"]) is None

    def test_uses_first_positional_arg(self) -> None:
        assert parse_setup_name(["main.py", "relax"]) == "relax"


class TestResolveConfig:
    def test_named_setup(self, tmp_path: Path) -> None:
        manager = _write_setups(tmp_path / "setups.json", ["concentration", "relax"])
        config = resolve_config(manager, "relax")
        assert isinstance(config, LightConfig)
        assert config.name == "relax"

    def test_default_is_concentration_when_present(self, tmp_path: Path) -> None:
        manager = _write_setups(tmp_path / "setups.json", ["relax", "concentration"])
        config = resolve_config(manager, None)
        assert config.name == DEFAULT_SETUP_NAME
        assert config.name == "concentration"

    def test_default_is_first_config_when_concentration_missing(
        self, tmp_path: Path
    ) -> None:
        manager = _write_setups(tmp_path / "setups.json", ["cyberpunk_night", "relax"])
        config = resolve_config(manager, None)
        assert config.name == "cyberpunk_night"

    def test_unknown_name_raises(self, tmp_path: Path) -> None:
        manager = _write_setups(tmp_path / "setups.json", ["concentration"])
        with pytest.raises(UnknownSetupError, match="missing_scene"):
            resolve_config(manager, "missing_scene")

    def test_empty_catalog_raises(self, tmp_path: Path) -> None:
        manager = _write_setups(tmp_path / "setups.json", [])
        with pytest.raises(EmptySetupsError):
            resolve_config(manager, None)


class TestApplySetup:
    def test_applies_resolved_config_and_returns_result(self, tmp_path: Path) -> None:
        manager = _write_setups(tmp_path / "setups.json", ["concentration"])
        controller = MagicMock()
        controller.apply_light_config.return_value = ApplyResult(
            applied=("Lâmpada 1",),
            failed=(),
        )

        result = apply_setup(manager, controller, "concentration")

        assert result.ok is True
        assert result.applied == ("Lâmpada 1",)
        controller.apply_light_config.assert_called_once()
        applied_config = controller.apply_light_config.call_args[0][0]
        assert applied_config.name == "concentration"

    def test_partial_failure_is_surfaced(self, tmp_path: Path) -> None:
        manager = _write_setups(tmp_path / "setups.json", ["concentration"])
        controller = MagicMock()
        controller.apply_light_config.return_value = ApplyResult(
            applied=("Lâmpada 1",),
            failed=(("Hue Iris", "timeout"),),
        )

        result = apply_setup(manager, controller, None)

        assert result.ok is False
        assert result.partial is True
        assert result.failed == (("Hue Iris", "timeout"),)


class TestFormatApplyResult:
    def test_includes_applied_and_failed(self) -> None:
        result = ApplyResult(
            applied=("Lâmpada 1", "Lâmpada 2"),
            failed=(("Hue Iris", "timeout"),),
        )
        text = format_apply_result(result)
        assert "Lâmpada 1" in text
        assert "Lâmpada 2" in text
        assert "Hue Iris" in text
        assert "timeout" in text
        assert "Applied:" in text
        assert "Failed:" in text
