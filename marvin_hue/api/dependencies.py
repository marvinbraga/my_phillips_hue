"""
FastAPI Dependencies
Dependency injection para compartilhar instâncias globais.
"""

from collections.abc import Awaitable, Callable
from typing import cast

from fastapi import FastAPI

from marvin_hue.audio_mirror import AudioMirror
from marvin_hue.basics import LightSetupsManager
from marvin_hue.chat import HueLightAgent
from marvin_hue.controllers import HueController
from marvin_hue.entertainment.client import EntertainmentClient
from marvin_hue.persistence.favorites_repository import SceneFavoritesRepository
from marvin_hue.persistence.group_repository import GroupRepository
from marvin_hue.persistence.light_repository import LightRegistryRepository
from marvin_hue.persistence.schedule_repository import ScheduleRepository
from marvin_hue.screen_mirror import ScreenMirror
from marvin_hue.services.backup import BackupService
from marvin_hue.services.group_service import GroupService
from marvin_hue.services.light_registry import LightRegistryService
from marvin_hue.services.mirror_control import MirrorControlService
from marvin_hue.services.scene_favorites import SceneFavoritesService
from marvin_hue.services.scene_history import SceneHistoryService
from marvin_hue.services.schedule_runner import ScheduleRunner
from marvin_hue.services.schedule_service import ScheduleService

# Instâncias globais (inicializadas no lifespan)
_hue_controller: HueController | None = None
_manager: LightSetupsManager | None = None
_screen_mirror: ScreenMirror | None = None
_audio_mirror: AudioMirror | None = None
_entertainment_client: EntertainmentClient | None = None
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
_group_service: GroupService | None = None
_scene_history_service: SceneHistoryService | None = None
_schedule_service: ScheduleService | None = None
_schedule_runner: ScheduleRunner | None = None
_mirror_control_service: MirrorControlService | None = None
_backup_service: BackupService | None = None
_scene_favorites_service: SceneFavoritesService | None = None
_bound_app: FastAPI | None = None

_DEFAULT_PHYSICAL_LOCATIONS = ".res/light_physical_locations.json"


def bind_fastapi_app(app: FastAPI | None) -> None:
    """Remember the FastAPI app so setters dual-write to ``app.state``."""
    global _bound_app
    _bound_app = app


def _sync_app_state(name: str, value: object) -> None:
    if _bound_app is None:
        return
    setattr(_bound_app.state, name, value)


def populate_app_state(app: FastAPI) -> None:
    """Copy locator instances onto ``app.state`` (lifespan dual-write)."""
    bind_fastapi_app(app)
    app.state.hue_controller = _hue_controller
    app.state.manager = _manager
    app.state.screen_mirror = _screen_mirror
    app.state.audio_mirror = _audio_mirror
    app.state.entertainment_client = _entertainment_client
    app.state.chat_agent = _chat_agent
    app.state.chat_checkpointer = _chat_checkpointer
    app.state.light_registry_service = _light_registry_service
    app.state.group_service = _group_service
    app.state.scene_history_service = _scene_history_service
    app.state.schedule_service = _schedule_service
    app.state.schedule_runner = _schedule_runner
    app.state.mirror_control_service = _mirror_control_service
    app.state.backup_service = _backup_service
    app.state.scene_favorites_service = _scene_favorites_service


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
    _sync_app_state("chat_checkpointer", checkpointer)


def get_chat_checkpointer() -> object | None:
    """Retorna o checkpointer ativo (ou None para InMemorySaver no agente)."""
    return _chat_checkpointer


def set_hue_controller(controller: HueController) -> None:
    """Define a instância global do controlador Hue."""
    global _hue_controller
    _hue_controller = controller
    _sync_app_state("hue_controller", controller)


def set_manager(manager: LightSetupsManager) -> None:
    """Define a instância global do gerenciador de setups."""
    global _manager
    _manager = manager
    _sync_app_state("manager", manager)


def set_screen_mirror(mirror: ScreenMirror) -> None:
    """Define a instância global do screen mirror."""
    global _screen_mirror
    _screen_mirror = mirror
    _sync_app_state("screen_mirror", mirror)


def set_audio_mirror(mirror: AudioMirror) -> None:
    """Define a instância global do audio/music mirror."""
    global _audio_mirror
    _audio_mirror = mirror
    _sync_app_state("audio_mirror", mirror)


def set_entertainment_client(client: EntertainmentClient | None) -> None:
    """Define o cliente Entertainment (pode ser None se desabilitado/sem creds)."""
    global _entertainment_client
    _entertainment_client = client
    _sync_app_state("entertainment_client", client)


def get_entertainment_client() -> EntertainmentClient | None:
    """Retorna o EntertainmentClient (None se não inicializado)."""
    return _entertainment_client


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
    _sync_app_state("chat_agent", agent)
    _sync_app_state("chat_unavailable_reason", _chat_unavailable_reason)


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


def get_audio_mirror() -> AudioMirror:
    """Retorna a instância do audio/music mirror."""
    if _audio_mirror is None:
        raise RuntimeError("AudioMirror não inicializado")
    return _audio_mirror


def get_chat_agent() -> HueLightAgent | None:
    """Retorna a instância do agente de chat (pode ser None)."""
    return _chat_agent


def set_light_registry_service(service: LightRegistryService | None) -> None:
    """Define a instância global do LightRegistryService."""
    global _light_registry_service
    _light_registry_service = service
    _sync_app_state("light_registry_service", service)


