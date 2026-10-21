"""HITL ponta-a-ponta no orquestrador REAL (create_hue_agent + subagents reais).

Só o provider é trocado por um modelo roteirizado pelo conteúdo. Cobre:
interrupt → aprovar/rejeitar, tools sem HITL, flag desligada, mensagem nova
com aprovação pendente e interrupções vindas de subagents (tool ``task``).
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from marvin_hue.apply_result import ApplyResult
from marvin_hue.chat.hitl import (
    ApprovalRequired,
    InvalidDecisionError,
    NoPendingApprovalError,
)
from tests.chat.fakes import FakeMirror, scripted_model, services


def _system(messages) -> str:
    first = messages[0] if messages else None
    return first.content if isinstance(first, SystemMessage) else ""


def _call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


class Router:
    """Roteiro: orquestrador e scene-designer, decididos pela última mensagem."""

    def __init__(self, orch_calls, sub_call=None):
        self.orch_calls = orch_calls  # list[dict] de tool calls para o 1º passo
        self.sub_call = sub_call      # (HumanMessage) -> (name, args) | None
        self.orch_steps = 0
        self.sub_human_steps = 0

    def __call__(self, messages):
        last = messages[-1]
        if "scene-designer" in _system(messages):
            if isinstance(last, HumanMessage):
                self.sub_human_steps += 1
                name, args = self.sub_call(last)
                return _call(name, args, f"sub-{last.content}")
            return AIMessage(content=f"sub ok: {last.content}")
        self.orch_steps += 1
        if isinstance(last, HumanMessage):
            return AIMessage(content="", tool_calls=self.orch_calls)
        tool_texts = [m.content for m in messages if isinstance(m, ToolMessage)]
        return AIMessage(content="fim: " + " | ".join(tool_texts))


def _agent(monkeypatch, controller, manager, router, *, require_approval=True, mirror=None,
           checkpointer=None):
    import marvin_hue.chat.agents.react_agent as ra
    from marvin_hue.chat import create_hue_agent

    class _FakeProvider:
        model = scripted_model(router)

    monkeypatch.setattr(
        ra.LLMProviderFactory, "create", classmethod(lambda cls, **kw: _FakeProvider())
    )
    return create_hue_agent(
        controller=controller,
        manager=manager,
        require_approval=require_approval,
        services=services(mirror=mirror or FakeMirror()),
        checkpointer=checkpointer,
    )


START_MIRROR = [{"name": "start_mirror", "args": {"mode": "screen"}, "id": "tc-1"}]


@pytest.mark.asyncio
async def test_mutating_tool_interrupts_and_approve_executes(
    monkeypatch, fake_controller, fake_manager
):
    mirror = FakeMirror()
    agent = _agent(monkeypatch, fake_controller, fake_manager, Router(START_MIRROR), mirror=mirror)

    out = await agent.ainvoke("liga o espelhamento", session_id="s1")

    assert isinstance(out, ApprovalRequired)
    assert out.to_dict()["type"] == "approval_required"
    [req] = out.requests
    assert req.tool == "start_mirror"
    assert req.args == {"mode": "screen"}
    assert req.allowed_decisions == ("approve", "reject")
    assert req.description.startswith("Esta ação precisa da sua aprovação")
    assert mirror.start_calls == []  # nada executou antes da aprovação

    final = await agent.aresume("s1", [{"type": "approve"}])

    assert isinstance(final, str) and final.startswith("fim:")
    assert [mode for mode, _ in mirror.start_calls] == ["screen"]
    assert await agent.apending("s1") is None


@pytest.mark.asyncio
async def test_reject_skips_tool_and_tells_the_model(monkeypatch, fake_controller, fake_manager):
    mirror = FakeMirror()
    agent = _agent(monkeypatch, fake_controller, fake_manager, Router(START_MIRROR), mirror=mirror)
    await agent.ainvoke("liga o espelhamento", session_id="s1")

    final = await agent.aresume("s1", [{"type": "reject", "message": "agora não"}])

    assert mirror.start_calls == []
    assert "rejeitou `start_mirror`" in final and "agora não" in final
    state = await agent._agent.aget_state(agent._config_for("s1"))
    tool_msgs = [m for m in state.values["messages"] if isinstance(m, ToolMessage)]
    assert tool_msgs[-1].status == "error"


@pytest.mark.asyncio
async def test_reject_without_message_uses_default_notice(
    monkeypatch, fake_controller, fake_manager
):
    agent = _agent(monkeypatch, fake_controller, fake_manager, Router(START_MIRROR))
    await agent.ainvoke("liga", session_id="s1")
    final = await agent.aresume("s1", [{"type": "reject"}])
    assert "The tool was not executed" in final


@pytest.mark.asyncio
async def test_read_only_tool_never_interrupts(monkeypatch, fake_controller, fake_manager):
    router = Router([{"name": "get_mirror_status", "args": {}, "id": "tc-1"}])
    agent = _agent(monkeypatch, fake_controller, fake_manager, router)

    out = await agent.ainvoke("status?", session_id="s1")

    assert isinstance(out, str) and out.startswith("fim:")
    assert await agent.apending("s1") is None


@pytest.mark.asyncio
async def test_flag_off_executes_without_approval(monkeypatch, fake_controller, fake_manager):
    mirror = FakeMirror()
    agent = _agent(
        monkeypatch, fake_controller, fake_manager, Router(START_MIRROR),
        require_approval=False, mirror=mirror,
    )

    out = await agent.ainvoke("liga o espelhamento", session_id="s1")

    assert isinstance(out, str) and out.startswith("fim:")
    assert len(mirror.start_calls) == 1


@pytest.mark.asyncio
async def test_new_message_while_pending_returns_the_pending_request(
    monkeypatch, fake_controller, fake_manager
):
    """Rodar um turno novo deixaria uma tool call sem ToolMessage (thread quebrada)."""
    router = Router(START_MIRROR)
    agent = _agent(monkeypatch, fake_controller, fake_manager, router)
    first = await agent.ainvoke("liga", session_id="s1")
    steps = router.orch_steps

    again = await agent.ainvoke("outra coisa", session_id="s1")

    assert isinstance(again, ApprovalRequired)
    assert [r.id for r in again.requests] == [r.id for r in first.requests]
    assert router.orch_steps == steps  # o modelo nem foi chamado


@pytest.mark.asyncio
async def test_resume_without_pending_and_bad_decisions(
    monkeypatch, fake_controller, fake_manager
):
    agent = _agent(monkeypatch, fake_controller, fake_manager, Router(START_MIRROR))
    with pytest.raises(NoPendingApprovalError):
        await agent.aresume("vazio", [{"type": "approve"}])

    await agent.ainvoke("liga", session_id="s1")
    with pytest.raises(InvalidDecisionError):
        await agent.aresume("s1", [{"type": "approve"}, {"type": "approve"}])
    with pytest.raises(InvalidDecisionError):
        await agent.aresume("s1", [{"type": "edit"}])
    # Continua pendente depois das decisões inválidas (falha fechado).
    assert await agent.apending("s1") is not None


@pytest.mark.asyncio
async def test_sessions_do_not_share_pending(monkeypatch, fake_controller, fake_manager):
    agent = _agent(monkeypatch, fake_controller, fake_manager, Router(START_MIRROR))
    await agent.ainvoke("liga", session_id="A")
    assert await agent.apending("B") is None
    with pytest.raises(NoPendingApprovalError):
        await agent.aresume("B", [{"type": "approve"}])


@pytest.mark.asyncio
async def test_astream_yields_approval_required(monkeypatch, fake_controller, fake_manager):
    agent = _agent(monkeypatch, fake_controller, fake_manager, Router(START_MIRROR))
    items = [item async for item in agent.astream("liga", session_id="s1")]
    assert isinstance(items[-1], ApprovalRequired)
    assert all(isinstance(i, str) for i in items[:-1])


def test_sync_invoke_returns_approval_required(monkeypatch, fake_controller, fake_manager):
    agent = _agent(monkeypatch, fake_controller, fake_manager, Router(START_MIRROR))
    out = agent.invoke("liga", session_id="s1")
    assert isinstance(out, ApprovalRequired)
    assert isinstance(agent.invoke("de novo", session_id="s1"), ApprovalRequired)


# --- Subagents: o interrupt nasce dentro da tool `task` -----------------------


def _task(description: str, call_id: str) -> dict:
    return {
        "name": "task",
        "args": {"description": description, "subagent_type": "scene-designer"},
        "id": call_id,
    }


@pytest.mark.asyncio
async def test_subagent_interrupt_propagates_and_resumes_without_rerun(
    monkeypatch, fake_controller, fake_manager
):
    fake_controller.apply_light_config.return_value = ApplyResult(
        applied=("Lâmpada 1",), failed=()
    )
    router = Router(
        [_task("noite_relaxante", "o1")],
        sub_call=lambda m: ("apply_config", {"config_name": m.content}),
    )
    agent = _agent(monkeypatch, fake_controller, fake_manager, router)

    out = await agent.ainvoke("deixa a sala relaxante", session_id="s1")

    assert isinstance(out, ApprovalRequired)
    [req] = out.requests
    assert req.tool == "apply_config" and req.args == {"config_name": "noite_relaxante"}
    fake_controller.apply_light_config.assert_not_called()

    final = await agent.aresume("s1", [{"type": "approve"}])

    fake_controller.apply_light_config.assert_called_once()
    assert final.startswith("fim: sub ok:")
    # Retomou do nó HITL do subagent: o modelo do subagent não foi rechamado
    # com a HumanMessage (args aprovados == args executados).
    assert router.sub_human_steps == 1


@pytest.mark.asyncio
async def test_parallel_subagent_interrupts_resume_by_id(
    monkeypatch, fake_controller, fake_manager
):
    fake_controller.apply_light_config.return_value = ApplyResult(
        applied=("Lâmpada 1",), failed=()
    )
    router = Router(
        [_task("noite_relaxante", "o1"), _task("outra", "o2")],
        sub_call=lambda m: ("apply_config", {"config_name": m.content}),
    )
    agent = _agent(monkeypatch, fake_controller, fake_manager, router)

    out = await agent.ainvoke("duas cenas", session_id="s1")

    assert isinstance(out, ApprovalRequired)
    by_name = {r.args["config_name"]: i for i, r in enumerate(out.requests)}
    assert set(by_name) == {"noite_relaxante", "outra"}
    decisions = [None, None]
    decisions[by_name["noite_relaxante"]] = {"type": "approve"}
    decisions[by_name["outra"]] = {"type": "reject"}

    final = await agent.aresume("s1", decisions)

    assert isinstance(final, str), final
    fake_controller.apply_light_config.assert_called_once()
    assert fake_controller.apply_light_config.call_args[0][0].name == "noite_relaxante"
    assert router.sub_human_steps == 2


@pytest.mark.asyncio
async def test_parallel_subagent_decisions_matched_by_id(
    monkeypatch, fake_controller, fake_manager
):
    fake_controller.apply_light_config.return_value = ApplyResult(
        applied=("Lâmpada 1",), failed=()
    )
    router = Router(
        [_task("noite_relaxante", "o1"), _task("outra", "o2")],
        sub_call=lambda m: ("apply_config", {"config_name": m.content}),
    )
    agent = _agent(monkeypatch, fake_controller, fake_manager, router)
    out = await agent.ainvoke("duas cenas", session_id="s1")

    # Ordem invertida de propósito: o id manda, não a posição.
    decisions = [
        {"id": r.id, "type": "approve" if r.args["config_name"] == "noite_relaxante" else "reject"}
        for r in reversed(out.requests)
    ]
    await agent.aresume("s1", decisions)

    fake_controller.apply_light_config.assert_called_once()
    assert fake_controller.apply_light_config.call_args[0][0].name == "noite_relaxante"


@pytest.mark.asyncio
async def test_pending_survives_agent_rebuild_with_sqlite(
    monkeypatch, fake_controller, fake_manager, tmp_path
):
    """Checkpointer persistente: outro agente (restart/configure) retoma a thread."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    mirror = FakeMirror()
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "chat.sqlite")) as saver:
        first = _agent(
            monkeypatch, fake_controller, fake_manager, Router(START_MIRROR),
            mirror=mirror, checkpointer=saver,
        )
        assert isinstance(await first.ainvoke("liga", session_id="s1"), ApprovalRequired)

        second = _agent(
            monkeypatch, fake_controller, fake_manager, Router(START_MIRROR),
            mirror=mirror, checkpointer=saver,
        )
        assert await second.apending("s1") is not None
        final = await second.aresume("s1", [{"type": "approve"}])

    assert final.startswith("fim:")
    assert len(mirror.start_calls) == 1
