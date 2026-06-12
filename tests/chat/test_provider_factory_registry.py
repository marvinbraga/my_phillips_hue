"""Cobre a API pública de LLPProviderFactory / Registry / Builder (sem rede)."""
from __future__ import annotations

import pytest

from marvin_hue.chat.providers import (
    LLMProviderFactory,
    LLMProviderRegistry,
    LLMProviderBuilder,
)
import marvin_hue.chat.providers  # noqa: F401  (dispara o registro dos providers)


def test_registry_lists_known_providers():
    providers = set(LLMProviderRegistry.list_providers())
    assert {"openai", "anthropic", "xai", "groq"} <= providers
    assert LLMProviderRegistry.is_registered("openai")
    assert LLMProviderRegistry.get("openai") is not None
    assert LLMProviderRegistry.get("inexistente") is None


def test_registry_get_or_raise_unknown():
    with pytest.raises(Exception):
        LLMProviderRegistry.get_or_raise("inexistente")


def test_factory_create_explicit_provider():
    provider = LLMProviderFactory.create(provider_name="openai", model="gpt-4o-mini")
    assert provider.provider_name == "openai"


def test_factory_detects_provider_from_model_prefix():
    # from_string usa _detect_provider pelos prefixes registrados.
    provider = LLMProviderFactory.from_string("gpt-4o-mini")
    assert provider.provider_name == "openai"


def test_factory_list_available_and_info():
    avail = LLMProviderFactory.list_available()
    assert "openai" in avail and "supported_models" in avail["openai"]
    info = LLMProviderRegistry.get_provider_info()
    assert "groq" in info


def test_provider_builder_build():
    provider = (
        LLMProviderBuilder()
        .provider("openai")
        .model("gpt-4o-mini")
        .temperature(0.3)
        .max_tokens(50)
        .streaming(False)
        .extra(foo=1)
        .build()
    )
    assert provider.provider_name == "openai"
