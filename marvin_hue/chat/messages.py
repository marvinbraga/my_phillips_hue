"""Helpers de mensagens do chat compartilhados por orquestrador e subagents.

Módulo folha (sem imports do pacote ``chat``) para evitar import circular entre
``agents/react_agent.py`` e ``subagents/task.py``.
"""

from __future__ import annotations

from typing import Any


def message_text(content: Any) -> str:
    """Texto visível de uma AIMessage.

    Modelos com raciocínio (ex.: Claude 5) devolvem ``content`` como lista de
    blocos (``thinking``, ``text``, ...). Só os blocos ``text`` vão para o usuário.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "".join(parts)
    return str(content) if content else ""
