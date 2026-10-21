"""Bounds do agente: recursion_limit do orquestrador e HITL nos subagents."""
from __future__ import annotations

from tests.chat.fakes import services


def test_config_for_sets_recursion_limit():
    from marvin_hue.chat.agents.react_agent import AGENT_RECURSION_LIMIT, HueLightAgent

    cfg = HueLightAgent._config_for("s1")
    assert cfg["configurable"] == {"thread_id": "s1"}
    assert cfg["recursion_limit"] == AGENT_RECURSION_LIMIT == 25


def _subagent_middleware(monkeypatch, fake_controller, fake_manager, bindable_model_factory, **kw):
    from marvin_hue.chat.subagents import definitions as d

    stacks: dict[str, list[str]] = {}

    def fake_create_agent(**kwargs):
        stacks[kwargs["system_prompt"]] = kwargs["middleware"]
        return object()

    monkeypatch.setattr(d, "create_agent", fake_create_agent)
    d.build_subagents(
        bindable_model_factory(), fake_controller, fake_manager, services=services(), **kw
    )
    return stacks


def test_subagents_have_no_hitl_by_default(
    monkeypatch, fake_controller, fake_manager, bindable_model_factory
):
    stacks = _subagent_middleware(
        monkeypatch, fake_controller, fake_manager, bindable_model_factory
    )
    for mw in stacks.values():
        assert "HumanInTheLoopMiddleware" not in [type(m).__name__ for m in mw]


def test_subagents_get_hitl_for_their_mutating_tools(
    monkeypatch, fake_controller, fake_manager, bindable_model_factory
):
    from marvin_hue.chat.hitl import HITL_INTERRUPT_ON
    from marvin_hue.chat.subagents import definitions as d

    stacks = _subagent_middleware(
        monkeypatch, fake_controller, fake_manager, bindable_model_factory,
        require_approval=True,
    )
    by_prompt = {
        d.SCENE_DESIGNER_PROMPT: d.SCENE_DESIGNER_TOOLS,
        d.CONFIG_LIBRARIAN_PROMPT: d.CONFIG_LIBRARIAN_TOOLS,
        d.GENERAL_PROMPT: d.GENERAL_TOOLS,
    }
    for prompt, mw in stacks.items():
        hitl = [m for m in mw if type(m).__name__ == "HumanInTheLoopMiddleware"]
        expected = {n for n in by_prompt[prompt] if n in HITL_INTERRUPT_ON}
        if expected:
            assert hitl and set(hitl[0].interrupt_on) == expected, prompt
        else:
            assert not hitl, prompt


def test_orchestrator_passes_require_approval_to_subagents(
    monkeypatch, fake_controller, fake_manager, bindable_model_factory
):
    import marvin_hue.chat.agents.react_agent as ra
    from marvin_hue.chat.subagents import definitions as d

    seen = {}
    real = d.build_subagents

    def spy(*a, **k):
        seen.update(k)
        return real(*a, **k)

    monkeypatch.setattr(d, "build_subagents", spy)
    monkeypatch.setattr(ra.HueLightAgent, "_create_llm", lambda self: bindable_model_factory())
    ra.HueLightAgent(
        fake_controller, fake_manager, config=ra.AgentConfig(require_approval=True),
        services=services(),
    )
    assert seen["require_approval"] is True
