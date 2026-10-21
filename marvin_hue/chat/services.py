"""``ChatServices``: container de providers preguiçosos para as tools do chat (P5).

Cada provider é um callable sem argumentos resolvido **a cada chamada de tool**
(o lifespan pode recriar serviços; o agente não guarda referências velhas). Os
providers padrão leem o service locator ``marvin_hue.api.dependencies`` com
import tardio — evita o ciclo ``chat → api → chat`` no import do pacote.

Fail-open: provider que devolve ``None`` ou levanta → o getter devolve ``None``
e a tool responde com uma mensagem ("indisponível"), nunca uma exceção.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from marvin_hue.logging_config import get_logger

if TYPE_CHECKING:
    from marvin_hue.services.group_service import GroupService
    from marvin_hue.services.last_applied_scene import LastAppliedPort
    from marvin_hue.services.mirror_control import MirrorControlService
    from marvin_hue.services.scene_favorites import SceneFavoritesService
    from marvin_hue.services.scene_history import SceneHistoryService
    from marvin_hue.services.schedule_service import ScheduleService

logger = get_logger("chat.services")

Provider = Callable[[], Any]
HealthCollector = Callable[[], Awaitable[dict[str, Any]]]


def _from_dependencies(getter_name: str) -> Any:
    try:
        from marvin_hue.api import dependencies

        return getattr(dependencies, getter_name)()
    except (RuntimeError, ImportError):
        return None


def default_favorites_provider() -> "SceneFavoritesService | None":
    """SceneFavoritesService registrado no lifespan (ou None)."""
    return _from_dependencies("get_scene_favorites_service")


def default_history_provider() -> "SceneHistoryService | None":
    return _from_dependencies("get_scene_history_service")


def default_groups_provider() -> "GroupService | None":
    return _from_dependencies("get_group_service")


def default_schedules_provider() -> "ScheduleService | None":
    return _from_dependencies("get_schedule_service")


def default_mirror_provider() -> "MirrorControlService | None":
    """MirrorControlService só quando os mirrors do lifespan existem.

    ``get_mirror_control_service`` cria o serviço sob demanda; sem o mirror de
    tela registrado (fora do app) o chat o trata como indisponível.
    """
    if _from_dependencies("get_screen_mirror") is None:
        return None
    return _from_dependencies("get_mirror_control_service")


def default_last_applied_provider() -> "LastAppliedPort | None":
    """LastAppliedSceneService registrado no lifespan (ou None)."""
    return _from_dependencies("get_last_applied_scene_service_optional")


def default_health_provider() -> HealthCollector | None:
    """Coletor de saúde com os mesmos argumentos da rota ``GET /api/health``.

    ``collect_health`` e ``dependencies`` são importados aqui dentro:
    ``services/health.py`` importa ``marvin_hue.chat`` no topo (P14).
    """
    try:
        from marvin_hue.api import dependencies as deps
        from marvin_hue.services.health import collect_health

        hue = deps.get_hue_controller()
        screen_mirror = deps.get_screen_mirror()
    except (RuntimeError, ImportError):
        return None

    def _optional(getter: Callable[[], Any]) -> Any:
        try:
            return getter()
        except RuntimeError:
            return None

    async def _collect() -> dict[str, Any]:
        return await collect_health(
            hue=hue,
            screen_mirror=screen_mirror,
            chat_agent=deps.get_chat_agent(),
            chat_reason=deps.get_chat_unavailable_reason(),
            registry=_optional(deps.get_light_registry_service),
            schedule_runner=deps.get_schedule_runner(),
            schedule_service=_optional(deps.get_schedule_service),
            audio_mirror=_optional(deps.get_audio_mirror),
        )

    return _collect


def _resolve(provider: Provider | None) -> Any:
    if provider is None:
        return None
    try:
        return provider()
    except Exception as exc:  # noqa: BLE001 — fail-open: tool responde "indisponível"
        logger.warning(f"Chat service provider falhou (fail-open): {exc!r}")
        return None


@dataclass(frozen=True)
class ChatServices:
    """Providers preguiçosos dos serviços do app usados pelas tools do chat.

    ``lights_off_provider`` é um gancho de teste: em produção fica ``None`` e
    ``lights_off(controller)`` compõe ``LightsOffService(controller, history,
    mirror=..., last_applied=...)`` exatamente como a rota ``POST /lights/off``.
    """

    favorites_provider: Provider = default_favorites_provider
    history_provider: Provider = default_history_provider
    groups_provider: Provider = default_groups_provider
    schedules_provider: Provider = default_schedules_provider
    mirror_provider: Provider = default_mirror_provider
    health_provider: Provider = default_health_provider
    last_applied_provider: Provider = default_last_applied_provider
    lights_off_provider: Provider | None = None

    def favorites(self) -> Any:
        return _resolve(self.favorites_provider)

    def history(self) -> Any:
        return _resolve(self.history_provider)

    def groups(self) -> Any:
        return _resolve(self.groups_provider)

    def schedules(self) -> Any:
        return _resolve(self.schedules_provider)

    def mirror(self) -> Any:
        return _resolve(self.mirror_provider)

    def last_applied(self) -> Any:
        return _resolve(self.last_applied_provider)

    def health(self) -> HealthCollector | None:
        return _resolve(self.health_provider)

    def lights_off(self, controller: Any) -> Any:
        if self.lights_off_provider is not None:
            return _resolve(self.lights_off_provider)
        try:
            from marvin_hue.services.lights_off import LightsOffService

            return LightsOffService(
                controller,
                self.history(),
                mirror=self.mirror(),
                last_applied=self.last_applied(),
            )
        except Exception as exc:  # noqa: BLE001 — fail-open
            logger.warning(f"Chat lights_off indisponível (fail-open): {exc!r}")
            return None
