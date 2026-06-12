"""Testes de caracterização do agente ATUAL (pré-harness).

Capturam o comportamento existente, incluindo limitações conhecidas, para
detectar regressões durante a migração. Marcados como legacy: serão removidos
quando o harness novo cobrir os mesmos cenários.
"""
from __future__ import annotations

import pytest


@pytest.mark.legacy
def test_create_hue_agent_smoke(fake_controller, fake_manager, monkeypatch):
    """O factory atual instancia sem erro com provider mockado."""
    from marvin_hue.chat import create_hue_agent

    # Evita criação de LLM real interceptando o factory de provider.
    import marvin_hue.chat.agents.react_agent as ra

    class _FakeModel:
        def bind_tools(self, *a, **k):
            return self

    class _FakeProvider:
        model = _FakeModel()

    monkeypatch.setattr(
        ra.LLMProviderFactory, "create",
        classmethod(lambda cls, **kw: _FakeProvider()),
    )
    monkeypatch.setattr(
        ra, "create_react_agent", lambda **kw: object()
    )

    agent = create_hue_agent(controller=fake_controller, manager=fake_manager)
    assert agent is not None


@pytest.mark.legacy
def test_conversation_history_is_instance_attribute(fake_controller, fake_manager, monkeypatch):
    """DOCUMENTA O BUG #2: histórico é atributo de instância (compartilhado)."""
    import marvin_hue.chat.agents.react_agent as ra

    class _FakeProvider:
        model = type("M", (), {"bind_tools": lambda self, *a, **k: self})()

    monkeypatch.setattr(
        ra.LLMProviderFactory, "create",
        classmethod(lambda cls, **kw: _FakeProvider()),
    )
    monkeypatch.setattr(ra, "create_react_agent", lambda **kw: object())

    agent = ra.HueLightAgent(fake_controller, fake_manager)
    assert hasattr(agent, "_conversation_history")
    assert agent._conversation_history == []
