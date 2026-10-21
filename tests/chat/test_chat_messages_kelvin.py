"""messages.message_text (P17), task._last_ai_text e Kelvin→RGB (P13)."""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage


def test_message_text_lives_in_common_module():
    from marvin_hue.chat.agents.react_agent import _message_text
    from marvin_hue.chat.messages import message_text

    content = [{"type": "thinking", "thinking": "x"}, {"type": "text", "text": "oi"}]
    assert message_text(content) == "oi"
    assert _message_text is message_text


def test_last_ai_text_handles_block_content():
    from marvin_hue.chat.subagents.task import _last_ai_text

    result = {
        "messages": [
            HumanMessage(content="pedido"),
            AIMessage(
                content=[
                    {"type": "thinking", "thinking": "pensando", "signature": "s"},
                    {"type": "text", "text": "Cena aplicada."},
                ]
            ),
        ]
    }
    assert _last_ai_text(result) == "Cena aplicada."


def test_last_ai_text_skips_thinking_only_message():
    from marvin_hue.chat.subagents.task import _last_ai_text

    result = {
        "messages": [
            AIMessage(content="Resposta anterior."),
            AIMessage(content=[{"type": "thinking", "thinking": "só pensei"}]),
        ]
    }
    assert _last_ai_text(result) == "Resposta anterior."


def test_last_ai_text_default_when_empty():
    from marvin_hue.chat.subagents.task import _last_ai_text

    assert _last_ai_text({"messages": []}) == "Tarefa concluída."


# ----- Kelvin → RGB (Tanner Helland) -----


def test_kelvin_channels_in_range():
    from marvin_hue.chat.tools.color_temperature import kelvin_to_rgb

    for k in range(2000, 6501, 250):
        rgb = kelvin_to_rgb(k)
        assert all(isinstance(c, int) and 0 <= c <= 255 for c in rgb), (k, rgb)


def test_kelvin_warm_is_red_saturated_and_blue_low():
    from marvin_hue.chat.tools.color_temperature import kelvin_to_rgb

    r, g, b = kelvin_to_rgb(2000)
    assert r == 255
    assert b < g < r


def test_kelvin_blue_rises_monotonically():
    from marvin_hue.chat.tools.color_temperature import kelvin_to_rgb

    blues = [kelvin_to_rgb(k)[2] for k in range(2000, 6501, 500)]
    assert blues == sorted(blues)
    assert blues[-1] > blues[0]


@pytest.mark.parametrize(
    ("kelvin", "rgb"),
    [
        (2000, (255, 137, 14)),
        (2700, (255, 167, 87)),
        (4000, (255, 206, 166)),
        (6500, (255, 254, 250)),
    ],
)
def test_kelvin_pinned_values(kelvin, rgb):
    from marvin_hue.chat.tools.color_temperature import kelvin_to_rgb

    assert kelvin_to_rgb(kelvin) == rgb


def test_message_text_none_text_block():
    from marvin_hue.chat.messages import message_text

    assert message_text([{"type": "text", "text": None}, {"type": "text"}]) == ""
    assert message_text(None) == ""


@pytest.mark.parametrize(("raw", "clamped"), [(1000, 2000), (1999, 2000), (9000, 6500)])
def test_kelvin_is_clamped(raw, clamped):
    from marvin_hue.chat.tools.color_temperature import clamp_kelvin, kelvin_to_rgb

    assert clamp_kelvin(raw) == clamped
    assert kelvin_to_rgb(raw) == kelvin_to_rgb(clamped)
