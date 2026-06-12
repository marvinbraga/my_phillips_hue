"""O orquestrador deve ser montado com create_agent + pilha de middleware."""
from __future__ import annotations


def test_orchestrator_uses_create_agent_with_middleware(
    monkeypatch, fake_controller, fake_manager, bindable_model_factory
):
    import marvin_hue.chat.agents.react_agent as ra

    seen = {}

    def fake_create_agent(**kw):
        seen.update(kw)
        return object()

    # Mocka APENAS o create_agent do orquestrador; build_subagents usa o
    # create_agent real (de definitions) com o fake bindable.
    monkeypatch.setattr(ra, "create_agent", fake_create_agent, raising=False)

    class _FakeProvider:
        model = bindable_model_factory()

    monkeypatch.setattr(
        ra.LLMProviderFactory, "create",
        classmethod(lambda cls, **kw: _FakeProvider()),
    )

    ra.HueLightAgent(fake_controller, fake_manager)

    assert "middleware" in seen and len(seen["middleware"]) >= 4
    assert "tools" in seen
    tool_names = {t.name for t in seen["tools"]}
    assert {"set_light_color", "set_brightness", "turn_off_lights", "apply_config", "task"} <= tool_names
    assert len(seen["tools"]) >= 11  # sanity (10 light tools + task)
    assert "checkpointer" in seen
    names = [type(m).__name__ for m in seen["middleware"]]
    assert "EyeSafetyMiddleware" in names
    assert "HueContextMiddleware" in names
    assert "TodoListMiddleware" in names
    assert "SummarizationMiddleware" in names
    # openai (default): SEM PromptCaching da Anthropic.
    assert "AnthropicPromptCachingMiddleware" not in names


def test_anthropic_provider_adds_prompt_caching(
    monkeypatch, fake_controller, fake_manager, bindable_model_factory
):
    """Com provider=anthropic, a pilha inclui AnthropicPromptCachingMiddleware."""
    import marvin_hue.chat.agents.react_agent as ra

    seen = {}

    def fake_create_agent(**kw):
        seen.update(kw)
        return object()

    monkeypatch.setattr(ra, "create_agent", fake_create_agent, raising=False)

    class _FakeProvider:
        model = bindable_model_factory()

    monkeypatch.setattr(
        ra.LLMProviderFactory, "create",
        classmethod(lambda cls, **kw: _FakeProvider()),
    )

    ra.HueLightAgent(
        fake_controller, fake_manager, config=ra.AgentConfig(provider="anthropic")
    )

    names = [type(m).__name__ for m in seen["middleware"]]
    assert "AnthropicPromptCachingMiddleware" in names
