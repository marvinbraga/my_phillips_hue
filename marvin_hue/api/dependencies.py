"""
FastAPI Dependencies
Dependency injection para compartilhar instâncias globais.
"""

from marvin_hue.controllers import HueController
from marvin_hue.basics import LightSetupsManager
from marvin_hue.screen_mirror import ScreenMirror
from marvin_hue.chat import HueLightAgent
from marvin_hue.services.light_registry import LightRegistryService

# Instâncias globais (inicializadas no lifespan)
_hue_controller: HueController | None = None
_manager: LightSetupsManager | None = None
_screen_mirror: ScreenMirror | None = None
_chat_agent: HueLightAgent | None = None
# Motivo sanitizado da última falha/indisponibilidade do agente de chat
# (sem secrets). Limpo quando o agente é definido com sucesso.
_chat_unavailable_reason: str | None = None
# Checkpointer ativo (cujo ciclo de vida é do lifespan). Guardado para que o
# reconfigure (/api/chat/configure) reuse o MESMO checkpointer em vez de cair
# silenciosamente para InMemorySaver quando chat_checkpoint=sqlite.
_chat_checkpointer: object | None = None
# App-owned lights catalog (SQLite) — separate from chat checkpointer DB.
_light_registry_service: LightRegistryService | None = None

# Mapa provider → (nome da env var, atributo em settings)
_PROVIDER_KEY_ENV: dict[str, tuple[str, str]] = {
    "openai": ("OPENAI_API_KEY", "openai_api_key"),
    "anthropic": ("ANTHROPIC_API_KEY", "anthropic_api_key"),
    "xai": ("XAI_API_KEY", "xai_api_key"),
    "groq": ("GROQ_API_KEY", "groq_api_key"),
}


def diagnose_chat_credentials(provider: str | None = None) -> str | None:
    """Diagnostica credenciais ausentes para o provider de chat.

    Returns:
        Mensagem em PT se a key estiver ausente/vazia; None se ok ou provider
        desconhecido. Nunca inclui o valor da chave.
    """
    from marvin_hue.config import settings

    prov = (provider or settings.chat_provider or "").strip().lower()
    mapping = _PROVIDER_KEY_ENV.get(prov)
    if mapping is None:
        return None

    env_var, attr = mapping
    value = getattr(settings, attr, None)
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return f"Provider '{prov}' sem {env_var} configurada."
    return None


def sanitize_chat_init_error(exc: BaseException, max_len: int = 200) -> str:
    """Primeira linha da exceção, truncada, sem stack — para resposta de API."""
    raw = str(exc).strip() or type(exc).__name__
    first_line = raw.splitlines()[0].strip()
    if len(first_line) > max_len:
        return first_line[: max_len - 1] + "…"
    return first_line


def set_chat_checkpointer(checkpointer: object | None) -> None:
    """Registra o checkpointer ativo (gerenciado pelo lifespan)."""
    global _chat_checkpointer
    _chat_checkpointer = checkpointer


def get_chat_checkpointer() -> object | None:
    """Retorna o checkpointer ativo (ou None para InMemorySaver no agente)."""
    return _chat_checkpointer


def set_hue_controller(controller: HueController) -> None:
    """Define a instância global do controlador Hue."""
    global _hue_controller
    _hue_controller = controller


def set_manager(manager: LightSetupsManager) -> None:
    """Define a instância global do gerenciador de setups."""
    global _manager
    _manager = manager


def set_screen_mirror(mirror: ScreenMirror) -> None:
    """Define a instância global do screen mirror."""
    global _screen_mirror
    _screen_mirror = mirror


def set_chat_agent(agent: HueLightAgent | None, reason: str | None = None) -> None:
    """Define a instância global do agente de chat.

    Quando ``agent`` é definido com sucesso, limpa o motivo de indisponibilidade.
    Quando ``agent`` é None, grava ``reason`` (diagnóstico sanitizado).
    """
    global _chat_agent, _chat_unavailable_reason
    _chat_agent = agent
    if agent is not None:
        _chat_unavailable_reason = None
    else:
        _chat_unavailable_reason = reason


def get_chat_unavailable_reason() -> str | None:
    """Retorna o motivo sanitizado da indisponibilidade do agente de chat."""
    return _chat_unavailable_reason


def get_hue_controller() -> HueController:
    """Retorna a instância do controlador Hue."""
    if _hue_controller is None:
        raise RuntimeError("HueController não inicializado")
    return _hue_controller


def get_manager() -> LightSetupsManager:
    """Retorna a instância do gerenciador de setups."""
    if _manager is None:
        raise RuntimeError("LightSetupsManager não inicializado")
    return _manager


def get_screen_mirror() -> ScreenMirror:
    """Retorna a instância do screen mirror."""
    if _screen_mirror is None:
        raise RuntimeError("ScreenMirror não inicializado")
    return _screen_mirror


def get_chat_agent() -> HueLightAgent | None:
    """Retorna a instância do agente de chat (pode ser None)."""
    return _chat_agent


def set_light_registry_service(service: LightRegistryService | None) -> None:
    """Define a instância global do LightRegistryService."""
    global _light_registry_service
    _light_registry_service = service


def get_light_registry_service() -> LightRegistryService:
    """Retorna a instância do LightRegistryService."""
    if _light_registry_service is None:
        raise RuntimeError("LightRegistryService não inicializado")
    return _light_registry_service
