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


def test_subagent_tool_subsets_have_no_typo(fake_controller, fake_manager):
    """Cada lista de tools por subagent resolve para nomes REAIS de build_light_tools.

    Guarda contra typo silenciosamente descartado por _subset (if n in by).
    """
    from marvin_hue.chat.subagents import definitions as d
    from marvin_hue.chat.tools.light_tools import build_light_tools

    real = {t.name for t in build_light_tools(fake_controller, fake_manager)}
    for names in (d.SCENE_DESIGNER_TOOLS, d.CONFIG_LIBRARIAN_TOOLS, d.GENERAL_TOOLS):
        missing = [n for n in names if n not in real]
        assert not missing, f"nomes inválidos (seriam descartados): {missing}"
        # _subset retorna exatamente o subconjunto pedido, sem perdas.
        got = {t.name for t in d._subset(build_light_tools(fake_controller, fake_manager), names)}
        assert got == set(names)
