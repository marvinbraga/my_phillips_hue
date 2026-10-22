"""Tools de cena do chat: busca, descrição, criação, desfazer e favoritos.

Invólucros finos sobre serviços existentes (``LightSetupsManager``,
``build_scene_preview``, ``SceneHistoryService``, ``SceneFavoritesService``,
``LastAppliedSceneService``). Nenhuma tool levanta exceção para o agente:
erros de domínio viram mensagem própria; erros inesperados viram mensagem
genérica e o detalhe fica no log do servidor.

Favoritos e desfazer são async (aiosqlite no loop do FastAPI); o caminho
síncrono devolve mensagem sem tocar o serviço (ver ``_common.service_tool``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from marvin_hue.basics import (
    DuplicateConfigError,
    LightConfig,
    LightSetting,
    LightSetupsManager,
    ReservedConfigNameError,
    is_reserved_config_name,
)
from marvin_hue.chat.services import ChatServices
from marvin_hue.chat.tools._common import (
    SINGLE_LINE,
    hue_to_pct,
    pct_to_hue,
    reserved_scene_name,
    resolve_scene,
    service_tool,
    unavailable,
    unexpected_error,
)
from marvin_hue.colors import Color
from marvin_hue.domain.scene_history import SceneHistoryNotFoundError
from marvin_hue.eye_safety import effective_hue_brightness
from marvin_hue.services.last_applied_scene import clear_after_undo
from marvin_hue.services.scene_favorites import FavoriteConfigNotFoundError
from marvin_hue.services.scene_preview import build_scene_preview

if TYPE_CHECKING:
    from marvin_hue.controllers import HueController

_UNDO_LABEL = "Desfazer"
_FAVORITES_LABEL = "Favoritos"
CONFIG_NAME_MAX = 64
DESCRIPTION_MAX = 200


def _short(text: str, size: int = 70) -> str:
    return text if len(text) <= size else text[: size - 3] + "..."


def known_light_names(
    controller: "HueController", rooms: Mapping[str, Sequence[str]]
) -> dict[str, str]:
    """casefold → nome canônico: bridge (cache do controller) ∪ registry snapshot."""
    names: list[str] = []
    try:
        names.extend(str(n) for n in controller.list_lights())
    except Exception:  # noqa: BLE001 — bridge fora: valida só pelo registry
        pass
    for loc in getattr(rooms, "locations", None) or ():
        names.append(str(loc.name))
    for room_names in rooms.values():
        names.extend(str(n) for n in room_names)
    return {n.casefold(): n for n in names if n}


class _SearchArgs(BaseModel):
    query: str = Field(
        max_length=100, description="Termos de busca (tema, mood, nome ou lâmpada)"
    )
    limit: int = Field(default=10, ge=1, le=30, description="Máximo de resultados")


class _DescribeArgs(BaseModel):
    name: str = Field(max_length=100, description="Nome da cena (sem diferenciar maiúsculas)")


class _SceneLightSpec(BaseModel):
    light_name: str = Field(max_length=100, description="Nome da lâmpada")
    red: int = Field(ge=0, le=255, description="Vermelho 0-255")
    green: int = Field(ge=0, le=255, description="Verde 0-255")
    blue: int = Field(ge=0, le=255, description="Azul 0-255")
    brightness_pct: int = Field(ge=0, le=100, description="Brilho 0-100%")


class _CreateConfigArgs(BaseModel):
    # ^\w+$ como em save_current_config: sem espaços/quebras de linha (o nome é
    # reinjetado no contexto do modelo — fecha vetor de injeção de prompt).
    name: str = Field(
        pattern=r"^\w+$",
        max_length=CONFIG_NAME_MAX,
        description="Nome único, sem espaços (use _)",
    )
    description: str = Field(
        max_length=DESCRIPTION_MAX,
        pattern=SINGLE_LINE,
        description="Descrição de uma linha do mood da cena",
    )
    settings: list[_SceneLightSpec] = Field(
        min_length=1, max_length=20, description="Cor e brilho de cada lâmpada da cena"
    )


class _FavoriteArgs(BaseModel):
    config_name: str = Field(
        max_length=100, description="Nome exato da cena/preset (veja list_configs)."
    )


def build_scene_tools(
    controller: "HueController",
    manager: LightSetupsManager,
    services: ChatServices,
    *,
    rooms: Mapping[str, Sequence[str]] | None = None,
) -> list[BaseTool]:
    """Tools de cena. ``rooms`` é o room_index já normalizado (registry snapshot)."""
    rooms_map: Mapping[str, Sequence[str]] = rooms if rooms is not None else {}

    # ----- busca / descrição (sync, sem I/O de rede) -----
    def _search_configs(query: str, limit: int = 10) -> str:
        tokens = [t for t in (query or "").casefold().split() if t]
        if not tokens:
            return "Informe um termo de busca."
        hits: list[tuple[int, str, LightConfig]] = []
        for cfg in manager.configs:
            name = cfg.name.casefold()
            lights = " ".join(s.light_name for s in cfg.settings).casefold()
            haystack = f"{name} {cfg.description.casefold()} {lights}"
            if all(t in haystack for t in tokens):
                rank = 0 if all(t in name for t in tokens) else 1
                hits.append((rank, cfg.name.casefold(), cfg))
        if not hits:
            return (
                f"Nenhuma cena encontrada para '{query}'. "
                "Use list_configs para ver todas."
            )
        hits.sort(key=lambda h: (h[0], h[1]))
        shown = hits[:limit]
        lines = [f"Cenas encontradas para '{query}' ({len(hits)}):"]
        lines.extend(f"- {cfg.name}: {_short(cfg.description)}" for _, _, cfg in shown)
        if len(hits) > len(shown):
            lines.append(f"(mostrando {len(shown)} de {len(hits)})")
        return "\n".join(lines)

    def _describe_config(name: str) -> str:
        canonical, error = resolve_scene(manager, name)
        if canonical is None:
            return error or ""
        cfg = manager.get_config(canonical)
        if cfg is None:
            return f"A cena '{name}' não existe."
        lines = [f"Cena '{cfg.name}': {cfg.description or '(sem descrição)'}"]
        for item in build_scene_preview(cfg):
            configured = int(item.color.get("brightness", item.brightness))
            line = (
                f"- {item.light_name}: RGB({item.color.get('red')}, "
                f"{item.color.get('green')}, {item.color.get('blue')}), "
                f"brilho efetivo {hue_to_pct(item.brightness)}%"
            )
            if item.brightness < configured:
                line += " (limitado pela segurança ocular)"
            if not item.enabled:
                line += " [desabilitada no app: ignorada ao aplicar]"
            lines.append(line)
        if len(lines) == 1:
            lines.append("(cena sem lâmpadas)")
        return "\n".join(lines)

    # ----- criação pela especificação (sem aplicar) -----
    def _create_config(
        name: str, description: str, settings: list[_SceneLightSpec | dict[str, Any]]
    ) -> str:
        if is_reserved_config_name(name):
            return reserved_scene_name(name)
        existing = {c.name.casefold(): c.name for c in manager.configs}
        duplicate = "Já existe uma cena com o nome '{name}'. Escolha outro nome."
        if name.casefold() in existing:
            return duplicate.format(name=existing[name.casefold()])
        known = known_light_names(controller, rooms_map)
        specs = [
            s if isinstance(s, _SceneLightSpec) else _SceneLightSpec(**s)
            for s in settings
        ]
        unknown = [s.light_name for s in specs if s.light_name.casefold() not in known]
        if unknown:
            return (
                f"Lâmpada(s) que não existe(m): {', '.join(unknown)}. "
                f"Lâmpadas conhecidas: {', '.join(sorted(known.values()))}."
            )
        seen: set[str] = set()
        light_settings: list[LightSetting] = []
        for spec in specs:
            canonical = known[spec.light_name.casefold()]
            if canonical in seen:
                return f"Lâmpada repetida na cena: '{canonical}'. Use uma entrada por lâmpada."
            seen.add(canonical)
            brightness = effective_hue_brightness(canonical, pct_to_hue(spec.brightness_pct))
            light_settings.append(
                LightSetting(canonical, Color(spec.red, spec.green, spec.blue, brightness))
            )
        new_config = LightConfig(
            name=name, settings=light_settings, description=description or ""
        )
        try:
            # Check-append-save sob lock; falha na escrita desfaz e levanta.
            manager.add_config(new_config)
        except ReservedConfigNameError:
            return reserved_scene_name(name)
        except DuplicateConfigError:
            return duplicate.format(name=name)
        except Exception as e:  # noqa: BLE001
            return unexpected_error(f"salvar a cena '{name}'", e, verb="Erro ao")
        names = ", ".join(s.light_name for s in light_settings)
        return (
            f"Cena '{name}' criada (não aplicada). Lâmpadas: {names}. "
            "Use apply_config para aplicá-la."
        )

    # ----- desfazer (async) -----
    async def _undo_last_scene() -> str:
        history = services.history()
        if history is None:
            return unavailable(_UNDO_LABEL)
        try:
            result = await history.restore_last(controller)
        except SceneHistoryNotFoundError:
            return "Não há cena anterior para desfazer."
        except Exception as e:  # noqa: BLE001
            return unexpected_error("desfazer a última cena", e)
        # Mesmo helper da rota de histórico: limpa a "última cena" (#14).
        await clear_after_undo(services.last_applied(), result)
        return (
            f"Cena anterior restaurada ({result.get('restored_count', 0)} "
            f"lâmpada(s)). Origem do snapshot: {result.get('source', '?')}."
        )

    # ----- favoritos (async) -----
    async def _list_favorites() -> str:
        service = services.favorites()
        if service is None:
            return unavailable(_FAVORITES_LABEL)
        try:
            names = await service.list_existing()
        except Exception as e:  # noqa: BLE001
            return unexpected_error("listar favoritos", e)
        if not names:
            return "Nenhuma cena favorita ainda."
        return "Cenas favoritas: " + ", ".join(names)

    async def _current_favorites(service: Any) -> str:
        # Devolve a lista atualizada: o modelo pode chamar list_favorites em
        # paralelo no mesmo turno e ler o estado anterior à escrita.
        try:
            names = await service.list_existing()
        except Exception:  # noqa: BLE001
            return ""
        return "Favoritas agora: " + (", ".join(names) or "nenhuma") + "."

    async def _add_favorite(config_name: str) -> str:
        service = services.favorites()
        if service is None:
            return unavailable(_FAVORITES_LABEL)
        name, error = resolve_scene(manager, config_name)
        if name is None:
            return error or ""
        try:
            if name in await service.list_existing():
                return f"A cena '{name}' já era favorita."
            await service.add(name)
        except FavoriteConfigNotFoundError:
            return (
                f"A cena '{name}' não existe. Use list_configs para ver os nomes "
                "disponíveis."
            )
        except Exception as e:  # noqa: BLE001
            return unexpected_error(f"marcar '{name}' como favorita", e)
        return (
            f"Cena '{name}' marcada como favorita "
            "(aparece com estrela na tela Controle). "
            + await _current_favorites(service)
        )

    async def _remove_favorite(config_name: str) -> str:
        service = services.favorites()
        if service is None:
            return unavailable(_FAVORITES_LABEL)
        name, error = resolve_scene(manager, config_name)
        if name is None:
            return error or ""
        try:
            if name not in await service.list_existing():
                return f"A cena '{name}' não era favorita."
            await service.remove(name)
        except Exception as e:  # noqa: BLE001
            return unexpected_error(f"remover '{name}' dos favoritos", e)
        return f"Cena '{name}' removida dos favoritos. " + await _current_favorites(
            service
        )

    def favorites_ready() -> bool:
        return services.favorites() is not None

    return [
        StructuredTool.from_function(
            func=_search_configs,
            name="search_configs",
            description="Busca cenas por tema, mood, descrição, nome ou lâmpada.",
            args_schema=_SearchArgs,
        ),
        StructuredTool.from_function(
            func=_describe_config,
            name="describe_config",
            description="Mostra cor e brilho efetivo de cada lâmpada de uma cena.",
            args_schema=_DescribeArgs,
        ),
        StructuredTool.from_function(
            func=_create_config,
            name="create_config",
            description=(
                "Cria cena nova com as cores dadas por lâmpada, sem aplicar "
                "(para salvar o estado atual use save_current_config)."
            ),
            args_schema=_CreateConfigArgs,
        ),
        service_tool(
            name="undo_last_scene",
            description="Desfaz a última mudança de cena restaurando o estado anterior.",
            coroutine=_undo_last_scene,
            label=_UNDO_LABEL,
            is_available=lambda: services.history() is not None,
        ),
        service_tool(
            name="list_favorites",
            description="Lista as cenas favoritas (estrela na tela Controle).",
            coroutine=_list_favorites,
            label=_FAVORITES_LABEL,
            is_available=favorites_ready,
        ),
        service_tool(
            name="add_favorite",
            description="Marca uma cena existente como favorita. Idempotente.",
            coroutine=_add_favorite,
            label=_FAVORITES_LABEL,
            is_available=favorites_ready,
            args_schema=_FavoriteArgs,
        ),
        service_tool(
            name="remove_favorite",
            description="Remove uma cena dos favoritos. Idempotente.",
            coroutine=_remove_favorite,
            label=_FAVORITES_LABEL,
            is_available=favorites_ready,
            args_schema=_FavoriteArgs,
        ),
    ]
