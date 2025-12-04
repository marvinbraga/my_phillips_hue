"""
LLM Provider Factory - Padrão Factory Method para criação de provedores.

O Factory encapsula a lógica de criação de provedores, utilizando o Registry
para descobrir e instanciar o provedor correto baseado no nome.
"""

from typing import Optional
from marvin_hue.chat.providers.base import BaseLLMProvider, LLMConfig
from marvin_hue.chat.providers.registry import LLMProviderRegistry


class LLMProviderFactory:
    """Factory para criação de provedores de LLM (Factory Method Pattern).

    Encapsula a lógica de criação de provedores, permitindo criar instâncias
    de forma simples e consistente.

    Uso:
        # Criar provedor com configuração padrão
        provider = LLMProviderFactory.create("openai", model="gpt-4o")

        # Criar provedor com configuração completa
        config = LLMConfig(model="claude-3-5-sonnet", temperature=0.5)
        provider = LLMProviderFactory.create_from_config("anthropic", config)

        # Criar provedor a partir de string no formato "provider:model"
        provider = LLMProviderFactory.from_string("openai:gpt-4o")
    """

    # Mapeamento de prefixos de modelo para provedores
    _model_prefixes: dict[str, str] = {
        "gpt-": "openai",
        "o1-": "openai",
        "claude-": "anthropic",
        "grok-": "xai",
    }

    @classmethod
    def create(
        cls,
        provider_name: str,
        model: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        api_key: Optional[str] = None,
        streaming: bool = True,
        **extra_params
    ) -> BaseLLMProvider:
        """Cria uma instância de provedor com os parâmetros fornecidos.

        Args:
            provider_name: Nome do provedor ("openai", "anthropic", "xai")
            model: Nome do modelo
            temperature: Temperatura para geração
            max_tokens: Número máximo de tokens
            api_key: Chave de API (opcional)
            streaming: Habilitar streaming
            **extra_params: Parâmetros adicionais

        Returns:
            Instância do provedor configurado

        Raises:
            KeyError: Se o provedor não estiver registrado
        """
        config = LLMConfig(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=api_key,
            streaming=streaming,
            extra_params=extra_params,
        )
        return cls.create_from_config(provider_name, config)

    @classmethod
    def create_from_config(
        cls,
        provider_name: str,
        config: LLMConfig
    ) -> BaseLLMProvider:
        """Cria uma instância de provedor a partir de um objeto LLMConfig.

        Args:
            provider_name: Nome do provedor
            config: Objeto de configuração

        Returns:
            Instância do provedor configurado

        Raises:
            KeyError: Se o provedor não estiver registrado
        """
        provider_class = LLMProviderRegistry.get_or_raise(provider_name)
        return provider_class(config)

    @classmethod
    def from_string(
        cls,
        model_string: str,
        temperature: float = 0.7,
        **extra_params
    ) -> BaseLLMProvider:
        """Cria um provedor a partir de uma string no formato "provider:model".

        Também suporta detecção automática do provedor baseado no nome do modelo.

        Args:
            model_string: String no formato "provider:model" ou apenas "model"
            temperature: Temperatura para geração
            **extra_params: Parâmetros adicionais

        Returns:
            Instância do provedor configurado

        Raises:
            ValueError: Se o formato for inválido ou provedor não detectado
            KeyError: Se o provedor não estiver registrado

        Exemplos:
            from_string("openai:gpt-4o")
            from_string("anthropic:claude-3-5-sonnet")
            from_string("gpt-4o")  # Auto-detecta OpenAI
        """
        if ":" in model_string:
            provider_name, model = model_string.split(":", 1)
        else:
            # Tenta detectar o provedor pelo prefixo do modelo
            provider_name = cls._detect_provider(model_string)
            model = model_string

        return cls.create(
            provider_name=provider_name,
            model=model,
            temperature=temperature,
            **extra_params
        )

    @classmethod
    def _detect_provider(cls, model: str) -> str:
        """Detecta o provedor baseado no nome do modelo.

        Args:
            model: Nome do modelo

        Returns:
            Nome do provedor detectado

        Raises:
            ValueError: Se não conseguir detectar o provedor
        """
        model_lower = model.lower()
        for prefix, provider in cls._model_prefixes.items():
            if model_lower.startswith(prefix):
                return provider

        available = ", ".join(LLMProviderRegistry.list_providers())
        raise ValueError(
            f"Could not auto-detect provider for model '{model}'. "
            f"Please specify provider explicitly. Available: {available}"
        )

    @classmethod
    def register_model_prefix(cls, prefix: str, provider: str) -> None:
        """Registra um prefixo de modelo para detecção automática.

        Args:
            prefix: Prefixo do modelo (ex: "llama-")
            provider: Nome do provedor associado
        """
        cls._model_prefixes[prefix.lower()] = provider.lower()

    @classmethod
    def list_available(cls) -> dict[str, list[str]]:
        """Lista provedores disponíveis e seus modelos suportados.

        Returns:
            Dicionário com provedores e modelos
        """
        return LLMProviderRegistry.get_provider_info()


class LLMProviderBuilder:
    """Builder para construção fluente de provedores (Builder Pattern).

    Permite construir provedores de forma mais legível com encadeamento de métodos.

    Uso:
        provider = (
            LLMProviderBuilder()
            .provider("openai")
            .model("gpt-4o")
            .temperature(0.5)
            .streaming(True)
            .build()
        )
    """

    def __init__(self):
        self._provider_name: Optional[str] = None
        self._model: Optional[str] = None
        self._temperature: float = 0.7
        self._max_tokens: Optional[int] = None
        self._api_key: Optional[str] = None
        self._base_url: Optional[str] = None
        self._streaming: bool = True
        self._extra_params: dict = {}

    def provider(self, name: str) -> "LLMProviderBuilder":
        """Define o provedor a ser usado."""
        self._provider_name = name
        return self

    def model(self, name: str) -> "LLMProviderBuilder":
        """Define o modelo a ser usado."""
        self._model = name
        return self

    def temperature(self, value: float) -> "LLMProviderBuilder":
        """Define a temperatura."""
        self._temperature = value
        return self

    def max_tokens(self, value: int) -> "LLMProviderBuilder":
        """Define o número máximo de tokens."""
        self._max_tokens = value
        return self

    def api_key(self, value: str) -> "LLMProviderBuilder":
        """Define a chave de API."""
        self._api_key = value
        return self

    def base_url(self, value: str) -> "LLMProviderBuilder":
        """Define a URL base."""
        self._base_url = value
        return self

    def streaming(self, value: bool) -> "LLMProviderBuilder":
        """Habilita ou desabilita streaming."""
        self._streaming = value
        return self

    def extra(self, **params) -> "LLMProviderBuilder":
        """Adiciona parâmetros extras."""
        self._extra_params.update(params)
        return self

    def build(self) -> BaseLLMProvider:
        """Constrói e retorna o provedor configurado.

        Returns:
            Instância do provedor

        Raises:
            ValueError: Se provider ou model não foram definidos
        """
        if not self._provider_name:
            raise ValueError("Provider name is required. Call .provider() first.")
        if not self._model:
            raise ValueError("Model name is required. Call .model() first.")

        config = LLMConfig(
            model=self._model,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            api_key=self._api_key,
            base_url=self._base_url,
            streaming=self._streaming,
            extra_params=self._extra_params,
        )
        return LLMProviderFactory.create_from_config(self._provider_name, config)
