"""Texto visível de AIMessage com conteúdo em blocos (modelos com raciocínio)."""
from __future__ import annotations

from marvin_hue.chat.agents.react_agent import _message_text


def test_plain_string_passes_through():
    assert _message_text("olá") == "olá"


def test_thinking_blocks_are_dropped_and_text_joined():
    content = [
        {"type": "thinking", "thinking": "", "signature": "abc"},
        {"type": "text", "text": "Parte 1. "},
        {"type": "text", "text": "Parte 2."},
    ]
    assert _message_text(content) == "Parte 1. Parte 2."


def test_only_thinking_yields_empty_text():
    assert _message_text([{"type": "thinking", "thinking": "x"}]) == ""


def test_empty_content():
    assert _message_text([]) == ""
    assert _message_text(None) == ""
