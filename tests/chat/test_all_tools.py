"""Agregador build_all_tools, subagents (P16), HITL (P9), prompt (P15) e grafo."""
from __future__ import annotations

from tests.chat.fakes import FakeHistory, services

NEW_TOOLS = {
    "search_configs",
    "describe_config",
    "create_config",
    "undo_last_scene",
    "list_groups",
    "apply_config_to_group",
    "list_schedules",
    "create_schedule",
    "set_schedule_enabled",
    "get_mirror_status",
    "start_mirror",
    "stop_mirror",
    "set_color_temperature",
    "get_system_health",
    "list_favorites",
    "add_favorite",
    "remove_favorite",
}
LIGHT_TOOLS = {
    "list_lights",
    "get_light_status",
    "set_light_color",
    "apply_config",
    "list_configs",
    "turn_off_lights",
    "turn_on_lights",
    "set_brightness",
    "save_current_config",
    "get_light_locations",
    "get_rooms",
    "list_lights_by_room",
    "set_room_power",
    "set_room_brightness",
}
MUTATING_HITL = {
    "apply_config",
    "save_current_config",
    "create_config",
    "apply_config_to_group",
    "create_schedule",
    "set_schedule_enabled",
    "start_mirror",
    "stop_mirror",
    "undo_last_scene",
}
# Tools cujo trabalho real depende de serviço async do app (coroutine=).
ASYNC_SERVICE_TOOLS = {
    "undo_last_scene",
    "list_groups",
    "apply_config_to_group",
    "list_schedules",
    "create_schedule",
    "set_schedule_enabled",
    "start_mirror",
    "stop_mirror",
    "get_system_health",
    "list_favorites",
    "add_favorite",
    "remove_favorite",
    "turn_off_lights",
}


def _all(controller, manager, svc=None):
    from marvin_hue.chat.tools import build_all_tools

    return build_all_tools(controller, manager, services=svc or services())


def test_build_all_tools_exposes_every_name_once(fake_controller, fake_manager):
    names = [t.name for t in _all(fake_controller, fake_manager)]
    assert len(names) == len(set(names)), "nomes duplicados"
    assert set(names) == LIGHT_TOOLS | NEW_TOOLS


def test_service_tools_have_async_path(fake_controller, fake_manager):
    by = {t.name: t for t in _all(fake_controller, fake_manager)}
    for name in ASYNC_SERVICE_TOOLS:
        assert by[name].coroutine is not None, name
        assert by[name].func is not None, name


def test_new_tool_descriptions_are_short(fake_controller, fake_manager):
    for t in _all(fake_controller, fake_manager):
        if t.name in NEW_TOOLS:
            assert len(t.description) <= 160, (t.name, t.description)


def test_subagent_subsets_include_plan_tools():
    from marvin_hue.chat.subagents import definitions as d

    assert {
        "search_configs", "describe_config", "create_config",
        "list_favorites", "add_favorite", "remove_favorite",
    } <= set(d.CONFIG_LIBRARIAN_TOOLS)
    assert {"set_color_temperature", "describe_config", "create_config"} <= set(
        d.SCENE_DESIGNER_TOOLS
    )
    assert {"get_system_health", "get_mirror_status", "list_groups", "list_schedules"} <= set(
        d.GENERAL_TOOLS
    )


def test_hitl_interrupt_on_covers_mutating_tools(fake_controller, fake_manager):
    from marvin_hue.chat.agents.react_agent import HITL_INTERRUPT_ON

    assert set(HITL_INTERRUPT_ON) == MUTATING_HITL
    assert HITL_INTERRUPT_ON["create_config"]["allowed_decisions"] == [
        "approve", "edit", "reject",
    ]
    real = {t.name for t in _all(fake_controller, fake_manager)}
    assert set(HITL_INTERRUPT_ON) <= real