def get_light_registry_service() -> LightRegistryService:
    """Retorna a instância do LightRegistryService."""
    if _light_registry_service is None:
        raise RuntimeError("LightRegistryService não inicializado")
    return _light_registry_service


def set_group_service(service: GroupService | None) -> None:
    """Define a instância global do GroupService."""
    global _group_service
    _group_service = service
    _sync_app_state("group_service", service)


def get_group_service() -> GroupService:
    """Retorna a instância do GroupService."""
    if _group_service is None:
        raise RuntimeError("GroupService não inicializado")
    return _group_service


def set_scene_history_service(service: SceneHistoryService | None) -> None:
    """Define a instância global do SceneHistoryService."""
    global _scene_history_service
    _scene_history_service = service
    _sync_app_state("scene_history_service", service)


def get_scene_history_service() -> SceneHistoryService:
    """Retorna a instância do SceneHistoryService."""
    if _scene_history_service is None:
        raise RuntimeError("SceneHistoryService não inicializado")
    return _scene_history_service


def set_schedule_service(service: ScheduleService | None) -> None:
    """Define a instância global do ScheduleService."""
    global _schedule_service
    _schedule_service = service
    _sync_app_state("schedule_service", service)


def get_schedule_service() -> ScheduleService:
    """Retorna a instância do ScheduleService."""
    if _schedule_service is None:
        raise RuntimeError("ScheduleService não inicializado")
    return _schedule_service


def set_schedule_runner(runner: ScheduleRunner | None) -> None:
    """Define a instância global do ScheduleRunner."""
    global _schedule_runner
    _schedule_runner = runner
    _sync_app_state("schedule_runner", runner)


def get_schedule_runner() -> ScheduleRunner | None:
    """Retorna o ScheduleRunner (pode ser None se não iniciado)."""
    return _schedule_runner


def set_scene_favorites_service(service: SceneFavoritesService | None) -> None:
    """Define (ou limpa) a instância global do SceneFavoritesService."""
    global _scene_favorites_service
    _scene_favorites_service = service
    _sync_app_state("scene_favorites_service", service)


def get_scene_favorites_service() -> SceneFavoritesService:
    """Retorna a instância do SceneFavoritesService."""
    if _scene_favorites_service is None:
        raise RuntimeError("SceneFavoritesService não inicializado")
    return _scene_favorites_service


def set_mirror_control_service(service: MirrorControlService | None) -> None:
    """Define (ou limpa) a instância do MirrorControlService."""
    global _mirror_control_service
    _mirror_control_service = service
    _sync_app_state("mirror_control_service", service)


def get_mirror_control_service() -> MirrorControlService:
    """Retorna o MirrorControlService (lazy, getters de mirrors atuais)."""
    global _mirror_control_service
    if _mirror_control_service is None:

        def _history() -> SceneHistoryService | None:
            try:
                return get_scene_history_service()
            except RuntimeError:
                return None

        _mirror_control_service = MirrorControlService(
            get_screen=get_screen_mirror,
            get_audio=get_audio_mirror,
            get_hue=get_hue_controller,
            get_manager=get_manager,
            get_entertainment=get_entertainment_client,
            get_history=_history,
        )
    return _mirror_control_service


def _repository_from_service(service: object) -> object:
    repo = getattr(service, "repository", None)
    if repo is not None:
        return repo
    repo = getattr(service, "_repo", None)
    if repo is None:
        raise RuntimeError("Service has no repository for backup")
    return repo


def build_backup_service(
    light_repo: LightRegistryRepository,
    *,
    group_repo: GroupRepository | None = None,
    schedule_repo: ScheduleRepository | None = None,
    favorites_repo: SceneFavoritesRepository | None = None,
    on_lights_changed: Callable[[], Awaitable[None]] | None = None,
    app_version: str = "2.0.0",
) -> BackupService:
    """Compose BackupService from already-open lifespan repositories."""
    from marvin_hue.config import settings

    physical_path = getattr(
        settings, "physical_locations_file", _DEFAULT_PHYSICAL_LOCATIONS
    )
    return BackupService(
        light_repo,
        group_repo=group_repo,
        schedule_repo=schedule_repo,
        favorites_repo=favorites_repo,
        setups_path=settings.setups_file,
        positions_path=settings.positions_file,
        physical_locations_path=physical_path,
        on_lights_changed=on_lights_changed,
        app_version=app_version,
    )


def set_backup_service(service: BackupService | None) -> None:
    """Define (or clear) the BackupService built in lifespan."""
    global _backup_service
    _backup_service = service
    _sync_app_state("backup_service", service)


def get_backup_service() -> BackupService:
    """Return the lifespan BackupService, or wrap current service repos.

    Never opens a new Sqlite*Repository connection.
    """
    if _backup_service is not None:
        return _backup_service

    light_svc = get_light_registry_service()
    group_svc = get_group_service()
    schedule_svc = get_schedule_service()

    favorites_repo: SceneFavoritesRepository | None = None
    if _scene_favorites_service is not None:
        favorites_repo = _scene_favorites_service.repository

    async def _refresh() -> None:
        await light_svc.refresh_runtime_policy()

    return build_backup_service(
        light_svc.repository,
        group_repo=cast(GroupRepository, _repository_from_service(group_svc)),
        schedule_repo=cast(ScheduleRepository, _repository_from_service(schedule_svc)),
        favorites_repo=favorites_repo,
        on_lights_changed=_refresh,
    )
