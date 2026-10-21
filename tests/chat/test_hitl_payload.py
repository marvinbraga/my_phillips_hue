"""Conversão interrupt → payload e validação das decisões (marvin_hue.chat.hitl)."""
from __future__ import annotations

import dataclasses

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Interrupt

from marvin_hue.chat.hitl import (
    CANCELLED_MESSAGE,
    HITL_INTERRUPT_ON,
    MAX_REJECT_MESSAGE_CHARS,
    ApprovalRequired,
    InvalidDecisionError,
    NoPendingApprovalError,
    approval_from_interrupts,
    build_resume_map,
    cancellation_messages,
    dangling_tool_calls,
)


def _intr(iid: str, *names: str, allowed=("approve", "edit", "reject")) -> Interrupt:
    return Interrupt(
        value={
            "action_requests": [
                {"name": n, "args": {"config_name": n}, "description": f"d {n}"} for n in names
            ],
            "review_configs": [
                {"action_name": n, "allowed_decisions": list(allowed)} for n in names
            ],
        },
        id=iid,
    )


def test_policy_gates_only_persistent_or_takeover_tools():
    assert set(HITL_INTERRUPT_ON) == {
        "create_config", "save_current_config", "create_schedule",
        "set_schedule_enabled", "start_mirror",
    }
    # Cada tool leva uma descrição pt-BR para o humano.
    assert all(cfg["description"] for cfg in HITL_INTERRUPT_ON.values())


def test_payload_flattens_and_orders_by_interrupt_id():
    out = approval_from_interrupts([_intr("b", "create_config"), _intr("a", "x", "y")])
    assert [r.id for r in out.requests] == ["a:0", "a:1", "b:0"]
    # "edit" nunca é oferecido ao cliente.
    assert out.requests[2].allowed_decisions == ("approve", "reject")
    assert out.to_dict()["requests"][0] == {
        "id": "a:0", "tool": "x", "args": {"config_name": "x"},
        "description": "d x", "allowed_decisions": ["approve", "reject"],
    }


def test_type_is_a_class_constant_not_a_field():
    assert ApprovalRequired.type == "approval_required"
    assert [f.name for f in dataclasses.fields(ApprovalRequired)] == ["requests"]


@pytest.mark.parametrize("interrupts", [None, [], [Interrupt(value="texto", id="z")]])
def test_no_payload_for_empty_or_foreign_interrupts(interrupts):
    assert approval_from_interrupts(interrupts) is None


def test_malformed_items_become_undecidable_requests():
    intr = Interrupt(
        value={
            "action_requests": [None, {"name": "x", "args": None}],
            "review_configs": [None, {"allowed_decisions": None}],
        },
        id="m",
    )
    out = approval_from_interrupts([intr])
    assert [(r.id, r.tool, r.args, r.allowed_decisions) for r in out.requests] == [
        ("m:0", "", {}, ()),
        ("m:1", "x", {}, ()),
    ]
    with pytest.raises(InvalidDecisionError, match="não permitida"):
        build_resume_map([intr], [{"id": "m:0", "type": "approve"}, {"id": "m:1", "type": "approve"}])


def test_resume_map_groups_by_interrupt_and_matches_by_id():
    ints = [_intr("b", "q"), _intr("a", "x", "y")]
    resume = build_resume_map(
        ints,
        [
            {"id": "b:0", "type": "approve"},
            {"id": "a:1", "type": "approve"},
            {"id": "a:0", "type": "reject"},
        ],
    )
    assert resume == {
        "a": {"decisions": [{"type": "reject"}, {"type": "approve"}]},
        "b": {"decisions": [{"type": "approve"}]},
    }


