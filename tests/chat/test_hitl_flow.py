"""HITL ponta-a-ponta no orquestrador REAL (create_hue_agent + subagents reais).

Só o provider é trocado por um modelo roteirizado pelo conteúdo
(``tests.chat.fakes.HitlRouter``). Cobre: interrupt → aprovar/rejeitar,
aprovação encadeada, tools sem HITL, flag desligada (inclusive com
pendências antigas no SQLite), mensagem nova com aprovação pendente, locks
por sessão e interrupções vindas de subagents (tool ``task``).
"""
from __future__ import annotations

import asyncio

import pytest
from langchain_core.messages import ToolMessage

from marvin_hue.chat.hitl import (
    CANCELLED_MESSAGE,
    ApprovalRequired,
    InvalidDecisionError,
    NoPendingApprovalError,
)
from tests.chat.fakes import (
    CREATE_SCHEDULE,
    START_MIRROR,
    FakeMirror,
    FakeSchedules,
    HitlRouter,
    create_config_call,
    decide_all,
    hitl_agent,
    task_call,
)


@pytest.fixture
def mirror():
    return FakeMirror()


@pytest.fixture
def agent(monkeypatch, fake_controller, fake_manager, mirror):
    return hitl_agent(
        monkeypatch, fake_controller, fake_manager, HitlRouter([START_MIRROR]), mirror=mirror
    )


async def _tool_messages(agent, session_id):
    state = await agent._agent.aget_state(agent._config_for(session_id))
    return [m for m in state.values["messages"] if isinstance(m, ToolMessage)]


@pytest.mark.asyncio
async def test_mutating_tool_interrupts_and_approve_executes(agent, mirror):
    out = await agent.ainvoke("liga o espelhamento", session_id="s1")

    assert isinstance(out, ApprovalRequired)
    assert out.to_dict()["type"] == "approval_required"
    [req] = out.requests
    assert req.tool == "start_mirror"
    assert req.args == {"mode": "screen"}
    assert req.allowed_decisions == ("approve", "reject")
    assert req.description.startswith("Iniciar o espelhamento")
    assert mirror.start_calls == []  # nada executou antes da aprovação

    final = await agent.aresume("s1", decide_all(out))

    assert isinstance(final, str) and final.startswith("fim:")
    assert [mode for mode, _ in mirror.start_calls] == ["screen"]
    assert await agent.apending("s1") is None


@pytest.mark.asyncio
async def test_reject_skips_tool_and_tells_the_model(agent, mirror):
    out = await agent.ainvoke("liga o espelhamento", session_id="s1")

    final = await agent.aresume(
        "s1", [{"id": out.requests[0].id, "type": "reject", "message": "agora não"}]
    )

    assert mirror.start_calls == []
    assert "rejeitou `start_mirror`" in final and "agora não" in final
    assert (await _tool_messages(agent, "s1"))[-1].status == "error"


@pytest.mark.asyncio
async def test_reject_without_message_uses_default_notice(agent):
    out = await agent.ainvoke("liga", session_id="s1")
    final = await agent.aresume("s1", decide_all(out, "reject"))
    assert "The tool was not executed" in final


@pytest.mark.asyncio
async def test_resume_can_return_a_second_approval(monkeypatch, fake_controller, fake_manager):
    """Aprovar o 1º passo leva o modelo a outra tool com HITL: novo pedido."""
    mirror, schedules = FakeMirror(), FakeSchedules()
    router = HitlRouter([START_MIRROR], [CREATE_SCHEDULE])
    agent = hitl_agent(
        monkeypatch, fake_controller, fake_manager, router, mirror=mirror, schedules=schedules
    )

    first = await agent.ainvoke("espelha e agenda", session_id="s1")
    second = await agent.aresume("s1", decide_all(first))

    assert isinstance(second, ApprovalRequired)
    assert [r.tool for r in second.requests] == ["create_schedule"]
    assert len(mirror.start_calls) == 1 and schedules.created == []
    # As decisões do 1º conjunto não valem para o 2º (ids diferentes).
    with pytest.raises(InvalidDecisionError):
        await agent.aresume("s1", decide_all(first))

    final = await agent.aresume("s1", decide_all(second))

    assert final.startswith("fim:")
    assert [c["name"] for c in schedules.created] == ["noite"]


