"""
LLM Providers Module

Implementa o padrão Registry + Factory + Strategy para gerenciar
diferentes provedores de LLM de forma extensível e desacoplada.
"""

from marvin_hue.chat.providers.base import BaseLLMProvider, LLMConfig
from marvin_hue.chat.providers.registry import LLMProviderRegistry
from marvin_hue.chat.providers.factory import LLMProviderFactory, LLMProviderBuilder
from marvin_hue.chat.providers.openai_provider import OpenAIProvider
from marvin_hue.chat.providers.anthropic_provider import AnthropicProvider
from marvin_hue.chat.providers.xai_provider import XAIProvider

__all__ = [
    "BaseLLMProvider",
    "LLMConfig",
    "LLMProviderRegistry",
    "LLMProviderFactory",
    "LLMProviderBuilder",
    "OpenAIProvider",
    "AnthropicProvider",
    "XAIProvider",
]
