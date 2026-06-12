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
from marvin_hue.chat.tools.light_tools import build_light_tools

SCENE_DESIGNER_PROMPT = (
    "Você é o scene-designer. Projeta cenas RGB multi-lâmpada para um mood, "
    "respeitando a localização física e a segurança ocular (Fita Led/Led cima <=25%). "
    "Use SOMENTE tools de cor/cena. Devolva a cena aplicada e o racional em 1 parágrafo."
)
CONFIG_LIBRARIAN_PROMPT = (
    "Você é o config-librarian. Busca, filtra e deduplica os presets existentes. "
    "ANTES de salvar um novo preset, recomende um existente equivalente se houver. "
    "Use tools de listar/buscar/salvar."
)
GENERAL_PROMPT = (
    "Você é o general-purpose. Responde status e perguntas gerais sobre as lâmpadas."
)


def _subset(tools: list[BaseTool], names: list[str]) -> list[BaseTool]:
    by = {t.name: t for t in tools}
    return [by[n] for n in names if n in by]


def build_subagents(
    model: BaseChatModel,
    controller: HueController,
    manager: LightSetupsManager,
    *,
    context_middleware: Optional[HueContextMiddleware] = None,
) -> dict[str, dict]:
    all_tools = build_light_tools(controller, manager)
    # REUSA a instância de HueContextMiddleware do orquestrador quando fornecida:
    # compartilha o cache TTL do status (Tarefa 3.3) — sem isso, cada subagent
    # faria seu próprio I/O na bridge a cada chamada de modelo.
    hue_context = context_middleware or HueContextMiddleware(controller, manager)
    safety = [hue_context, EyeSafetyMiddleware()]

    scene = create_agent(
        model=model,
        tools=_subset(all_tools, ["set_light_color", "apply_config", "get_light_locations", "get_light_status"]),
        system_prompt=SCENE_DESIGNER_PROMPT, middleware=list(safety),
    )
    librarian = create_agent(
        model=model,
        tools=_subset(all_tools, ["list_configs", "apply_config", "save_current_config", "get_light_status"]),
        system_prompt=CONFIG_LIBRARIAN_PROMPT, middleware=list(safety),
    )
    general = create_agent(
        model=model,
        tools=_subset(all_tools, ["list_lights", "get_light_status", "get_light_locations"]),
        system_prompt=GENERAL_PROMPT, middleware=list(safety),
    )
    return {
        "scene-designer": {"runnable": scene, "description": "Projeta cenas RGB multi-lâmpada para um mood."},
        "config-librarian": {"runnable": librarian, "description": "Busca/recomenda/salva presets dos existentes."},
        "general-purpose": {"runnable": general, "description": "Status e perguntas gerais."},
    }