@pytest.mark.asyncio
async def test_ungated_mutations_never_interrupt(monkeypatch, fake_controller, fake_manager):
    """apply_config, stop_mirror, undo_last_scene ficam fora (reversíveis)."""
    mirror = FakeMirror(mode="screen")
    router = HitlRouter([
        {"name": "get_mirror_status", "args": {}},
        {"name": "stop_mirror", "args": {}},
        {"name": "apply_config", "args": {"config_name": "noite_relaxante"}},
    ])
    agent = hitl_agent(monkeypatch, fake_controller, fake_manager, router, mirror=mirror)

    out = await agent.ainvoke("para tudo e aplica a noite", session_id="s1")

    assert isinstance(out, str) and out.startswith("fim:")
    assert mirror.stop_calls == 1
    fake_controller.apply_light_config.assert_called_once()
    assert await agent.apending("s1") is None


@pytest.mark.asyncio
async def test_flag_off_executes_without_approval(
    monkeypatch, fake_controller, fake_manager, mirror
):
    agent = hitl_agent(
        monkeypatch, fake_controller, fake_manager, HitlRouter([START_MIRROR]),
        require_approval=False, mirror=mirror,
    )

    out = await agent.ainvoke("liga o espelhamento", session_id="s1")

    assert isinstance(out, str) and out.startswith("fim:")
    assert len(mirror.start_calls) == 1


@pytest.mark.asyncio
async def test_flag_off_cancels_stale_pending_from_sqlite(
    monkeypatch, fake_controller, fake_manager, tmp_path
):
    """Flag ligada → pendência no SQLite → restart com a flag desligada.

    O grafo sem HITL não vê a interrupção antiga: sobraria uma tool call sem
    ToolMessage. O turno seguinte fecha a chamada (sem executar) e segue.
    """
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    mirror = FakeMirror()
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "chat.sqlite")) as saver:
        on = hitl_agent(
            monkeypatch, fake_controller, fake_manager, HitlRouter([START_MIRROR]),
            mirror=mirror, checkpointer=saver,
        )
        assert isinstance(await on.ainvoke("liga", session_id="s1"), ApprovalRequired)

        off = hitl_agent(
            monkeypatch, fake_controller, fake_manager, HitlRouter(),
            require_approval=False, mirror=mirror, checkpointer=saver,
        )
        assert await off.apending("s1") is None
        out = await off.ainvoke("oi de novo", session_id="s1")

        assert out.startswith("fim:")
        assert mirror.start_calls == []
        cancelled = await _tool_messages(off, "s1")
        assert [m.content for m in cancelled] == [CANCELLED_MESSAGE]
        assert cancelled[0].status == "error"
        assert await off.apending("s1") is None


