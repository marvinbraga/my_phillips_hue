"""
Base LLM Provider - Abstrações base para provedores de LLM.

Implementa o padrão Strategy para permitir diferentes implementações
de provedores de LLM de forma intercambiável.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from langchain_core.language_models.chat_models import BaseChatModel


@dataclass
class LLMConfig:
    """Configuração para instanciar um provedor de LLM.

    Attributes:
        model: Nome do modelo (ex: "gpt-4o", "claude-3-5-sonnet")
        temperature: Temperatura para geração (0.0 a 2.0)
        max_tokens: Número máximo de tokens na resposta
        api_key: Chave de API (opcional, pode vir de env vars)
        base_url: URL base customizada (opcional)
        streaming: Habilitar streaming de respostas
        extra_params: Parâmetros adicionais específicos do provedor
    """
    model: str
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    streaming: bool = True
    extra_params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Converte a configuração para dicionário."""
        result = {
            "model": self.model,
            "temperature": self.temperature,
            "streaming": self.streaming,
        }
        if self.max_tokens:
            result["max_tokens"] = self.max_tokens
        if self.api_key:
            result["api_key"] = self.api_key
        if self.base_url:
            result["base_url"] = self.base_url
        result.update(self.extra_params)
        return result


class BaseLLMProvider(ABC):
    """Classe base abstrata para provedores de LLM (Strategy Pattern).

    Define a interface que todos os provedores de LLM devem implementar.
    Cada provedor concreto (OpenAI, Anthropic, xAI) implementa esta interface.
    """

    def __init__(self, config: LLMConfig):
        """Inicializa o provedor com a configuração fornecida.

        Args:
            config: Configuração do LLM
        """
        self._config = config
        self._model: Optional[BaseChatModel] = None

    @property
    def config(self) -> LLMConfig:
        """Retorna a configuração atual."""
        return self._config

    @property
    def model(self) -> BaseChatModel:
        """Retorna a instância do modelo, criando-a se necessário (Lazy Loading)."""
        if self._model is None:
            self._model = self._create_model()
        return self._model

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Retorna o nome do provedor (ex: 'openai', 'anthropic')."""
        pass

    @property
    @abstractmethod
    def supported_models(self) -> list[str]:
        """Retorna lista de modelos suportados por este provedor."""
        pass

    @abstractmethod
    def _create_model(self) -> BaseChatModel:
        """Cria e retorna uma instância do modelo de chat.

        Returns:
            Instância do modelo de chat configurado
        """
        pass

    def bind_tools(self, tools: list) -> BaseChatModel:
        """Vincula ferramentas ao modelo.

        Args:
            tools: Lista de ferramentas para vincular

        Returns:
            Modelo com ferramentas vinculadas
        """
        return self.model.bind_tools(tools)

    def with_config(self, **kwargs) -> "BaseLLMProvider":
        """Cria uma nova instância com configuração modificada.

        Args:
            **kwargs: Parâmetros de configuração para sobrescrever

        Returns:
            Nova instância do provedor com configuração atualizada
        """
        new_config = LLMConfig(
            model=kwargs.get("model", self._config.model),
            temperature=kwargs.get("temperature", self._config.temperature),
            max_tokens=kwargs.get("max_tokens", self._config.max_tokens),
            api_key=kwargs.get("api_key", self._config.api_key),
            base_url=kwargs.get("base_url", self._config.base_url),
            streaming=kwargs.get("streaming", self._config.streaming),
            extra_params={**self._config.extra_params, **kwargs.get("extra_params", {})},
        )
        return self.__class__(new_config)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(model={self._config.model!r})"
