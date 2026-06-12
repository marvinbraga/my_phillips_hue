from unittest.mock import MagicMock


def _make_controller():
    from marvin_hue.controllers import HueController
    c = HueController.__new__(HueController)  # sem conectar à bridge
    l1, l2 = MagicMock(name="Fita Led"), MagicMock(name="Teto")
    l1.name, l2.name = "Fita Led", "Lâmpada 1"
    c.lights = [l1, l2]
    c._light_cache = {l1.name: l1, l2.name: l2}
    return c, l1, l2


def test_turn_off_uses_public_method():
    c, l1, _ = _make_controller()
    c.turn_off("Fita Led")
    assert l1.on is False


def test_set_brightness_public():
    # Usa a lâmpada do teto (sem restrição ocular) para testar a MECÂNICA do
    # setter público sem o clamp interferir; o clamp em si é coberto em
    # tests/test_controller_eye_safety.py.
    c, _, l2 = _make_controller()
    c.set_brightness("Lâmpada 1", 64)
    assert l2.brightness == 64


def test_set_all():
    c, l1, l2 = _make_controller()
    c.set_all(False)
    assert l1.on is False and l2.on is False
