"""Garante que duas sessões (thread_id) não compartilham histórico."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def patched_agent(monkeypatch, fake_controller, fake_manager, bindable_model_factory):
    import marvin_hue.chat.agents.react_agent as ra
    from langchain_core.messages import AIMessage

    # Fake REAL (BaseChatModel) com bind_tools: SummarizationMiddleware resolve o
    # model na construção, e build_subagents (create_agent real) vincula tools.
    class _FakeProvider:
        model = bindable_model_factory(50)

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
            return {"messages": [AIMessage(content=f"ok:{tid}")]}

        async def ainvoke(self, payload, config=None):
            return self.invoke(payload, config)

    monkeypatch.setattr(ra, "create_agent", lambda **kw: _FakeCompiled())
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


def test_real_checkpointer_isolates_history(monkeypatch, fake_controller, fake_manager):
    """Integração: grafo REAL + InMemorySaver REAL isolam histórico por thread.

    Diferente dos testes de plumbing acima (que mockam o agente compilado), aqui
    exercitamos o caminho real do checkpointer — uma regressão que quebrasse o
    isolamento de fato (e não só a propagação do thread_id) FALHARIA aqui.
    """
    import marvin_hue.chat.agents.react_agent as ra
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage

    # Fake que aceita bind_tools (a pilha de middleware, ex. TodoList, adiciona
    # tools que o create_agent vincula ao model). As respostas não têm tool_calls,
    # então o agente não entra em loop.
    class _BindableFake(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    fake_model = _BindableFake(responses=[AIMessage(content=f"resp{i}") for i in range(6)])
    monkeypatch.setattr(
        ra.LLMProviderFactory, "create",
        classmethod(lambda cls, **kw: type("P", (), {"model": fake_model})()),
    )
    # Sem light tools próprias: o foco é o isolamento do checkpointer.
    monkeypatch.setattr(ra, "build_light_tools", lambda *a, **k: [])
    # NÃO mockar create_agent: grafo real + InMemorySaver real.
    agent = ra.HueLightAgent(fake_controller, fake_manager)

    agent.invoke("ALPHA-marker", session_id="A")
    agent.invoke("BETA-marker", session_id="B")

    def thread_text(thread_id: str) -> str:
        state = agent._agent.get_state({"configurable": {"thread_id": thread_id}})
        return " ".join(str(m.content) for m in state.values["messages"])

    a_text, b_text = thread_text("A"), thread_text("B")
    assert "ALPHA-marker" in a_text and "BETA-marker" not in a_text
    assert "BETA-marker" in b_text and "ALPHA-marker" not in b_text


def test_lru_eviction_drops_oldest(patched_agent):
    """_touch_session evicta a sessão menos recentemente usada ao exceder o limite."""
    patched_agent._max_sessions = 3
    for sid in ["s1", "s2", "s3"]:
        patched_agent._touch_session(sid)
    patched_agent._touch_session("s1")   # s1 vira a mais recente; s2 é a mais antiga
    patched_agent._touch_session("s4")   # excede 3 -> evicta a mais antiga (s2)
    assert "s2" not in patched_agent._session_last_access
    assert set(patched_agent._session_last_access) == {"s1", "s3", "s4"}


def test_clear_history_purges_only_that_session(patched_agent):
    """clear_history(session_id) deleta SÓ aquela thread (nunca global)."""
    patched_agent._checkpointer = MagicMock()
    patched_agent._touch_session("keep")
    patched_agent._touch_session("drop")

    patched_agent.clear_history("drop")

    patched_agent._checkpointer.delete_thread.assert_called_once_with("drop")
    assert "drop" not in patched_agent._session_last_access
    assert "keep" in patched_agent._session_last_access


def test_stream_does_not_reinvoke(monkeypatch, fake_controller, fake_manager, bindable_model_factory):
    """Regressão do BUG #1: stream() NÃO re-invoca o agente após o streaming."""
    import marvin_hue.chat.agents.react_agent as ra
    from langchain_core.messages import AIMessage

    class _Recorder:
        def __init__(self):
            self.invoked = 0
            self.streamed = 0

        def stream(self, payload, config=None, stream_mode=None):
            self.streamed += 1
            yield {"messages": [AIMessage(content="final")]}

        def invoke(self, payload, config=None):
            self.invoked += 1
            return {"messages": [AIMessage(content="x")]}

    rec = _Recorder()
    fake_model = bindable_model_factory()
    monkeypatch.setattr(
        ra.LLMProviderFactory, "create",
        classmethod(lambda cls, **kw: type("P", (), {"model": fake_model})()),
    )
    monkeypatch.setattr(ra, "create_agent", lambda **kw: rec)
    agent = ra.HueLightAgent(fake_controller, fake_manager)

    chunks = list(agent.stream("oi", session_id="s"))

    assert chunks == ["final"]
    assert rec.streamed == 1
    assert rec.invoked == 0  # sem re-invocação pós-stream (bug #1)
