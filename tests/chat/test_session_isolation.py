"""Garante que duas sessões (thread_id) não compartilham histórico."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def patched_agent(monkeypatch, fake_controller, fake_manager):
    import marvin_hue.chat.agents.react_agent as ra

    class _FakeProvider:
        model = type("M", (), {"bind_tools": lambda self, *a, **k: self})()

    monkeypatch.setattr(
        ra.LLMProviderFactory, "create",
        classmethod(lambda cls, **kw: _FakeProvider()),
    )

    # Agente fake compilado que ecoa thread_id no estado.
    class _FakeCompiled:
        def __init__(self):
            self.calls = []

        def invoke(self, payload, config=None):
            tid = (config or {}).get("configurable", {}).get("thread_id")
            self.calls.append(tid)
            from langchain_core.messages import AIMessage
            return {"messages": [AIMessage(content=f"ok:{tid}")]}

        async def ainvoke(self, payload, config=None):
            return self.invoke(payload, config)

    monkeypatch.setattr(ra, "create_react_agent", lambda **kw: _FakeCompiled())
    return ra.HueLightAgent(fake_controller, fake_manager)


def test_no_shared_history_attribute(patched_agent):
    """O agente não deve mais manter _conversation_history mutável de instância."""
    assert not hasattr(patched_agent, "_conversation_history")


@pytest.mark.asyncio
async def test_invoke_requires_thread_id(patched_agent):
    """ainvoke aceita session_id e o repassa como thread_id ao checkpointer."""
    r1 = await patched_agent.ainvoke("oi", session_id="sessao-A")
    r2 = await patched_agent.ainvoke("oi", session_id="sessao-B")
    assert "sessao-A" in r1
    assert "sessao-B" in r2


@pytest.mark.asyncio
async def test_concurrent_sessions_do_not_mix(patched_agent):
    """ainvokes INTERCALADOS em sessões distintas não se misturam.

    Honestidade: o InMemorySaver NÃO documenta atomicidade de
    read-modify-write sob concorrência — este teste é a rede de DETECÇÃO,
    não uma prova de atomicidade. Se um dia falhar de forma intermitente,
    é sinal para antecipar um checkpointer com locking real (Fase 5.2).
    """
    import asyncio

    results = await asyncio.gather(
        *[patched_agent.ainvoke("oi", session_id="sessao-A") for _ in range(5)],
        *[patched_agent.ainvoke("oi", session_id="sessao-B") for _ in range(5)],
    )
    assert all("sessao-A" in r for r in results[:5])
    assert all("sessao-B" in r for r in results[5:])
