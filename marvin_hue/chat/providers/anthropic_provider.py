"""
Anthropic Provider - Implementação do provedor para modelos Anthropic (Claude).
"""

import os
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_anthropic import ChatAnthropic

from marvin_hue.chat.providers.base import BaseLLMProvider, LLMConfig
from marvin_hue.chat.providers.registry import register_provider


@register_provider("anthropic")
class AnthropicProvider(BaseLLMProvider):
    """Provedor para modelos Anthropic (Claude).

    Suporta todos os modelos Claude disponíveis na API Anthropic.

    Variáveis de ambiente:
        ANTHROPIC_API_KEY: Chave de API da Anthropic
    """

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def supported_models(self) -> list[str]:
        return [
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307",
        ]

    def _create_model(self) -> BaseChatModel:
        """Cria uma instância do ChatAnthropic."""
        params = {
            "model": self._config.model,
            "temperature": self._config.temperature,
            "streaming": self._config.streaming,
        }

        # API key: usa config ou variável de ambiente
        api_key = self._config.api_key or os.getenv("ANTHROPIC_API_KEY")
        if api_key:
            params["api_key"] = api_key

        # Parâmetros opcionais
        if self._config.max_tokens:
            params["max_tokens"] = self._config.max_tokens

        if self._config.base_url:
            params["base_url"] = self._config.base_url

        # Parâmetros extras (só adiciona se houver valores)
        if self._config.extra_params:
            params.update(self._config.extra_params)

        return ChatAnthropic(**params)
