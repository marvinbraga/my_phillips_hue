"""
OpenAI Provider - Implementação do provedor para modelos OpenAI.
"""

import os
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from marvin_hue.chat.providers.base import BaseLLMProvider, LLMConfig
from marvin_hue.chat.providers.registry import register_provider


@register_provider("openai")
class OpenAIProvider(BaseLLMProvider):
    """Provedor para modelos OpenAI (GPT-4, GPT-4o, o1, etc.).

    Suporta todos os modelos disponíveis na API OpenAI.

    Variáveis de ambiente:
        OPENAI_API_KEY: Chave de API da OpenAI
    """

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def supported_models(self) -> list[str]:
        return [
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4-turbo",
            "gpt-4",
            "gpt-3.5-turbo",
            "o1",
            "o1-mini",
            "o1-preview",
        ]

    def _create_model(self) -> BaseChatModel:
        """Cria uma instância do ChatOpenAI."""
        params = {
            "model": self._config.model,
            "temperature": self._config.temperature,
            "streaming": self._config.streaming,
        }

        # API key: usa config ou variável de ambiente
        api_key = self._config.api_key or os.getenv("OPENAI_API_KEY")
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

        return ChatOpenAI(**params)
