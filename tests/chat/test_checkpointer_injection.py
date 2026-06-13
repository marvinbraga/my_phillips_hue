"""Persistência opcional: o checkpointer é INJETADO; o agente nunca abre SQLite."""
from __future__ import annotations

import pytest


def test_sqlite_saver_smoke():
    """SqliteSaver.from_conn_string é um context manager (ciclo de vida do chamador)."""
    from langgraph.checkpoint.sqlite import SqliteSaver
    with SqliteSaver.from_conn_string(":memory:") as saver:
        assert saver is not None


def test_agent_uses_injected_checkpointer(monkeypatch, fake_controller, fake_manager, bindable_model_factory):
    """Quando um checkpointer é injetado, o agente o usa (não cria InMemorySaver)."""
    import marvin_hue.chat.agents.react_agent as ra

    sentinel = object()

    class _FakeProvider:
        model = bindable_model_factory()

    monkeypatch.setattr(
        ra.LLMProviderFactory, "create",
        classmethod(lambda cls, **kw: _FakeProvider()),
    )
    monkeypatch.setattr(ra, "create_agent", lambda **kw: kw.get("checkpointer"))

    agent = ra.HueLightAgent(fake_controller, fake_manager, checkpointer=sentinel)
    assert agent._checkpointer is sentinel


def test_agent_defaults_to_in_memory_saver(monkeypatch, fake_controller, fake_manager, bindable_model_factory):
    """Sem injeção, o agente cria um InMemorySaver (volátil) — sem abrir SQLite."""
    import marvin_hue.chat.agents.react_agent as ra
    from langgraph.checkpoint.memory import InMemorySaver

    class _FakeProvider:
        model = bindable_model_factory()

    monkeypatch.setattr(
        ra.LLMProviderFactory, "create",
        classmethod(lambda cls, **kw: _FakeProvider()),
    )
    monkeypatch.setattr(ra, "create_agent", lambda **kw: object())

    agent = ra.HueLightAgent(fake_controller, fake_manager)
    assert isinstance(agent._checkpointer, InMemorySaver)


@pytest.mark.asyncio
async def test_async_delete_paths_with_async_sqlite(
    monkeypatch, fake_controller, fake_manager, bindable_model_factory
):
    """REGRESSÃO: sob AsyncSqliteSaver, aclear_history e a eviction async NÃO
    podem chamar delete_thread síncrono do event loop (InvalidStateError).
    Devem aguardar adelete_thread."""
    import marvin_hue.chat.agents.react_agent as ra
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    class _FakeProvider:
        model = bindable_model_factory()

    monkeypatch.setattr(
        ra.LLMProviderFactory, "create",
        classmethod(lambda cls, **kw: _FakeProvider()),
    )
    monkeypatch.setattr(ra, "create_agent", lambda **kw: object())

    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        await saver.setup()  # cria as tabelas (em produção o grafo faz no 1º write)
        agent = ra.HueLightAgent(fake_controller, fake_manager, checkpointer=saver)

        # aclear_history no event loop NÃO deve levantar InvalidStateError.
        await agent.aclear_history("s1")

        # Eviction pelo caminho async (como ainvoke/astream fazem): também não levanta.
        agent._max_sessions = 1
        agent._session_last_access = {"velha": 1.0}
        for tid in agent._touch_session("nova"):
            await agent._adelete_thread(tid)
        assert "velha" not in agent._session_last_access