@pytest.mark.parametrize(
    ("decisions", "match"),
    [
        ([{"type": "approve"}], "precisa do id"),
        ([{"id": "", "type": "approve"}], "precisa do id"),
        ([{"id": "a:0", "type": "approve"}, {"type": "approve"}], "precisa do id"),
        ([{"id": "a:0", "type": "approve"}, {"id": "a:0", "type": "reject"}], "repetidas"),
        ([{"id": "zz:0", "type": "approve"}], "não batem"),
        ([{"id": "a:0", "type": "approve"}, {"id": "a:9", "type": "approve"}], "não batem"),
    ],
    ids=["missing", "empty", "mixed", "duplicate", "unknown", "extra"],
)
def test_resume_map_requires_exact_ids(decisions, match):
    with pytest.raises(InvalidDecisionError, match=match):
        build_resume_map([_intr("a", "x")], decisions)


def test_stale_decisions_rejected_against_new_interrupt_set():
    old = build_resume_map([_intr("old", "x")], [{"id": "old:0", "type": "approve"}])
    assert old
    with pytest.raises(InvalidDecisionError):
        build_resume_map([_intr("new", "x")], [{"id": "old:0", "type": "approve"}])


def test_reject_message_is_trimmed_and_framed():
    resume = build_resume_map(
        [_intr("a", "create_config")],
        [{"id": "a:0", "type": "reject", "message": "  " + "x" * 2000}],
    )
    msg = resume["a"]["decisions"][0]["message"]
    assert msg.startswith("O usuário rejeitou `create_config`; a ferramenta não foi executada.")
    assert msg.endswith("Motivo informado: " + "x" * MAX_REJECT_MESSAGE_CHARS)


def test_blank_reject_message_falls_back_to_default():
    resume = build_resume_map([_intr("a", "x")], [{"id": "a:0", "type": "reject", "message": " "}])
    assert resume["a"]["decisions"] == [{"type": "reject"}]


@pytest.mark.parametrize("kind", ["edit", "respond", "bogus", None])
def test_unsupported_decisions_fail_closed(kind):
    with pytest.raises(InvalidDecisionError, match="não permitida"):
        build_resume_map([_intr("a", "x")], [{"id": "a:0", "type": kind}])


def test_decision_not_in_tool_policy_fails():
    with pytest.raises(InvalidDecisionError, match="permitidas: approve"):
        build_resume_map(
            [_intr("a", "x", allowed=("approve",))], [{"id": "a:0", "type": "reject"}]
        )


def test_nothing_pending():
    with pytest.raises(NoPendingApprovalError):
        build_resume_map([], [{"id": "a:0", "type": "approve"}])
    with pytest.raises(NoPendingApprovalError):
        build_resume_map([Interrupt(value="texto", id="z")], [{"id": "z:0", "type": "approve"}])


def test_dangling_tool_calls_and_cancellation():
    call = {"name": "start_mirror", "args": {}, "id": "t1"}
    other = {"name": "get_light_status", "args": {}, "id": "t2"}
    msgs = [
        HumanMessage("oi"),
        AIMessage(content="", tool_calls=[call, other]),
        ToolMessage("ok", tool_call_id="t2"),
    ]
    assert [c["id"] for c in dangling_tool_calls(msgs)] == ["t1"]
    assert dangling_tool_calls(msgs + [ToolMessage("x", tool_call_id="t1")]) == []
    assert dangling_tool_calls([HumanMessage("oi"), AIMessage("fim")]) == []
    assert dangling_tool_calls(None) == []
    [cancel] = cancellation_messages([call])
    assert (cancel.content, cancel.tool_call_id, cancel.status) == (CANCELLED_MESSAGE, "t1", "error")


@pytest.mark.parametrize(("raw", "expected"), [(None, False), ("false", False), ("true", True)])
def test_require_approval_setting_reads_env(monkeypatch, raw, expected):
    from marvin_hue.config import Settings

    monkeypatch.setenv("BRIDGE_IP", "127.0.0.1")
    if raw is None:
        monkeypatch.delenv("CHAT_REQUIRE_APPROVAL", raising=False)
    else:
        monkeypatch.setenv("CHAT_REQUIRE_APPROVAL", raw)
    assert Settings(_env_file=None).chat_require_approval is expected
