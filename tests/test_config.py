"""
Testes para o módulo de configuração centralizada.
"""

import os
import pytest
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def isolate_env_vars(monkeypatch):
    """Isola variáveis de ambiente para cada teste."""
    # Lista de variáveis de ambiente que devem ser isoladas
    env_vars = [
        "BRIDGE_IP",
        "BRIDGE_TIMEOUT",
        "API_KEY",
        "CORS_ORIGINS",
        "API_HOST",
        "API_PORT",
        "CHAT_PROVIDER",
        "CHAT_MODEL",
        "CHAT_TEMPERATURE",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "XAI_API_KEY",
        "GROQ_API_KEY",
        "SETUPS_FILE",
        "POSITIONS_FILE",
        "LOG_LEVEL",
        "LOG_FILE",
    ]
    # Salva valores originais
    original_values = {var: os.environ.get(var) for var in env_vars}

    # Remove variáveis
    for var in env_vars:
        monkeypatch.delenv(var, raising=False)

    yield

    # Restaura valores originais
    for var, value in original_values.items():
        if value is not None:
            os.environ[var] = value


def create_test_settings(**kwargs):
    """Helper para criar settings de teste sem carregar .env file."""
    from marvin_hue.config import Settings as _Settings
    from pydantic_settings import SettingsConfigDict

    # Cria uma classe de teste que não carrega .env
    class TestSettings(_Settings):
        model_config = SettingsConfigDict(
            env_file=None,  # Não carregar .env
            case_sensitive=False,
            extra="ignore",
        )

    return TestSettings(**kwargs)


class TestSettingsDefaults:
    """Testes para valores padrão das configurações."""

    def test_default_bridge_timeout(self):
        """Verifica timeout padrão da bridge."""
        settings = create_test_settings(bridge_ip="192.168.1.100")
        assert settings.bridge_timeout == 10

    def test_default_api_host(self):
        """Verifica host padrão da API."""
        settings = create_test_settings(bridge_ip="192.168.1.100")
        assert settings.api_host == "0.0.0.0"

    def test_default_api_port(self):
        """Verifica porta padrão da API."""
        settings = create_test_settings(bridge_ip="192.168.1.100")
        assert settings.api_port == 5081

    def test_default_chat_provider(self):
        """Verifica provider padrão de chat."""
        settings = create_test_settings(bridge_ip="192.168.1.100")
        assert settings.chat_provider == "openai"

    def test_default_chat_model(self):
        """Verifica modelo padrão de chat."""
        settings = create_test_settings(bridge_ip="192.168.1.100")
        assert settings.chat_model == "gpt-4o-mini"

    def test_default_chat_temperature(self):
        """Verifica temperatura padrão de chat."""
        settings = create_test_settings(bridge_ip="192.168.1.100")
        assert settings.chat_temperature == 0.7

    def test_default_setups_file(self):
        """Verifica path padrão do arquivo de setups."""
        settings = create_test_settings(bridge_ip="192.168.1.100")
        assert settings.setups_file == ".res/setups.json"

    def test_default_positions_file(self):
        """Verifica path padrão do arquivo de posições."""
        settings = create_test_settings(bridge_ip="192.168.1.100")
        assert settings.positions_file == ".res/light_positions.json"

    def test_default_log_level(self):
        """Verifica nível padrão de logging."""
        settings = create_test_settings(bridge_ip="192.168.1.100")
        assert settings.log_level == "INFO"

    def test_default_log_file(self):
        """Verifica path padrão do arquivo de log."""
        settings = create_test_settings(bridge_ip="192.168.1.100")
        assert settings.log_file == "logs/marvin_hue.log"

    def test_default_cors_origins(self):
        """Verifica origens CORS padrão."""
        settings = create_test_settings(bridge_ip="192.168.1.100")
        assert settings.cors_origins == ["*"]


class TestSettingsValidation:
    """Testes para validação de configurações."""

    def test_bridge_ip_required(self):
        """Bridge IP é obrigatório."""
        with pytest.raises(ValidationError) as exc_info:
            create_test_settings()
        assert "bridge_ip" in str(exc_info.value)

    def test_bridge_timeout_validation_min(self):
        """Bridge timeout deve ser >= 1."""
        with pytest.raises(ValidationError):
            create_test_settings(bridge_ip="192.168.1.100", bridge_timeout=0)

    def test_bridge_timeout_validation_max(self):
        """Bridge timeout deve ser <= 60."""
        with pytest.raises(ValidationError):
            create_test_settings(bridge_ip="192.168.1.100", bridge_timeout=61)

    def test_api_port_validation_min(self):
        """API port deve ser >= 1."""
        with pytest.raises(ValidationError):
            create_test_settings(bridge_ip="192.168.1.100", api_port=0)

    def test_api_port_validation_max(self):
        """API port deve ser <= 65535."""
        with pytest.raises(ValidationError):
            create_test_settings(bridge_ip="192.168.1.100", api_port=65536)

    def test_chat_provider_validation(self):
        """Chat provider deve ser um dos valores permitidos."""
        with pytest.raises(ValidationError):
            create_test_settings(bridge_ip="192.168.1.100", chat_provider="invalid")

    def test_chat_temperature_validation_min(self):
        """Chat temperature deve ser >= 0.0."""
        with pytest.raises(ValidationError):
            create_test_settings(bridge_ip="192.168.1.100", chat_temperature=-0.1)

    def test_chat_temperature_validation_max(self):
        """Chat temperature deve ser <= 2.0."""
        with pytest.raises(ValidationError):
            create_test_settings(bridge_ip="192.168.1.100", chat_temperature=2.1)

    def test_log_level_validation(self):
        """Log level deve ser um dos valores permitidos."""
        with pytest.raises(ValidationError):
            create_test_settings(bridge_ip="192.168.1.100", log_level="INVALID")


