def test_build_subagents_three_named(fake_controller, fake_manager):
    from marvin_hue.chat.subagents.definitions import build_subagents
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage

    # Fake REAL que aceita bind_tools (create_agent vincula as tools ao model).
    class _BindableFake(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    model = _BindableFake(responses=[AIMessage(content="ok")])
    subs = build_subagents(model=model, controller=fake_controller, manager=fake_manager)
    assert set(subs) == {"scene-designer", "config-librarian", "general-purpose"}
    for s in subs.values():
        assert "runnable" in s and "description" in s