@pytest.mark.asyncio
async def test_flag_off_cancels_stale_subagent_pending(
    monkeypatch, fake_controller, fake_manager, tmp_path
):
    """Pendência que nasceu num subagent (task) também some com a flag desligada."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "chat.sqlite")) as saver:
        on = hitl_agent(
            monkeypatch, fake_controller, fake_manager,
            HitlRouter([task_call("sala_calma")], sub_call=_sub_create_config),
            checkpointer=saver,
        )
        out = await on.ainvoke("cria uma cena", session_id="s1")
        assert isinstance(out, ApprovalRequired)

        off = hitl_agent(
            monkeypatch, fake_controller, fake_manager, HitlRouter(),
            require_approval=False, checkpointer=saver,
        )
        assert await off.apending("s1") is None
        with pytest.raises(NoPendingApprovalError):
            await off.aresume("s1", decide_all(out))

        reply = await off.ainvoke("oi", session_id="s1")

        assert reply.startswith("fim:")
        fake_manager.add_config.assert_not_called()
        assert [m.content for m in await _tool_messages(off, "s1")] == [CANCELLED_MESSAGE]
        assert await off.apending("s1") is None


def test_flag_off_cancels_stale_pending_sync(monkeypatch, fake_controller, fake_manager):
    from langgraph.checkpoint.memory import InMemorySaver

    saver, mirror = InMemorySaver(), FakeMirror()
    on = hitl_agent(
        monkeypatch, fake_controller, fake_manager, HitlRouter([START_MIRROR]),
        mirror=mirror, checkpointer=saver,
    )
    assert isinstance(on.invoke("liga", session_id="s1"), ApprovalRequired)
    off = hitl_agent(
        monkeypatch, fake_controller, fake_manager, HitlRouter(),
        require_approval=False, mirror=mirror, checkpointer=saver,
    )
    assert off.invoke("oi", session_id="s1").startswith("fim:")
    assert mirror.start_calls == []


@pytest.mark.asyncio
async def test_new_message_while_pending_returns_the_pending_request(
    monkeypatch, fake_controller, fake_manager
):
    """Rodar um turno novo deixaria uma tool call sem ToolMessage (thread quebrada)."""
    router = HitlRouter([START_MIRROR])
    agent = hitl_agent(monkeypatch, fake_controller, fake_manager, router)
    first = await agent.ainvoke("liga", session_id="s1")
    steps = router.orch_steps

    again = await agent.ainvoke("outra coisa", session_id="s1")

    assert isinstance(again, ApprovalRequired)
    assert [r.id for r in again.requests] == [r.id for r in first.requests]
    assert router.orch_steps == steps  # o modelo nem foi chamado


@pytest.mark.asyncio
async def test_resume_without_pending(agent):
    with pytest.raises(NoPendingApprovalError, match="Nenhuma aprovação pendente"):
        await agent.aresume("vazio", [{"id": "x:0", "type": "approve"}])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("make", "match"),
    [
        (lambda rid: [{"type": "approve"}], "precisa do id"),
        (lambda rid: [{"id": rid, "type": "approve"}, {"type": "approve"}], "precisa do id"),
        (lambda rid: [{"id": rid, "type": "approve"}, {"id": rid, "type": "reject"}],
         "repetidas"),
        (lambda rid: [{"id": "outro:0", "type": "approve"}], "não batem"),
        (lambda rid: [{"id": rid, "type": "edit"}], "não permitida"),
    ],
    ids=["no-id", "mixed-ids", "duplicate-ids", "unknown-id", "edit"],
)
async def test_invalid_decisions_fail_closed(agent, mirror, make, match):
    out = await agent.ainvoke("liga", session_id="s1")
    with pytest.raises(InvalidDecisionError, match=match):
        await agent.aresume("s1", make(out.requests[0].id))
    assert mirror.start_calls == []
    assert await agent.apending("s1") is not None  # continua pendente


@pytest.mark.asyncio
async def test_sessions_do_not_share_pending(agent):
    out = await agent.ainvoke("liga", session_id="A")
    assert await agent.apending("B") is None
    with pytest.raises(NoPendingApprovalError):
        await agent.aresume("B", decide_all(out))


@pytest.mark.asyncio
async def test_concurrent_resumes_execute_once(agent, mirror):
    out = await agent.ainvoke("liga", session_id="s1")

    results = await asyncio.gather(
        agent.aresume("s1", decide_all(out)),
        agent.aresume("s1", decide_all(out)),
        return_exceptions=True,
    )

    assert len(mirror.start_calls) == 1
    assert sum(isinstance(r, str) for r in results) == 1
    assert sum(isinstance(r, NoPendingApprovalError) for r in results) == 1


@pytest.mark.asyncio
async def test_session_lock_is_shared_across_agent_instances(
    monkeypatch, fake_controller, fake_manager
):
    """O lock sobrevive a /api/chat/configure (agente novo, mesma sessão)."""
    from langgraph.checkpoint.memory import InMemorySaver

    from marvin_hue.chat.agents.react_agent import session_lock

    saver, mirror = InMemorySaver(), FakeMirror()
    old = hitl_agent(
        monkeypatch, fake_controller, fake_manager, HitlRouter([START_MIRROR]),
        mirror=mirror, checkpointer=saver,
    )
    new = hitl_agent(
        monkeypatch, fake_controller, fake_manager, HitlRouter([START_MIRROR]),
        mirror=mirror, checkpointer=saver,
    )
    out = await old.ainvoke("liga", session_id="s1")
    assert session_lock("s1") is session_lock("s1")

    results = await asyncio.gather(
        old.aresume("s1", decide_all(out)),
        new.aresume("s1", decide_all(out)),
        return_exceptions=True,
    )

    assert len(mirror.start_calls) == 1
    assert sum(isinstance(r, NoPendingApprovalError) for r in results) == 1


@pytest.mark.asyncio
async def test_clear_while_pending_drops_the_request(agent, mirror):
    out = await agent.ainvoke("liga", session_id="s1")

    await agent.aclear_history("s1")

    assert await agent.apending("s1") is None
    with pytest.raises(NoPendingApprovalError):
        await agent.aresume("s1", decide_all(out))
    assert mirror.start_calls == []


@pytest.mark.asyncio
async def test_astream_yields_approval_required(agent):
    items = [item async for item in agent.astream("liga", session_id="s1")]
    assert isinstance(items[-1], ApprovalRequired)
    assert all(isinstance(i, str) for i in items[:-1])


def test_sync_invoke_returns_approval_required(agent):
    out = agent.invoke("liga", session_id="s1")
    assert isinstance(out, ApprovalRequired)
    assert isinstance(agent.invoke("de novo", session_id="s1"), ApprovalRequired)


def test_sync_stream_yields_approval_required_then_pending(agent, mirror):
    items = list(agent.stream("liga", session_id="s1"))
    assert isinstance(items[-1], ApprovalRequired)
    again = list(agent.stream("outra", session_id="s1"))
    assert len(again) == 1 and isinstance(again[0], ApprovalRequired)
    assert mirror.start_calls == []


# --- Subagents: o interrupt nasce dentro da tool `task` -----------------------


def _sub_create_config(message):
    return create_config_call(str(message.content))


@pytest.mark.asyncio
async def test_subagent_interrupt_propagates_and_resumes_without_rerun(
    monkeypatch, fake_controller, fake_manager
):
    router = HitlRouter([task_call("sala_calma")], sub_call=_sub_create_config)
    agent = hitl_agent(monkeypatch, fake_controller, fake_manager, router)

    out = await agent.ainvoke("cria uma cena calma", session_id="s1")

    assert isinstance(out, ApprovalRequired)
    [req] = out.requests
    assert req.tool == "create_config" and req.args["name"] == "sala_calma"
    assert req.allowed_decisions == ("approve", "reject")  # edit nunca é oferecido
    fake_manager.add_config.assert_not_called()

    final = await agent.aresume("s1", decide_all(out))

    fake_manager.add_config.assert_called_once()
    assert final.startswith("fim: sub ok:")
    # Retomou do nó HITL do subagent: o modelo do subagent não foi rechamado
    # com a HumanMessage (args aprovados == args executados).
    assert router.sub_human_steps == 1


@pytest.mark.asyncio
async def test_parallel_subagent_decisions_matched_by_id(
    monkeypatch, fake_controller, fake_manager
):
    router = HitlRouter(
        [task_call("sala_calma"), task_call("sala_viva")], sub_call=_sub_create_config
    )
    agent = hitl_agent(monkeypatch, fake_controller, fake_manager, router)
    out = await agent.ainvoke("duas cenas", session_id="s1")
    assert {r.args["name"] for r in out.requests} == {"sala_calma", "sala_viva"}

    # Ordem invertida de propósito: o id manda, não a posição.
    decisions = [
        {"id": r.id, "type": "approve" if r.args["name"] == "sala_calma" else "reject"}
        for r in reversed(out.requests)
    ]
    final = await agent.aresume("s1", decisions)

    assert isinstance(final, str)
    fake_manager.add_config.assert_called_once()
    assert fake_manager.add_config.call_args[0][0].name == "sala_calma"
    assert router.sub_human_steps == 2


@pytest.mark.asyncio
async def test_pending_survives_agent_rebuild_with_sqlite(
    monkeypatch, fake_controller, fake_manager, tmp_path
):
    """Checkpointer persistente: outro agente (restart/configure) retoma a thread."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    mirror = FakeMirror()
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "chat.sqlite")) as saver:
        first = hitl_agent(
            monkeypatch, fake_controller, fake_manager, HitlRouter([START_MIRROR]),
            mirror=mirror, checkpointer=saver,
        )
        out = await first.ainvoke("liga", session_id="s1")

        second = hitl_agent(
            monkeypatch, fake_controller, fake_manager, HitlRouter([START_MIRROR]),
            mirror=mirror, checkpointer=saver,
        )
        assert await second.apending("s1") is not None
        final = await second.aresume("s1", decide_all(out))

    assert final.startswith("fim:")
    assert len(mirror.start_calls) == 1
