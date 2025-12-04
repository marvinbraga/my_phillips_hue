"""
LLM Provider Registry - Padrão Registry para gerenciar provedores de LLM.

O Registry mantém um mapeamento de nomes de provedores para suas classes,
permitindo registro dinâmico e descoberta de provedores disponíveis.
"""

from typing import Type, Optional
from marvin_hue.chat.providers.base import BaseLLMProvider


class LLMProviderRegistry:
    """Registry central para provedores de LLM (Registry Pattern).

    Permite registrar, descobrir e obter classes de provedores de LLM
    de forma centralizada e extensível.

    Uso:
        # Registrar um provedor
        LLMProviderRegistry.register("openai", OpenAIProvider)

        # Obter um provedor
        provider_class = LLMProviderRegistry.get("openai")

        # Listar provedores disponíveis
        providers = LLMProviderRegistry.list_providers()
    """

    _providers: dict[str, Type[BaseLLMProvider]] = {}

    @classmethod
    def register(cls, name: str, provider_class: Type[BaseLLMProvider]) -> None:
        """Registra um provedor de LLM no registry.

        Args:
            name: Nome único do provedor (ex: "openai", "anthropic")
            provider_class: Classe do provedor que estende BaseLLMProvider

        Raises:
            ValueError: Se o nome já estiver registrado
            TypeError: Se a classe não for subclasse de BaseLLMProvider
        """
        if not issubclass(provider_class, BaseLLMProvider):
            raise TypeError(
                f"Provider class must be a subclass of BaseLLMProvider, "
                f"got {provider_class.__name__}"
            )

        name_lower = name.lower()
        if name_lower in cls._providers:
            raise ValueError(f"Provider '{name}' is already registered")

        cls._providers[name_lower] = provider_class

    @classmethod
    def unregister(cls, name: str) -> bool:
        """Remove um provedor do registry.

        Args:
            name: Nome do provedor a remover

        Returns:
            True se o provedor foi removido, False se não existia
        """
        name_lower = name.lower()
        if name_lower in cls._providers:
            del cls._providers[name_lower]
            return True
        return False

    @classmethod
    def get(cls, name: str) -> Optional[Type[BaseLLMProvider]]:
        """Obtém a classe de um provedor pelo nome.

        Args:
            name: Nome do provedor

        Returns:
            Classe do provedor ou None se não encontrado
        """
        return cls._providers.get(name.lower())

    @classmethod
    def get_or_raise(cls, name: str) -> Type[BaseLLMProvider]:
        """Obtém a classe de um provedor pelo nome ou levanta exceção.

        Args:
            name: Nome do provedor

        Returns:
            Classe do provedor

        Raises:
            KeyError: Se o provedor não estiver registrado
        """
        provider = cls.get(name)
        if provider is None:
            available = ", ".join(cls.list_providers())
            raise KeyError(
                f"Provider '{name}' not found. Available providers: {available}"
            )
        return provider

    @classmethod
    def list_providers(cls) -> list[str]:
        """Lista todos os provedores registrados.

        Returns:
            Lista de nomes de provedores disponíveis
        """
        return list(cls._providers.keys())

    @classmethod
    def is_registered(cls, name: str) -> bool:
        """Verifica se um provedor está registrado.

        Args:
            name: Nome do provedor

        Returns:
            True se o provedor está registrado
        """
        return name.lower() in cls._providers

    @classmethod
    def clear(cls) -> None:
        """Remove todos os provedores registrados (útil para testes)."""
        cls._providers.clear()

    @classmethod
    def get_provider_info(cls) -> dict[str, dict]:
        """Retorna informações sobre todos os provedores registrados.

        Returns:
            Dicionário com informações de cada provedor
        """
        info = {}
        for name, provider_class in cls._providers.items():
            # Instancia temporariamente para obter informações
            try:
                from marvin_hue.chat.providers.base import LLMConfig
                temp_config = LLMConfig(model="temp")
                temp_instance = provider_class(temp_config)
                info[name] = {
                    "class": provider_class.__name__,
                    "supported_models": temp_instance.supported_models,
                }
            except Exception:
                info[name] = {
                    "class": provider_class.__name__,
                    "supported_models": [],
                }
        return info


def register_provider(name: str):
    """Decorator para registrar automaticamente um provedor.

    Uso:
        @register_provider("custom")
        class CustomProvider(BaseLLMProvider):
            ...
    """
    def decorator(cls: Type[BaseLLMProvider]) -> Type[BaseLLMProvider]:
        LLMProviderRegistry.register(name, cls)
        return cls
    return decorator
