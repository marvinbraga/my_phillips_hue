"""GroqProvider deve estar registrado (fecha o gap config.chat_provider='groq')."""
from __future__ import annotations


def test_groq_registered():
    from marvin_hue.chat.providers import LLMProviderRegistry
    import marvin_hue.chat.providers  # noqa: F401  (dispara registro)

    assert LLMProviderRegistry.is_registered("groq")


def test_groq_supported_models():
    from marvin_hue.chat.providers import GroqProvider, LLMConfig

    provider = GroqProvider(LLMConfig(model="llama-3.3-70b-versatile"))
    assert provider.provider_name == "groq"
    assert "llama-3.3-70b-versatile" in provider.supported_models
