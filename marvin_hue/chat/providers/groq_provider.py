"""
Groq Provider - Implementação do provedor para modelos Groq.

O Groq expõe uma API compatível com OpenAI, então reutilizamos ChatOpenAI
com base_url customizada (zero dependência nova).
"""

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from marvin_hue.chat.providers.base import BaseLLMProvider
from marvin_hue.chat.providers.registry import register_provider
from marvin_hue.config import settings


@register_provider("groq")
class GroqProvider(BaseLLMProvider):
    """Provedor para modelos Groq (API compatível com OpenAI).

    Variáveis de ambiente:
        GROQ_API_KEY: Chave de API do Groq
    """

    GROQ_BASE_URL = "https://api.groq.com/openai/v1"

    @property
    def provider_name(self) -> str:
        return "groq"

    @property
    def supported_models(self) -> list[str]:
        return [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
        ]

    def _create_model(self) -> BaseChatModel:
        """Cria uma instância do ChatOpenAI configurada para Groq."""
        params: dict[str, Any] = {
            "model": self._config.model,
            "temperature": self._config.temperature,
            "streaming": self._config.streaming,
            "base_url": self._config.base_url or self.GROQ_BASE_URL,
        }

        api_key = self._config.api_key or settings.groq_api_key
        if api_key:
            params["api_key"] = api_key

        if self._config.max_tokens:
            params["max_tokens"] = self._config.max_tokens

        if self._config.extra_params:
            params.update(self._config.extra_params)

        return ChatOpenAI(**params)
