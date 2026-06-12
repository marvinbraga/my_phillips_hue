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
    assert captured["brightness"] == 25  # percentual (limite exato)


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
    assert captured["brightness"] == 63  # 25% de 254 (floor exato)


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


def test_non_numeric_brightness_passes_through():
    """Brilho não-numérico (output bruto do modelo) não quebra o middleware:
    repassa para a validação pydantic da tool."""
    from marvin_hue.chat.middleware.eye_safety import EyeSafetyMiddleware
    mw = EyeSafetyMiddleware()
    captured = {}

    def handler(request):
        captured.update(request.tool_call["args"])
        return "ok"

    req = _make_request("set_brightness", {"light_name": "Fita Led", "brightness": "abc"})
    mw.wrap_tool_call(req, handler)
    assert captured["brightness"] == "abc"  # inalterado (sem int() explosivo)


import pytest


@pytest.mark.asyncio
async def test_awrap_tool_call_clamps_fita_led():
    """O caminho async (awrap_tool_call) clampa igual ao síncrono."""
    from marvin_hue.chat.middleware.eye_safety import EyeSafetyMiddleware
    mw = EyeSafetyMiddleware()
    captured = {}

    async def handler(request):
        captured.update(request.tool_call["args"])
        return "ok"

    req = _make_request("set_brightness", {"light_name": "Fita Led", "brightness": 100})
    await mw.awrap_tool_call(req, handler)
    assert captured["brightness"] == 25
