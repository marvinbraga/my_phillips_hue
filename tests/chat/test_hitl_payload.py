"""Conversão interrupt → payload e validação das decisões (marvin_hue.chat.hitl)."""
from __future__ import annotations

import pytest
from langgraph.types import Interrupt

from marvin_hue.chat.hitl import (
    MAX_REJECT_MESSAGE_CHARS,
    InvalidDecisionError,
    NoPendingApprovalError,
    approval_from_interrupts,
    build_resume_map,
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


def test_payload_flattens_and_orders_by_interrupt_id():
    out = approval_from_interrupts([_intr("b", "create_config"), _intr("a", "x", "y")])
    assert [r.id for r in out.requests] == ["a:0", "a:1", "b:0"]
    # "edit" nunca é oferecido ao cliente.
    assert out.requests[2].allowed_decisions == ("approve", "reject")
    assert out.to_dict()["requests"][0] == {
        "id": "a:0", "tool": "x", "args": {"config_name": "x"},
        "description": "d x", "allowed_decisions": ["approve", "reject"],
    }


@pytest.mark.parametrize("interrupts", [None, [], [Interrupt(value="texto", id="z")]])
def test_no_payload_for_empty_or_foreign_interrupts(interrupts):
    assert approval_from_interrupts(interrupts) is None


def test_resume_map_groups_by_interrupt_in_payload_order():
    ints = [_intr("b", "q"), _intr("a", "x", "y")]
    resume = build_resume_map(
        ints, [{"type": "approve"}, {"type": "reject"}, {"type": "approve"}]
    )
    assert resume == {
        "a": {"decisions": [{"type": "approve"}, {"type": "reject"}]},
        "b": {"decisions": [{"type": "approve"}]},
    }


def test_resume_map_by_id_ignores_position():
    ints = [_intr("a", "x"), _intr("b", "y")]
    resume = build_resume_map(ints, [{"id": "b:0", "type": "reject"}, {"id": "a:0", "type": "approve"}])
    assert resume["a"] == {"decisions": [{"type": "approve"}]}
    assert resume["b"] == {"decisions": [{"type": "reject"}]}


def test_resume_map_rejects_unknown_ids():
    with pytest.raises(InvalidDecisionError):
        build_resume_map([_intr("a", "x")], [{"id": "zz:0", "type": "approve"}])


def test_reject_message_is_trimmed_and_framed():
    resume = build_resume_map(
        [_intr("a", "apply_config")],
        [{"type": "reject", "message": "  " + "x" * 2000}],
    )
    msg = resume["a"]["decisions"][0]["message"]
    assert msg.startswith("O usuário rejeitou `apply_config`; a ferramenta não foi executada.")
    assert msg.endswith("Motivo informado: " + "x" * MAX_REJECT_MESSAGE_CHARS)


def test_blank_reject_message_falls_back_to_default():
    resume = build_resume_map([_intr("a", "x")], [{"type": "reject", "message": "  "}])
    assert resume["a"]["decisions"] == [{"type": "reject"}]


@pytest.mark.parametrize("kind", ["edit", "respond", "bogus", None])
def test_unsupported_decisions_fail_closed(kind):
    with pytest.raises(InvalidDecisionError):
        build_resume_map([_intr("a", "x")], [{"type": kind}])


def test_decision_not_in_tool_policy_fails():
    with pytest.raises(InvalidDecisionError):
        build_resume_map([_intr("a", "x", allowed=("approve",))], [{"type": "reject"}])


def test_nothing_pending():
    with pytest.raises(NoPendingApprovalError):
        build_resume_map([], [{"type": "approve"}])
    with pytest.raises(NoPendingApprovalError):
        build_resume_map([Interrupt(value="texto", id="z")], [{"type": "approve"}])


def test_require_approval_setting_reads_env(monkeypatch):
    from marvin_hue.config import Settings

    monkeypatch.setenv("BRIDGE_IP", "127.0.0.1")
    monkeypatch.delenv("CHAT_REQUIRE_APPROVAL", raising=False)
    assert Settings(_env_file=None).chat_require_approval is False
    monkeypatch.setenv("CHAT_REQUIRE_APPROVAL", "true")
    assert Settings(_env_file=None).chat_require_approval is True


def test_configure_route_threads_require_approval(fastapi_test_client, monkeypatch):
    import marvin_hue.api.routes.chat as chat_routes
    from marvin_hue.api import dependencies

    seen = {}
    monkeypatch.setattr(chat_routes.settings, "chat_require_approval", True)
    monkeypatch.setattr(
        chat_routes, "create_hue_agent", lambda **kw: seen.update(kw) or object()
    )
    monkeypatch.setattr(dependencies, "_chat_agent", dependencies._chat_agent)
    r = fastapi_test_client.post(
        "/api/chat/configure", json={"provider": "openai", "model": "gpt-4o-mini"}
    )
    assert r.status_code == 200
    assert seen["require_approval"] is True