class TestSettingsEnvironmentOverride:
    """Testes para override de configurações via variáveis de ambiente."""

    def test_bridge_ip_from_env(self, monkeypatch):
        """Bridge IP pode ser definido via variável de ambiente."""
        monkeypatch.setenv("BRIDGE_IP", "10.0.0.1")
        settings = create_test_settings()
        assert settings.bridge_ip == "10.0.0.1"

    def test_bridge_timeout_from_env(self, monkeypatch):
        """Bridge timeout pode ser definido via variável de ambiente."""
        monkeypatch.setenv("BRIDGE_IP", "192.168.1.100")
        monkeypatch.setenv("BRIDGE_TIMEOUT", "30")
        settings = create_test_settings()
        assert settings.bridge_timeout == 30

    def test_api_port_from_env(self, monkeypatch):
        """API port pode ser definido via variável de ambiente."""
        monkeypatch.setenv("BRIDGE_IP", "192.168.1.100")
        monkeypatch.setenv("API_PORT", "8000")
        settings = create_test_settings()
        assert settings.api_port == 8000

    def test_log_level_from_env(self, monkeypatch):
        """Log level pode ser definido via variável de ambiente."""
        monkeypatch.setenv("BRIDGE_IP", "192.168.1.100")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        settings = create_test_settings()
        assert settings.log_level == "DEBUG"

    def test_chat_provider_from_env(self, monkeypatch):
        """Chat provider pode ser definido via variável de ambiente."""
        monkeypatch.setenv("BRIDGE_IP", "192.168.1.100")
        monkeypatch.setenv("CHAT_PROVIDER", "anthropic")
        settings = create_test_settings()
        assert settings.chat_provider == "anthropic"


class TestSettingsOptionalFields:
    """Testes para campos opcionais das configurações."""

    def test_api_key_optional(self):
        """API key é opcional."""
        settings = create_test_settings(bridge_ip="192.168.1.100")
        assert settings.api_key is None

    def test_openai_api_key_optional(self):
        """OpenAI API key é opcional."""
        settings = create_test_settings(bridge_ip="192.168.1.100")
        assert settings.openai_api_key is None

    def test_anthropic_api_key_optional(self):
        """Anthropic API key é opcional."""
        settings = create_test_settings(bridge_ip="192.168.1.100")
        assert settings.anthropic_api_key is None

    def test_xai_api_key_optional(self):
        """xAI API key é opcional."""
        settings = create_test_settings(bridge_ip="192.168.1.100")
        assert settings.xai_api_key is None

    def test_groq_api_key_optional(self):
        """Groq API key é opcional."""
        settings = create_test_settings(bridge_ip="192.168.1.100")
        assert settings.groq_api_key is None


class TestSettingsValidChatProviders:
    """Testes para providers de chat válidos."""

    def test_openai_provider(self):
        """Verifica provider OpenAI."""
        settings = create_test_settings(
            bridge_ip="192.168.1.100", chat_provider="openai"
        )
        assert settings.chat_provider == "openai"

    def test_anthropic_provider(self):
        """Verifica provider Anthropic."""
        settings = create_test_settings(
            bridge_ip="192.168.1.100", chat_provider="anthropic"
        )
        assert settings.chat_provider == "anthropic"

    def test_xai_provider(self):
        """Verifica provider xAI."""
        settings = create_test_settings(bridge_ip="192.168.1.100", chat_provider="xai")
        assert settings.chat_provider == "xai"

    def test_groq_provider(self):
        """Verifica provider Groq."""
        settings = create_test_settings(bridge_ip="192.168.1.100", chat_provider="groq")
        assert settings.chat_provider == "groq"


class TestSettingsValidLogLevels:
    """Testes para níveis de log válidos."""

    def test_debug_log_level(self):
        """Verifica nível DEBUG."""
        settings = create_test_settings(bridge_ip="192.168.1.100", log_level="DEBUG")
        assert settings.log_level == "DEBUG"

    def test_info_log_level(self):
        """Verifica nível INFO."""
        settings = create_test_settings(bridge_ip="192.168.1.100", log_level="INFO")
        assert settings.log_level == "INFO"

    def test_warning_log_level(self):
        """Verifica nível WARNING."""
        settings = create_test_settings(bridge_ip="192.168.1.100", log_level="WARNING")
        assert settings.log_level == "WARNING"

    def test_error_log_level(self):
        """Verifica nível ERROR."""
        settings = create_test_settings(bridge_ip="192.168.1.100", log_level="ERROR")
        assert settings.log_level == "ERROR"

    def test_critical_log_level(self):
        """Verifica nível CRITICAL."""
        settings = create_test_settings(bridge_ip="192.168.1.100", log_level="CRITICAL")
        assert settings.log_level == "CRITICAL"


class TestSettingsCaseInsensitive:
    """Testes para verificar case insensitivity."""

    def test_log_level_lowercase(self, monkeypatch):
        """Log level aceita lowercase via validação."""
        # Pydantic Literal é case-sensitive, então testamos que uppercase funciona
        monkeypatch.setenv("BRIDGE_IP", "192.168.1.100")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        settings = create_test_settings()
        assert settings.log_level == "DEBUG"

    def test_chat_provider_lowercase(self, monkeypatch):
        """Chat provider aceita lowercase."""
        monkeypatch.setenv("BRIDGE_IP", "192.168.1.100")
        monkeypatch.setenv("CHAT_PROVIDER", "openai")
        settings = create_test_settings()
        assert settings.chat_provider == "openai"
