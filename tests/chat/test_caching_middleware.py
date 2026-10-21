"""Builder único do AnthropicPromptCachingMiddleware (orquestrador + subagents)."""
from __future__ import annotations


def test_prompt_caching_middleware_uses_shared_ttl():
    from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware

    from marvin_hue.chat.middleware.caching import (
        PROMPT_CACHE_TTL,
        prompt_caching_middleware,
    )

    middleware = prompt_caching_middleware()
    assert isinstance(middleware, AnthropicPromptCachingMiddleware)
    assert PROMPT_CACHE_TTL == "5m"
    assert middleware.ttl == PROMPT_CACHE_TTL


def test_orchestrator_and_subagents_use_the_shared_builder(
    monkeypatch, fake_controller, fake_manager, bindable_model_factory
):
    import marvin_hue.chat.agents.react_agent as ra
    from marvin_hue.chat.middleware import caching
    from marvin_hue.chat.subagents import definitions

    sentinel_calls: list[object] = []

    class _Marker:
        pass

    def fake_builder():
        marker = _Marker()
        sentinel_calls.append(marker)
        return marker

    monkeypatch.setattr(caching, "prompt_caching_middleware", fake_builder)
    seen: dict[str, list] = {}

    def fake_create_agent(**kw):
        seen.setdefault("stacks", []).append(kw["middleware"])
        return object()

    monkeypatch.setattr(ra, "create_agent", fake_create_agent, raising=False)
    monkeypatch.setattr(definitions, "create_agent", fake_create_agent)

    class _FakeProvider:
        model = bindable_model_factory()

    monkeypatch.setattr(
        ra.LLMProviderFactory, "create",
        classmethod(lambda cls, **kw: _FakeProvider()),
    )
    ra.HueLightAgent(
        fake_controller, fake_manager, config=ra.AgentConfig(provider="anthropic")
    )

    # 3 subagents + orquestrador, todos com o marcador do builder compartilhado.
    assert len(sentinel_calls) == 4
    assert len(seen["stacks"]) == 4
    for stack in seen["stacks"]:
        assert any(isinstance(m, _Marker) for m in stack)
