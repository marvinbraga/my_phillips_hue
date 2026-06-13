from unittest.mock import MagicMock

import pytest

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command


def _sub_result(text):
    """Resultado de subagent com uma AIMessage REAL (passa pelo isinstance gate)."""
    return {"messages": [HumanMessage(content="in"), AIMessage(content=text)]}


def test_task_tool_schema_exposes_fields():
    from marvin_hue.chat.subagents.task import build_task_tool

    task = build_task_tool({"scene-designer": {"runnable": MagicMock(), "description": "x"}})
    assert task.name == "task"
    fields = task.args_schema.model_fields.keys()
    assert "description" in fields and "subagent_type" in fields


def test_task_tool_success_returns_tool_message_with_ai_text():
    from marvin_hue.chat.subagents.task import build_task_tool

    fake_sub = MagicMock()
    fake_sub.invoke.return_value = _sub_result("cena pronta")
    task = build_task_tool({"scene-designer": {"runnable": fake_sub, "description": "projeta"}})

    out = task.func(
        description="faça uma cena", subagent_type="scene-designer",
        runtime=MagicMock(tool_call_id="tc-1"),
    )
    assert isinstance(out, Command)
    msg = out.update["messages"][0]
    assert isinstance(msg, ToolMessage)
    assert msg.content == "cena pronta"
    assert msg.tool_call_id == "tc-1"
    # subagent recebeu APENAS a description (contexto isolado) + um config (recursion_limit).
    args, kwargs = fake_sub.invoke.call_args
    assert args[0]["messages"][0].content == "faça uma cena"
    assert kwargs["config"]["recursion_limit"] >= 1


@pytest.mark.asyncio
async def test_task_tool_async_success():
    from marvin_hue.chat.subagents.task import build_task_tool

    fake_sub = MagicMock()

    async def _ainvoke(payload, config=None):
        return _sub_result("cena async")

    fake_sub.ainvoke = _ainvoke
    task = build_task_tool({"scene-designer": {"runnable": fake_sub, "description": "x"}})

    out = await task.coroutine(
        description="oi", subagent_type="scene-designer",
        runtime=MagicMock(tool_call_id="tc-2"),
    )
    assert isinstance(out, Command)
    assert out.update["messages"][0].content == "cena async"


def test_task_tool_unknown_subagent_returns_message():
    from marvin_hue.chat.subagents.task import build_task_tool
    task = build_task_tool({"scene-designer": {"runnable": MagicMock(), "description": "x"}})
    out = task.func(description="oi", subagent_type="inexistente", runtime=MagicMock(tool_call_id="t1"))
    assert "inexistente" in str(out)


def test_task_tool_requires_tool_call_id():
    from marvin_hue.chat.subagents.task import build_task_tool
    fake_sub = MagicMock()
    fake_sub.invoke.return_value = _sub_result("x")
    task = build_task_tool({"scene-designer": {"runnable": fake_sub, "description": "x"}})
    with pytest.raises(ValueError):
        task.func(description="oi", subagent_type="scene-designer", runtime=MagicMock(tool_call_id=None))


def test_last_ai_text_fallback_when_no_ai_message():
    from marvin_hue.chat.subagents.task import build_task_tool
    fake_sub = MagicMock()
    fake_sub.invoke.return_value = {"messages": [HumanMessage(content="só humano")]}
    task = build_task_tool({"scene-designer": {"runnable": fake_sub, "description": "x"}})
    out = task.func(description="oi", subagent_type="scene-designer", runtime=MagicMock(tool_call_id="t1"))
    assert out.update["messages"][0].content == "Tarefa concluída."


def test_task_tool_runtime_is_injected_not_in_model_schema():
    """ToolRuntime deve ser ARG INJETADO: fora do schema do modelo, mas detectado
    pelo ToolNode (regressão do 'atask() missing runtime')."""
    from marvin_hue.chat.subagents.task import build_task_tool
    from langgraph.prebuilt.tool_node import _get_all_injected_args

    task = build_task_tool({"general-purpose": {"runnable": MagicMock(), "description": "g"}})
    assert "runtime" not in task.args  # não exposto ao modelo
    assert _get_all_injected_args(task).runtime == "runtime"  # injetável pelo ToolNode


@pytest.mark.asyncio
async def test_task_delegation_through_real_agent_injects_runtime():
    """E2E: um tool_call `task` atravessa um create_agent REAL e o runtime é
    injetado (sem 'missing positional argument runtime'). Regressão do bug live."""
    from langchain.agents import create_agent
    from langgraph.checkpoint.memory import InMemorySaver
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from marvin_hue.chat.subagents.task import build_task_tool

    class _Sub:
        def invoke(self, payload, config=None):
            return {"messages": [AIMessage(content="subagent respondeu")]}
        async def ainvoke(self, payload, config=None):
            return {"messages": [AIMessage(content="subagent respondeu")]}

    task_tool = build_task_tool({"general-purpose": {"runnable": _Sub(), "description": "geral"}})

    class _Bindable(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    model = _Bindable(responses=[
        AIMessage(content="", tool_calls=[{
            "name": "task",
            "args": {"description": "responda algo", "subagent_type": "general-purpose"},
            "id": "tc-1",
        }]),
        AIMessage(content="feito"),
    ])
    agent = create_agent(
        model=model, tools=[task_tool], system_prompt="s", checkpointer=InMemorySaver(),
    )
    out = await agent.ainvoke(
        {"messages": [("user", "delegue")]},
        config={"configurable": {"thread_id": "t"}},
    )
    blob = " ".join(str(m.content) for m in out["messages"])
    assert "subagent respondeu" in blob  # o resultado do subagent voltou via ToolMessage
