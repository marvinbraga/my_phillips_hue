"""Cobre _create_model de cada provider mockando a classe Chat subjacente."""
from __future__ import annotations

import pytest


class _FakeChat:
    """Captura os kwargs passados ao construtor Chat* (sem rede)."""
    last_kwargs: dict = {}

    def __init__(self, **kwargs):
        type(self).last_kwargs = kwargs


def test_openai_create_model(monkeypatch):
    import marvin_hue.chat.providers.openai_provider as p
    from marvin_hue.chat.providers import LLMConfig
    monkeypatch.setattr(p, "ChatOpenAI", _FakeChat)
    model = p.OpenAIProvider(LLMConfig(model="gpt-4o-mini", api_key="k", max_tokens=10)).model
    assert isinstance(model, _FakeChat)
    assert _FakeChat.last_kwargs["model"] == "gpt-4o-mini"
    assert _FakeChat.last_kwargs["api_key"] == "k"


def test_anthropic_create_model(monkeypatch):
    import marvin_hue.chat.providers.anthropic_provider as p
    from marvin_hue.chat.providers import LLMConfig
    monkeypatch.setattr(p, "ChatAnthropic", _FakeChat)
    model = p.AnthropicProvider(LLMConfig(model="claude-3-5-sonnet-20241022", api_key="k")).model
    assert isinstance(model, _FakeChat)
    assert _FakeChat.last_kwargs["model"] == "claude-3-5-sonnet-20241022"


@pytest.mark.parametrize(
    "model",
    ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-4-8", "claude-fable-5-1"],
)
def test_anthropic_omits_temperature_on_models_without_sampling(monkeypatch, model):
    import marvin_hue.chat.providers.anthropic_provider as p
    from marvin_hue.chat.providers import LLMConfig
    monkeypatch.setattr(p, "ChatAnthropic", _FakeChat)
    p.AnthropicProvider(LLMConfig(model=model, api_key="k")).model
    assert "temperature" not in _FakeChat.last_kwargs


def test_anthropic_keeps_temperature_on_older_models(monkeypatch):
    import marvin_hue.chat.providers.anthropic_provider as p
    from marvin_hue.chat.providers import LLMConfig
    monkeypatch.setattr(p, "ChatAnthropic", _FakeChat)
    p.AnthropicProvider(LLMConfig(model="claude-3-5-haiku-20241022", api_key="k", temperature=0.3)).model
    assert _FakeChat.last_kwargs["temperature"] == 0.3


def test_xai_create_model_uses_base_url(monkeypatch):
    import marvin_hue.chat.providers.xai_provider as p
    from marvin_hue.chat.providers import LLMConfig
    monkeypatch.setattr(p, "ChatOpenAI", _FakeChat)
    p.XAIProvider(LLMConfig(model="grok-2", api_key="k")).model
    assert _FakeChat.last_kwargs["base_url"] == p.XAIProvider.XAI_BASE_URL


def test_groq_create_model_uses_base_url(monkeypatch):
    import marvin_hue.chat.providers.groq_provider as p
    from marvin_hue.chat.providers import LLMConfig
    monkeypatch.setattr(p, "ChatOpenAI", _FakeChat)
    p.GroqProvider(LLMConfig(model="llama-3.3-70b-versatile", api_key="k")).model
    assert _FakeChat.last_kwargs["base_url"] == p.GroqProvider.GROQ_BASE_URL
