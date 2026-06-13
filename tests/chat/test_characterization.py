"""Testes de caracterização do agente ATUAL (pré-harness).

Capturam o comportamento existente, incluindo limitações conhecidas, para
detectar regressões durante a migração. Marcados como legacy: serão removidos
quando o harness novo cobrir os mesmos cenários.
"""
from __future__ import annotations

import pytest


@pytest.mark.legacy
def test_create_hue_agent_smoke(fake_controller, fake_manager, monkeypatch, bindable_model_factory):
    """O factory instancia sem erro com provider mockado (smoke)."""
    from marvin_hue.chat import create_hue_agent

    # Evita criação de LLM real interceptando o factory de provider.
    import marvin_hue.chat.agents.react_agent as ra

    class _FakeProvider:
        model = bindable_model_factory()

    monkeypatch.setattr(
        ra.LLMProviderFactory, "create",
        classmethod(lambda cls, **kw: _FakeProvider()),
    )
    monkeypatch.setattr(ra, "create_agent", lambda **kw: object())

    agent = create_hue_agent(controller=fake_controller, manager=fake_manager)
    assert agent is not None

# NOTA: o teste que documentava o BUG #2 (_conversation_history de instância)
# foi removido na Tarefa 1.2 — o bug foi corrigido (memória por thread_id via
# checkpointer). O comportamento correto é coberto por
# tests/chat/test_session_isolation.py::test_no_shared_history_attribute.
