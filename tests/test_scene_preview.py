"""Testes do preview de cena (issue #8): brilho efetivo, enabled e cor exibida."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from marvin_hue.basics import LightConfig, LightSetting
from marvin_hue.colors import Color
from marvin_hue.eye_safety import (
    clear_runtime_policy,
    set_runtime_enabled,
    set_runtime_limits,
)
from marvin_hue.services.scene_preview import ScenePreviewLight, build_scene_preview
from marvin_hue.utils import ColorConverter


@pytest.fixture(autouse=True)
def _reset_runtime_policy() -> Iterator[None]:
    clear_runtime_policy()
    yield
    clear_runtime_policy()


def _config(*settings: tuple[str, Color]) -> LightConfig:
    return LightConfig(
        name="teste",
        description="cena de teste",
        settings=[LightSetting(name, color) for name, color in settings],
    )


def test_preview_keeps_order_and_configured_color() -> None:
    config = _config(
        ("Lâmpada 1", Color(255, 147, 41, 180)),
        ("Lâmpada 2", Color(10, 20, 30, 40)),
    )

    preview = build_scene_preview(config)

    assert [item.light_name for item in preview] == ["Lâmpada 1", "Lâmpada 2"]
    assert isinstance(preview[0], ScenePreviewLight)
    assert preview[0].color == Color(255, 147, 41, 180).to_dict()
    assert preview[1].color == {"red": 10, "green": 20, "blue": 30, "brightness": 40}


def test_uncapped_light_keeps_brightness() -> None:
    preview = build_scene_preview(_config(("Lâmpada 1", Color(255, 0, 0, 254))))
    assert preview[0].brightness == 254
    assert preview[0].enabled is True


@pytest.mark.parametrize("light_name", ["Fita Led", "Led cima"])
def test_capped_light_is_clamped_like_controller(light_name: str) -> None:
    preview = build_scene_preview(_config((light_name, Color(255, 255, 255, 254))))
    # 25% de 254 = 63.5 -> floor 63 (mesmo critério de clamp_eye_safety "hue")
    assert preview[0].brightness == 63
    # cor configurada permanece intacta
    assert preview[0].color["brightness"] == 254


def test_capped_light_below_limit_is_untouched() -> None:
    preview = build_scene_preview(_config(("Fita Led", Color(255, 255, 255, 30))))
    assert preview[0].brightness == 30


def test_disabled_light_is_flagged() -> None:
    set_runtime_enabled({"Lâmpada 2": False, "Lâmpada 1": True})
    preview = build_scene_preview(
        _config(
            ("Lâmpada 1", Color(255, 0, 0, 200)),
            ("Lâmpada 2", Color(0, 255, 0, 200)),
        )
    )
    assert preview[0].enabled is True
    assert preview[1].enabled is False


def test_rgb_matches_controller_color_space() -> None:
    preview = build_scene_preview(_config(("Fita Led", Color(255, 147, 41, 254))))
    expected = ColorConverter.xy_to_rgb(ColorConverter.rgb_to_xy(255, 147, 41), 63)
    assert (preview[0].r, preview[0].g, preview[0].b) == expected


def test_zero_brightness_edge() -> None:
    preview = build_scene_preview(_config(("Lâmpada 1", Color(255, 0, 0, 0))))
    assert preview[0].brightness == 0
    assert (preview[0].r, preview[0].g, preview[0].b) == ColorConverter.xy_to_rgb(
        ColorConverter.rgb_to_xy(255, 0, 0), 0
    )


def test_black_color_maps_to_white_point() -> None:
    preview = build_scene_preview(_config(("Lâmpada 1", Color(0, 0, 0, 100))))
    # (0, 0, 0) -> ponto branco D65 (0.3127, 0.329) -> RGB em brilho 100
    assert (preview[0].r, preview[0].g, preview[0].b) == (163, 170, 170)
    assert preview[0].brightness == 100


def test_runtime_limit_caps_uncapped_light() -> None:
    set_runtime_limits({"Lâmpada 1": 50})
    preview = build_scene_preview(_config(("Lâmpada 1", Color(255, 255, 255, 254))))
    # 50% de 254 = 127 (floor)
    assert preview[0].brightness == 127


def test_runtime_null_limit_falls_back_to_hardcoded_default() -> None:
    # None no registry = "sem override" -> volta ao fallback hardcoded (25%)
    set_runtime_limits({"Fita Led": None})
    preview = build_scene_preview(_config(("Fita Led", Color(255, 255, 255, 254))))
    assert preview[0].brightness == 63


def test_preview_uses_shared_effective_brightness_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import marvin_hue.services.scene_preview as sp

    calls: list[tuple[str, int]] = []

    def fake(name: str, bri: int) -> int:
        calls.append((name, bri))
        return 7

    monkeypatch.setattr(sp, "effective_hue_brightness", fake)
    preview = build_scene_preview(_config(("Lâmpada 1", Color(1, 2, 3, 200))))
    assert calls == [("Lâmpada 1", 200)]
    assert preview[0].brightness == 7


def test_empty_config_returns_empty_list() -> None:
    assert build_scene_preview(_config()) == []
