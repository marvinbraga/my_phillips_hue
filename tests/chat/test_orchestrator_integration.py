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


@pytest.mark.asyncio
async def test_eye_safety_clamp_flows_through_assembled_graph(
    monkeypatch, fake_controller, fake_manager
):
    """SEAM COMPORTAMENTAL: um tool_call do modelo atravessa o grafo REAL
    (EyeSafetyMiddleware → tool closure → controller) e chega clampado.

    Pede set_brightness("Fita Led", 100%); o middleware clampa 100->25 (pct), a
    tool converte p/ hue, e o controller recebe <=63. Prova a segurança ocular
    ponta-a-ponta no agente montado, não só nas peças isoladas."""
    import marvin_hue.chat.agents.react_agent as ra
    from marvin_hue.chat import create_hue_agent
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage

    # Fake que (1) emite um tool_call para set_brightness e depois (2) finaliza.
    class _ToolCallingFake(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    responses = [
        AIMessage(
            content="",
            tool_calls=[{
                "name": "set_brightness",
                "args": {"light_name": "Fita Led", "brightness": 100},
                "id": "tc-1",
            }],
        ),
        AIMessage(content="brilho ajustado"),
    ]
    fake_controller.set_brightness.return_value = True

    class _FakeProvider:
        model = _ToolCallingFake(responses=responses)

    monkeypatch.setattr(
        ra.LLMProviderFactory, "create",
        classmethod(lambda cls, **kw: _FakeProvider()),
    )
    agent = create_hue_agent(controller=fake_controller, manager=fake_manager)

    await agent.ainvoke("deixa a fita led no máximo", session_id="s")

    # O EyeSafetyMiddleware clampou 100%->25% ANTES da tool; a tool converteu
    # p/ hue (25% de 254 = 63) e chamou o controller com <=63.
    fake_controller.set_brightness.assert_called()
    name, hue = fake_controller.set_brightness.call_args[0][:2]
    assert name == "Fita Led"
    assert hue <= 63  # nunca o valor de 100% (254)
