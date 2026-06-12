"""Smoke de COMPOSIÇÃO: o orquestrador real é construído e invocado de uma vez.

Mocka APENAS o provider (modelo fake). Tudo o mais é real: create_agent,
as 10 light tools + a tool task, os 5 middleware e os 3 subagents reais. É o
único teste que exercita o seam de composição ponta-a-ponta (sem mockar
create_agent / build_light_tools / build_subagents).
"""
from __future__ import annotations

import pytest


def _patch_provider(monkeypatch, bindable_model_factory):
    import marvin_hue.chat.agents.react_agent as ra

    class _FakeProvider:
        model = bindable_model_factory()

    monkeypatch.setattr(
        ra.LLMProviderFactory, "create",
        classmethod(lambda cls, **kw: _FakeProvider()),
    )


@pytest.mark.asyncio
async def test_real_orchestrator_composes_and_ainvokes(
    monkeypatch, fake_controller, fake_manager, bindable_model_factory
):
    from marvin_hue.chat import create_hue_agent

    _patch_provider(monkeypatch, bindable_model_factory)
    # Nada mais é mockado: grafo real + tools reais + middleware real + subagents reais.
    agent = create_hue_agent(controller=fake_controller, manager=fake_manager)

    out = await agent.ainvoke("oi", session_id="s")
    assert isinstance(out, str) and out


def test_real_orchestrator_sync_invoke(
    monkeypatch, fake_controller, fake_manager, bindable_model_factory
):
    from marvin_hue.chat import create_hue_agent

    _patch_provider(monkeypatch, bindable_model_factory)
    agent = create_hue_agent(controller=fake_controller, manager=fake_manager)

    out = agent.invoke("oi", session_id="s")
    assert isinstance(out, str) and out
