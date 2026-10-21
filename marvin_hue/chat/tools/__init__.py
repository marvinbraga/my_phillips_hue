"""
Hue Light Tools Module

Ferramentas do agente: lâmpadas (``light_tools``), cenas (``scene_tools``),
grupos/agendamentos (``automation_tools``) e sistema (``system_tools``).
``build_all_tools`` junta tudo para o orquestrador e os subagents.
"""

from collections.abc import Mapping, Sequence

from langchain_core.tools import BaseTool

from marvin_hue.basics import LightSetupsManager
from marvin_hue.chat.services import ChatServices
from marvin_hue.chat.tools.automation_tools import build_automation_tools
from marvin_hue.chat.tools.light_tools import build_light_tools
from marvin_hue.chat.tools.rooms import (
    DEFAULT_LOCATIONS_PATH,
    build_room_index_from_registry_rows,
    normalize_room_index,
)
from marvin_hue.chat.tools.scene_tools import build_scene_tools
from marvin_hue.chat.tools.system_tools import build_system_tools
from marvin_hue.controllers import HueController


def build_all_tools(
    controller: HueController,
    manager: LightSetupsManager,
    locations_path: str = DEFAULT_LOCATIONS_PATH,
    *,
    room_index: Mapping[str, Sequence[str]] | None = None,
    services: ChatServices | None = None,
) -> list[BaseTool]:
    """Todas as tools do chat, sem nomes duplicados.

    Args:
        controller: HueController (API pública).
        manager: LightSetupsManager.
        locations_path: JSON de localizações (fallback sem registry).
        room_index: snapshot sala → lâmpadas do registry (ver ``build_light_tools``).
        services: providers preguiçosos dos serviços do app. None → padrão
            (``api.dependencies``, fail-open).
    """
    chat_services = services or ChatServices()
    # Normaliza uma vez; os builders recebem o mesmo índice (idempotente).
    rooms = normalize_room_index(room_index, locations_path)
    tools: list[BaseTool] = [
        *build_light_tools(
            controller,
            manager,
            locations_path,
            room_index=rooms,
            services=chat_services,
        ),
        *build_scene_tools(controller, manager, chat_services, rooms=rooms),
        *build_automation_tools(controller, manager, chat_services),
        *build_system_tools(controller, chat_services, rooms=rooms),
    ]
    names = [t.name for t in tools]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ValueError(f"Tools duplicadas: {duplicates}")
    return tools


__all__ = [
    "ChatServices",
    "build_all_tools",
    "build_light_tools",
    "build_room_index_from_registry_rows",
]
