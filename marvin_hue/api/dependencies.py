"""
FastAPI Dependencies
Dependency injection para compartilhar instâncias globais.
"""

from marvin_hue.controllers import HueController
from marvin_hue.basics import LightSetupsManager
from marvin_hue.screen_mirror import ScreenMirror
from marvin_hue.chat import HueLightAgent

# Instâncias globais (inicializadas no lifespan)
_hue_controller: HueController | None = None
_manager: LightSetupsManager | None = None
_screen_mirror: ScreenMirror | None = None
_chat_agent: HueLightAgent | None = None
# Checkpointer ativo (cujo ciclo de vida é do lifespan). Guardado para que o
# reconfigure (/api/chat/configure) reuse o MESMO checkpointer em vez de cair
# silenciosamente para InMemorySaver quando chat_checkpoint=sqlite.
_chat_checkpointer: object | None = None


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


def set_chat_agent(agent: HueLightAgent | None) -> None:
    """Define a instância global do agente de chat."""
    global _chat_agent
    _chat_agent = agent


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
