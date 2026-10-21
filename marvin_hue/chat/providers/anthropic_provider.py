"""
Anthropic Provider - Implementação do provedor para modelos Anthropic (Claude).
"""

import re

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_anthropic import ChatAnthropic

from marvin_hue.chat.providers.base import BaseLLMProvider
from marvin_hue.chat.providers.registry import register_provider
from marvin_hue.config import settings

# Modelos que rejeitam temperature/top_p/top_k com HTTP 400
# (família Claude 5, Fable/Mythos e Opus 4.7/4.8).
_NO_SAMPLING_MODELS = re.compile(
    r"^claude-(fable|mythos)-|^claude-(opus|sonnet|haiku)-(5|4-7|4-8)(\b|-)"
)


def accepts_sampling_params(model: str) -> bool:
    """Indica se o modelo aceita parâmetros de amostragem (temperature etc.)."""
    return not _NO_SAMPLING_MODELS.match(model or "")


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
            "claude-opus-5-5",
            "claude-sonnet-5-5",
            "claude-haiku-5-5",
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
            "streaming": self._config.streaming,
        }
        if accepts_sampling_params(self._config.model):
            params["temperature"] = self._config.temperature

        # API key: usa config ou settings
        api_key = self._config.api_key or settings.anthropic_api_key
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
