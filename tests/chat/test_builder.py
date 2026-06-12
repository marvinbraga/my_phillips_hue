"""Cobre HueLightAgentBuilder (API fluente) e as guardas de build()."""
from __future__ import annotations

import pytest


def test_builder_full_chain(monkeypatch, fake_controller, fake_manager, bindable_model_factory):
    import marvin_hue.chat.agents.react_agent as ra

    class _FakeProvider:
        model = bindable_model_factory()

    monkeypatch.setattr(
        ra.LLMProviderFactory, "create",
        classmethod(lambda cls, **kw: _FakeProvider()),
    )
    monkeypatch.setattr(ra, "create_agent", lambda **kw: object())

    agent = (
        ra.HueLightAgentBuilder()
        .with_controller(fake_controller)
        .with_manager(fake_manager)
        .with_provider("openai")
        .with_model("gpt-4o-mini")
        .with_temperature(0.5)
        .with_max_tokens(100)
        .with_streaming(False)
        .with_system_prompt("prompt custom")
        .with_extra_params(foo=1)
        .build()
    )
    assert isinstance(agent, ra.HueLightAgent)
    assert agent._config.provider == "openai"
    assert agent._config.temperature == 0.5
    assert agent._config.system_prompt == "prompt custom"


def test_builder_requires_controller_and_manager():
    import marvin_hue.chat.agents.react_agent as ra

    with pytest.raises(ValueError):
        ra.HueLightAgentBuilder().build()

    with pytest.raises(ValueError):
        ra.HueLightAgentBuilder().with_controller(object()).build()