def test_hitl_middleware_uses_constant(monkeypatch, fake_controller, fake_manager, bindable_model_factory):
    import marvin_hue.chat.agents.react_agent as ra

    seen = {}
    monkeypatch.setattr(ra, "create_agent", lambda **kw: seen.update(kw) or object())

    class _FakeProvider:
        model = bindable_model_factory()

    monkeypatch.setattr(
        ra.LLMProviderFactory, "create", classmethod(lambda cls, **kw: _FakeProvider())
    )
    ra.HueLightAgent(
        fake_controller, fake_manager, config=ra.AgentConfig(require_approval=True),
        services=services(),
    )
    hitl = next(
        m for m in seen["middleware"] if type(m).__name__ == "HumanInTheLoopMiddleware"
    )
    assert set(hitl.interrupt_on) == MUTATING_HITL


def test_system_prompt_mentions_new_capabilities():
    from marvin_hue.chat.agents.react_agent import SYSTEM_PROMPT

    for word in ("create_config", "save_current_config", "undo_last_scene", "grupo",
                 "agendamento", "espelhamento", "saúde", "temperatura"):
        assert word in SYSTEM_PROMPT.lower() or word in SYSTEM_PROMPT, word


def test_agent_threads_services_to_orchestrator_and_subagents(
    fake_controller, fake_manager, monkeypatch, bindable_model_factory
):
    from marvin_hue.chat.agents import react_agent as ra
    from marvin_hue.chat.subagents import definitions as d

    seen: list[object] = []
    real = ra.build_all_tools

    def spy(*a, **k):
        seen.append(k.get("services"))
        return real(*a, **k)

    monkeypatch.setattr(ra, "build_all_tools", spy)
    monkeypatch.setattr(d, "build_all_tools", spy)
    monkeypatch.setattr(ra.HueLightAgent, "_create_llm", lambda self: bindable_model_factory())
    svc = services()
    ra.create_hue_agent(fake_controller, fake_manager, services=svc)
    assert len(seen) == 2 and all(s is svc for s in seen)


def test_builder_with_services_threads_container(
    fake_controller, fake_manager, monkeypatch, bindable_model_factory
):
    from marvin_hue.chat.agents import react_agent as ra

    monkeypatch.setattr(ra.HueLightAgent, "_create_llm", lambda self: bindable_model_factory())
    svc = services()
    agent = (
        ra.HueLightAgentBuilder()
        .with_controller(fake_controller)
        .with_manager(fake_manager)
        .with_services(svc)
        .build()
    )
    assert agent._services is svc


def test_legacy_favorites_provider_keyword_removed():
    import inspect

    from marvin_hue.chat.agents import react_agent as ra

    assert "favorites_provider" not in inspect.signature(ra.create_hue_agent).parameters
    assert "favorites_provider" not in inspect.signature(ra.HueLightAgent).parameters
    assert not hasattr(ra.HueLightAgentBuilder, "with_favorites_provider")


async def test_undo_through_compiled_graph_uses_async_path(
    fake_controller, fake_manager, monkeypatch
):
    """Tool call do modelo atravessa o grafo REAL via ainvoke e usa o coroutine."""
    import marvin_hue.chat.agents.react_agent as ra
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage, ToolMessage

    class _ToolCallingFake(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    responses = [
        AIMessage(
            content="",
            tool_calls=[{"name": "undo_last_scene", "args": {}, "id": "tc-undo"}],
        ),
        AIMessage(content="desfeito"),
    ]

    class _FakeProvider:
        model = _ToolCallingFake(responses=responses)

    monkeypatch.setattr(
        ra.LLMProviderFactory, "create", classmethod(lambda cls, **kw: _FakeProvider())
    )
    history = FakeHistory()
    agent = ra.create_hue_agent(
        controller=fake_controller, manager=fake_manager, services=services(history=history)
    )

    await agent.ainvoke("desfaz a última cena", session_id="undo")

    assert history.restore_calls == 1
    state = await agent._agent.aget_state(agent._config_for("undo"))
    tool_msgs = [m for m in state.values["messages"] if isinstance(m, ToolMessage)]
    assert tool_msgs and "restaurada" in str(tool_msgs[-1].content)
