"""Definição dos subagents do harness Hue (isolamento de contexto)."""
from __future__ import annotations

from typing import Optional

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool

from marvin_hue.controllers import HueController
from marvin_hue.basics import LightSetupsManager
from marvin_hue.chat.middleware.eye_safety import EyeSafetyMiddleware
from marvin_hue.chat.middleware.hue_context import HueContextMiddleware
from marvin_hue.chat.hitl import interrupt_on_for
from marvin_hue.chat.services import ChatServices
from marvin_hue.chat.tools import build_all_tools

SCENE_DESIGNER_PROMPT = (
    "Você é o scene-designer. Projeta cenas RGB multi-lâmpada para um mood, "
    "respeitando a localização física e a segurança ocular (Fita Led/Led cima <=25%). "
    "Use SOMENTE tools de cor/cena (inclui temperatura de cor em Kelvin e "
    "create_config para gravar a cena sem aplicar). Devolva a cena aplicada e "
    "o racional em 1 parágrafo."
)
CONFIG_LIBRARIAN_PROMPT = (
    "Você é o config-librarian. Busca, filtra e deduplica os presets existentes. "
    "ANTES de salvar um novo preset, recomende um existente equivalente se houver. "
    "Use tools de listar/buscar/detalhar/criar/salvar e de favoritos "
    "(listar/marcar/desmarcar)."
)
GENERAL_PROMPT = (
    "Você é o general-purpose. Responde status e perguntas gerais sobre as "
    "lâmpadas, saúde do sistema, espelhamento, grupos e agendamentos (só consulta)."
)

# Subconjuntos de tools por subagent (least-privilege). Extraídos como
# constantes para serem testáveis contra typos (um nome inválido seria
# silenciosamente descartado por _subset).
SCENE_DESIGNER_TOOLS = [
    "set_light_color",
    "apply_config",
    "get_light_locations",
    "get_light_status",
    "list_lights_by_room",
    "set_room_power",
    "set_room_brightness",
    "set_color_temperature",
    "describe_config",
    "create_config",
]
CONFIG_LIBRARIAN_TOOLS = [
    "list_configs",
    "search_configs",
    "describe_config",
    "create_config",
    "apply_config",
    "save_current_config",
    "get_light_status",
    "list_favorites",
    "add_favorite",
    "remove_favorite",
]
GENERAL_TOOLS = [
    "list_lights",
    "get_light_status",
    "get_light_locations",
    "get_rooms",
    "list_lights_by_room",
    "get_system_health",
    "get_mirror_status",
    "list_groups",
    "list_schedules",
]


def _subset(tools: list[BaseTool], names: list[str]) -> list[BaseTool]:
    by = {t.name: t for t in tools}
    return [by[n] for n in names if n in by]


def build_subagents(
    model: BaseChatModel,
    controller: HueController,
    manager: LightSetupsManager,
    *,
    context_middleware: Optional[HueContextMiddleware] = None,
    room_index: Optional[dict[str, list[str]]] = None,
    services: Optional[ChatServices] = None,
    require_approval: bool = False,
    prompt_caching: bool = False,
) -> dict[str, dict]:
    """Monta os três subagents com tools least-privilege.

    ``prompt_caching`` liga ``AnthropicPromptCachingMiddleware`` (o chamador
    passa True só quando o provider é anthropic, como no orquestrador).
    """
    all_tools = build_all_tools(
        controller, manager, room_index=room_index, services=services,
    )
    # REUSA a instância de HueContextMiddleware do orquestrador quando fornecida:
    # compartilha o cache TTL do status (Tarefa 3.3) — sem isso, cada subagent
    # faria seu próprio I/O na bridge a cada chamada de modelo.
    hue_context = context_middleware or HueContextMiddleware(controller, manager)
    safety = [hue_context, EyeSafetyMiddleware()]

    def _middleware(names: list[str]) -> list:
        # Mesma política HITL do orquestrador: sem isso a delegação via `task`
        # contornaria a aprovação das tools de mutação.
        stack = list(safety)
        if prompt_caching:
            from marvin_hue.chat.middleware.caching import prompt_caching_middleware

            stack.append(prompt_caching_middleware())
        interrupt_on = interrupt_on_for(names) if require_approval else {}
        if interrupt_on:
            from langchain.agents.middleware import HumanInTheLoopMiddleware

            stack.append(HumanInTheLoopMiddleware(interrupt_on=interrupt_on))
        return stack

    scene = create_agent(
        model=model,
        tools=_subset(all_tools, SCENE_DESIGNER_TOOLS),
        system_prompt=SCENE_DESIGNER_PROMPT,
        middleware=_middleware(SCENE_DESIGNER_TOOLS),
    )
    librarian = create_agent(
        model=model,
        tools=_subset(all_tools, CONFIG_LIBRARIAN_TOOLS),
        system_prompt=CONFIG_LIBRARIAN_PROMPT,
        middleware=_middleware(CONFIG_LIBRARIAN_TOOLS),
    )
    general = create_agent(
        model=model,
        tools=_subset(all_tools, GENERAL_TOOLS),
        system_prompt=GENERAL_PROMPT,
        middleware=_middleware(GENERAL_TOOLS),
    )
    return {
        "scene-designer": {"runnable": scene, "description": "Projeta cenas RGB multi-lâmpada para um mood."},
        "config-librarian": {"runnable": librarian, "description": "Busca/recomenda/salva presets dos existentes."},
        "general-purpose": {"runnable": general, "description": "Status e perguntas gerais."},
    }
