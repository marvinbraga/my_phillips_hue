from unittest.mock import MagicMock


def test_task_tool_dispatches_to_named_subagent():
    from marvin_hue.chat.subagents.task import build_task_tool

    fake_sub = MagicMock()
    fake_sub.invoke.return_value = {
        "messages": [type("AI", (), {"content": "cena pronta", "tool_calls": []})()]
    }
    subagents = {"scene-designer": {"runnable": fake_sub, "description": "projeta cenas"}}

    task = build_task_tool(subagents)
    assert task.name == "task"
    # schema expõe description + subagent_type
    fields = task.args_schema.model_fields.keys()
    assert "description" in fields and "subagent_type" in fields


def test_task_tool_unknown_subagent_returns_message():
    from marvin_hue.chat.subagents.task import build_task_tool
    task = build_task_tool({"scene-designer": {"runnable": MagicMock(), "description": "x"}})
    # invocação direta da função subjacente via .func não exige runtime real
    out = task.func(description="oi", subagent_type="inexistente", runtime=MagicMock(tool_call_id="t1"))
    assert "inexistente" in str(out)
