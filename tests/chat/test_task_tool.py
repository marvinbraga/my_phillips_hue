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
