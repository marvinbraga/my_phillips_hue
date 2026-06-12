from unittest.mock import MagicMock

from marvin_hue.basics import LightConfig, LightSetting
from marvin_hue.colors import Color


def _make_controller():
    from marvin_hue.controllers import HueController
    c = HueController.__new__(HueController)  # sem conectar à bridge
    fita = MagicMock(); fita.name = "Fita Led"
    teto = MagicMock(); teto.name = "Lâmpada 1"
    c.lights = [fita, teto]
    c._light_cache = {fita.name: fita, teto.name: teto}
    return c, fita, teto


def test_set_light_color_clamps_fita_led():
    c, fita, _ = _make_controller()
    c.set_light_color("Fita Led", Color(255, 0, 0, 254))  # pediu 254 (100%)
    assert fita.brightness <= 64  # 25% de 254


def test_apply_config_preset_is_clamped_through_chokepoint():
    """Preset que liga Led cima a 254 escapa do middleware, mas NÃO do controller."""
    c, _, _ = _make_controller()
    led = MagicMock(); led.name = "Led cima"
    c.lights.append(led); c._light_cache["Led cima"] = led
    cfg = LightConfig(
        name="cena_forte",
        settings=[LightSetting("Led cima", Color(255, 255, 255, 254))],
        description="cena que pede brilho máximo",
    )
    c.apply_light_config(cfg)
    assert led.brightness <= 64  # clampado na origem


def test_set_light_color_no_clamp_for_ceiling():
    c, _, teto = _make_controller()
    c.set_light_color("Lâmpada 1", Color(255, 255, 255, 254))
    assert teto.brightness == 254  # teto não tem restrição


def test_set_all_brightness_clamps_per_lamp():
    """Fecha o furo do caminho "all": clamp aplicado POR LÂMPADA."""
    c, fita, teto = _make_controller()
    c.set_all_brightness(254)
    assert fita.brightness <= 64   # 25% de 254
    assert teto.brightness == 254  # sem restrição
