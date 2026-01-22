"""
Configurações centralizadas do Marvin Hue.

Este módulo define todas as configurações da aplicação usando Pydantic Settings,
permitindo carregamento a partir de variáveis de ambiente ou arquivo .env.
"""

from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Configurações centralizadas do Marvin Hue.

    Todas as configurações podem ser sobrescritas via variáveis de ambiente.
    Por exemplo: BRIDGE_IP=192.168.1.100 python app.py

    Attributes:
        bridge_ip: Endereço IP do Philips Hue Bridge (obrigatório)
        bridge_timeout: Timeout em segundos para operações com a bridge

        api_key: API key opcional para autenticação
        cors_origins: Lista de origens permitidas para CORS (separadas por vírgula em .env)
        api_host: Host onde a API será servida
        api_port: Porta onde a API será servida

        chat_provider: Provider de chat (openai, anthropic, xai, groq)
        chat_model: Modelo específico a usar (ex: gpt-4o-mini, claude-3-5-sonnet-20241022)
        chat_temperature: Temperatura para geração de texto (0.0-1.0)
        openai_api_key: API key para OpenAI
        anthropic_api_key: API key para Anthropic
        xai_api_key: API key para xAI
        groq_api_key: API key para Groq

        setups_file: Caminho para o arquivo JSON de configurações de iluminação
        positions_file: Caminho para o arquivo JSON de posições das lâmpadas

        log_level: Nível de logging (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Caminho para o arquivo de log
    """

    # Bridge Configuration
    bridge_ip: str = Field(..., description="IP address do Philips Hue Bridge")
    bridge_timeout: int = Field(
        default=10,
        ge=1,
        le=60,
        description="Timeout em segundos para operações com a bridge",
    )

    # API Configuration
    api_key: str | None = Field(
        default=None, description="API key opcional para autenticação"
    )
    cors_origins: list[str] = Field(
        default=["*"],
        description="CORS allowed origins (separados por vírgula em .env)",
    )
    api_host: str = Field(default="0.0.0.0", description="Host da API")
    api_port: int = Field(default=5000, ge=1, le=65535, description="Porta da API")

    # Chat Configuration
    chat_provider: Literal["openai", "anthropic", "xai", "groq"] = Field(
        default="openai", description="Provider de chat (openai, anthropic, xai, groq)"
    )
    chat_model: str = Field(
        default="gpt-4o-mini", description="Modelo de chat a ser usado"
    )
    chat_temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Temperatura para geração de texto (0.0-1.0)",
    )
    openai_api_key: str | None = Field(default=None, description="API key para OpenAI")
    anthropic_api_key: str | None = Field(
        default=None, description="API key para Anthropic"
    )
    xai_api_key: str | None = Field(default=None, description="API key para xAI")
    groq_api_key: str | None = Field(default=None, description="API key para Groq")

    # File Paths
    setups_file: str = Field(
        default=".res/setups.json",
        description="Caminho para o arquivo JSON de configurações",
    )
    positions_file: str = Field(
        default=".res/light_positions.json",
        description="Caminho para o arquivo JSON de posições",
    )

    # Logging Configuration
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="Nível de logging"
    )
    log_file: str = Field(
        default="logs/marvin_hue.log", description="Caminho para o arquivo de log"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Ignora variáveis extras não definidas
    )


# Singleton instance - usar esta instância em todo o código
settings = Settings()
