"""
xAI Provider - Implementação do provedor para modelos xAI (Grok).

O xAI usa uma API compatível com OpenAI, então utilizamos ChatOpenAI
com base_url customizada.
"""

import os
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from marvin_hue.chat.providers.base import BaseLLMProvider, LLMConfig
from marvin_hue.chat.providers.registry import register_provider


@register_provider("xai")
class XAIProvider(BaseLLMProvider):
    """Provedor para modelos xAI (Grok).

    Utiliza API compatível com OpenAI através do endpoint xAI.

    Variáveis de ambiente:
        XAI_API_KEY: Chave de API do xAI
    """

    XAI_BASE_URL = "https://api.x.ai/v1"

    @property
    def provider_name(self) -> str:
        return "xai"

    @property
    def supported_models(self) -> list[str]:
        return [
            "grok-beta",
            "grok-2",
            "grok-2-mini",
        ]

    def _create_model(self) -> BaseChatModel:
        """Cria uma instância do ChatOpenAI configurada para xAI."""
        params = {
            "model": self._config.model,
            "temperature": self._config.temperature,
            "streaming": self._config.streaming,
            "base_url": self._config.base_url or self.XAI_BASE_URL,
        }

        # API key: usa config ou variável de ambiente
        api_key = self._config.api_key or os.getenv("XAI_API_KEY")
        if api_key:
            params["api_key"] = api_key

        # Parâmetros opcionais
        if self._config.max_tokens:
            params["max_tokens"] = self._config.max_tokens

        # Parâmetros extras (só adiciona se houver valores)
        if self._config.extra_params:
            params.update(self._config.extra_params)

        return ChatOpenAI(**params)
