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
    """Cada lista de tools por subagent resolve para nomes REAIS de build_all_tools.

    Guarda contra typo silenciosamente descartado por _subset (if n in by).
    """
    from marvin_hue.chat.subagents import definitions as d
    from marvin_hue.chat.tools import build_all_tools

    real = {t.name for t in build_all_tools(fake_controller, fake_manager)}
    for names in (d.SCENE_DESIGNER_TOOLS, d.CONFIG_LIBRARIAN_TOOLS, d.GENERAL_TOOLS):
        missing = [n for n in names if n not in real]
        assert not missing, f"nomes inválidos (seriam descartados): {missing}"
        # _subset retorna exatamente o subconjunto pedido, sem perdas.
        got = {t.name for t in d._subset(build_all_tools(fake_controller, fake_manager), names)}
        assert got == set(names)


def _capture_subagent_middleware(monkeypatch, fake_controller, fake_manager, **kwargs):
    from marvin_hue.chat.subagents import definitions as d

    stacks: dict[str, list[str]] = {}

    def fake_create_agent(**kw):
        stacks[kw["system_prompt"]] = [type(m).__name__ for m in kw["middleware"]]
        return object()

    monkeypatch.setattr(d, "create_agent", fake_create_agent)
    d.build_subagents(object(), fake_controller, fake_manager, **kwargs)
    assert set(stacks) == {
        d.SCENE_DESIGNER_PROMPT,
        d.CONFIG_LIBRARIAN_PROMPT,
        d.GENERAL_PROMPT,
    }
    return stacks


def test_subagents_add_prompt_caching_when_enabled(
    monkeypatch, fake_controller, fake_manager
):
    stacks = _capture_subagent_middleware(
        monkeypatch, fake_controller, fake_manager, prompt_caching=True
    )
    for names in stacks.values():
        assert names.count("AnthropicPromptCachingMiddleware") == 1
        # Mesma ordem do orquestrador: depois da pilha de segurança.
        assert names.index("AnthropicPromptCachingMiddleware") > names.index(
            "EyeSafetyMiddleware"
        )


def test_subagents_without_prompt_caching_by_default(
    monkeypatch, fake_controller, fake_manager
):
    stacks = _capture_subagent_middleware(monkeypatch, fake_controller, fake_manager)
    for names in stacks.values():
        assert "AnthropicPromptCachingMiddleware" not in names


def test_prompt_caching_comes_before_hitl(monkeypatch, fake_controller, fake_manager):
    from marvin_hue.chat.subagents import definitions as d

    stacks = _capture_subagent_middleware(
        monkeypatch,
        fake_controller,
        fake_manager,
        prompt_caching=True,
        require_approval=True,
    )
    for names in stacks.values():
        if "HumanInTheLoopMiddleware" in names:
            assert names.index("AnthropicPromptCachingMiddleware") < names.index(
                "HumanInTheLoopMiddleware"
            )
    assert "HumanInTheLoopMiddleware" in stacks[d.SCENE_DESIGNER_PROMPT]
