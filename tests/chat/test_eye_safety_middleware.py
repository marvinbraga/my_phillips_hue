"""EyeSafetyMiddleware deve limitar Fita Led / Led cima a <=25% via código."""
from __future__ import annotations

from unittest.mock import MagicMock


def _make_request(tool_name, args):
    """Fake de ToolCallRequest cujo override(tool_call=...) encaminha o novo
    tool_call (o middleware usa override imutável, não mutação in-place)."""
    req = MagicMock()
    req.tool_call = {"name": tool_name, "args": dict(args), "id": "tc-1"}

    def _override(**kw):
        new = MagicMock()
        new.tool_call = kw.get("tool_call", req.tool_call)
        new.override.side_effect = _override
        return new

    req.override.side_effect = _override
    return req


def test_clamp_set_brightness_fita_led():
    from marvin_hue.chat.middleware.eye_safety import EyeSafetyMiddleware
    mw = EyeSafetyMiddleware()
    captured = {}

    def handler(request):
        captured.update(request.tool_call["args"])
        return "ok"

    req = _make_request("set_brightness", {"light_name": "Fita Led", "brightness": 100})
    mw.wrap_tool_call(req, handler)
    assert captured["brightness"] <= 25  # percentual


def test_clamp_set_light_color_led_cima_hue_scale():
    """set_light_color usa brilho 0-254: 25% -> 63 (floor)."""
    from marvin_hue.chat.middleware.eye_safety import EyeSafetyMiddleware
    mw = EyeSafetyMiddleware()
    captured = {}

    def handler(request):
        captured.update(request.tool_call["args"])
        return "ok"

    req = _make_request(
        "set_light_color",
        {"light_name": "Led cima", "red": 255, "green": 0, "blue": 0, "brightness": 254},
    )
    mw.wrap_tool_call(req, handler)
    assert captured["brightness"] <= 63  # 25% de 254 (floor)


def test_no_clamp_for_ceiling():
    from marvin_hue.chat.middleware.eye_safety import EyeSafetyMiddleware
    mw = EyeSafetyMiddleware()
    captured = {}

    def handler(request):
        captured.update(request.tool_call["args"])
        return "ok"

    req = _make_request("set_brightness", {"light_name": "Lâmpada 1", "brightness": 100})
    mw.wrap_tool_call(req, handler)
    assert captured["brightness"] == 100
