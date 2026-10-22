"""
Light Tools - Ferramentas para controle de lâmpadas Philips Hue.

Define a factory ``build_light_tools(controller, manager, *, room_index=...)``
que cria as tools do agente como closures (sem estado global), usando SOMENTE
a API pública do HueController.

Registry / rooms
----------------
``room_index`` is a **sync snapshot** ``{room_label: [light_name, ...]}`` built
at agent construction (lifespan / reconfigure) from the light registry.
Tools stay synchronous; room metadata changes require agent rebuild.

Disabled lights (``enabled_for_app=false``)
-------------------------------------------
- Listing tools exclude lights marked disabled via ``is_enabled_for_app``.
- Control tools call HueController, which already **skips** disabled lights
  (set_light_color raises; turn_on/off/set_brightness return False;
  apply_light_config / set_all skip). Room batch tools skip them too.

"Desligar tudo" (``turn_off_lights("all")``)
--------------------------------------------
The async path uses ``LightsOffService`` (stop mirror, idempotent snapshot,
one bridge read), like ``POST /lights/off``. The sync path (CLI) keeps the
plain ``controller.set_all(False)``. Single-light turn-off is unchanged.

Last applied scene (``apply_config``)
-------------------------------------
The ``coroutine`` delegates to ``ApplyConfigService`` (source ``"chat"``): it
takes the "before apply" snapshot (so undo works) and records the last applied
scene when at least one light applied. History and the last-applied service
come lazily from ``ChatServices`` and fail open. The sync ``func`` talks to the
controller only (no event-loop-bound services).

Favorites, scenes, groups, schedules, mirror and health tools live in
``scene_tools`` / ``automation_tools`` / ``system_tools`` (see
``build_all_tools`` in ``marvin_hue.chat.tools``).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from marvin_hue.apply_result import ApplyResult
from marvin_hue.basics import (
    DuplicateConfigError,
    LightSetupsManager,
    ReservedConfigNameError,
    is_reserved_config_name,
)
from marvin_hue.chat.services import ChatServices
from marvin_hue.chat.tools._common import (
    SINGLE_LINE,
    pct_to_hue,
    reserved_scene_name,
    unexpected_error,
)
from marvin_hue.chat.tools.rooms import (
    DEFAULT_LOCATIONS_PATH,
    RegistryLocation,
    enabled_names,
    match_rooms,
    normalize_room_index,
    resolve_room_lights,
    room_list,
)
from marvin_hue.colors import Color
from marvin_hue.controllers import HueController
from marvin_hue.eye_safety import is_enabled_for_app
from marvin_hue.services.apply_config import (
    ApplyConfigNotFoundError,
    ApplyConfigService,
)
from marvin_hue.services.last_applied_scene import SOURCE_CHAT
from marvin_hue.services.lights_off import LightsOffBridgeError

__all__ = ["build_light_tools"]


def _registry_location_lines(loc: RegistryLocation, *, heading: bool) -> str:
    if heading:
        lines = [f"Lâmpada '{loc.name}':", f"• Localização: {loc.room}"]
        if loc.eye_safety_limit_pct is not None:
            lines.append(
                f"• ⚠️ Intensidade máxima recomendada: {loc.eye_safety_limit_pct}%"
            )
        if loc.notes:
            lines.append(f"• Observação: {loc.notes}")
        return "\n".join(lines)
    info = f"\n• {loc.name}: {loc.room}"
    if loc.eye_safety_limit_pct is not None:
        info += f"\n  ⚠️ Intensidade máxima recomendada: {loc.eye_safety_limit_pct}%"
    if loc.notes:
        info += f"\n  📝 {loc.notes}"
    return info


def _format_registry_locations(
    locations: Sequence[RegistryLocation], light_name: str
) -> str:
    enabled = [loc for loc in locations if loc.name and is_enabled_for_app(loc.name)]
    if light_name.lower() == "all":
        if not enabled:
            return "Nenhuma lâmpada habilitada no registry."
        parts = ["Localizações físicas das lâmpadas:"]
        parts.extend(_registry_location_lines(loc, heading=False) for loc in enabled)
        return "\n".join(parts)
    target = light_name.lower()
    for loc in locations:
        if loc.name.lower() != target:
            continue
        if not is_enabled_for_app(loc.name):
            return f"Lâmpada '{light_name}' desabilitada no app."
        return _registry_location_lines(loc, heading=True)
    return f"Lâmpada '{light_name}' não encontrada no registry."


def _json_max_brightness_line(light: dict[str, object], *, heading: bool) -> str:
    if "max_brightness_percent" not in light:
        return ""
    prefix = "• " if heading else "  "
    return (
        f"\n{prefix}⚠️ Intensidade máxima recomendada: "
        f"{light['max_brightness_percent']}%"
    )


def _json_light_all_line(light: object) -> str | None:
    if not isinstance(light, dict) or "name" not in light or "location" not in light:
        return None
    if not is_enabled_for_app(str(light["name"])):
        return None
    info = f"\n• {light['name']}: {light['location']}"
    info += _json_max_brightness_line(light, heading=False)
    if light.get("notes"):
        info += f"\n  📝 {light['notes']}"
    recs = light.get("recommendations")
    if isinstance(recs, list):
        info += "\n  💡 Recomendações:" + "".join(f"\n     - {r}" for r in recs)
    return info


def _json_light_one(light: object, light_name: str) -> str | None:
    if not isinstance(light, dict):
        return None
    if str(light.get("name", "")).lower() != light_name.lower():
        return None
    if not is_enabled_for_app(str(light.get("name", ""))):
        return f"Lâmpada '{light_name}' desabilitada no app."
    info = f"Lâmpada '{light['name']}':\n• Localização: {light.get('location', '?')}"
    info += _json_max_brightness_line(light, heading=True)
    if light.get("notes"):
        info += f"\n• Observação: {light['notes']}"
    recs = light.get("recommendations")
    if isinstance(recs, list):
        info += "\n• Recomendações:" + "".join(f"\n  - {r}" for r in recs)
    return info


def _format_json_locations(locations_path: str, light_name: str) -> str:
    path = Path(locations_path)
    if not path.exists():
        return "Arquivo de localizações físicas não encontrado."
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        lights = data.get("lights", []) if isinstance(data, dict) else []
        if light_name.lower() == "all":
            parts = ["Localizações físicas das lâmpadas:"]
            parts.extend(
                line
                for light in lights
                if (line := _json_light_all_line(light)) is not None
            )
            env = data.get("environment_info", {}) if isinstance(data, dict) else {}
            if isinstance(env, dict) and "considerations" in env:
                parts.append("\n⚙️ Considerações importantes:")
                parts.extend(f"  • {c}" for c in env["considerations"])
            return "\n".join(parts)
        for light in lights:
            one = _json_light_one(light, light_name)
            if one is not None:
                return one
    except Exception as e:  # noqa: BLE001
        return f"Erro ao ler arquivo de localizações: {e}"
    return f"Lâmpada '{light_name}' não encontrada no arquivo de localizações."


def build_light_tools(
    controller: HueController,
    manager: LightSetupsManager,
    locations_path: str = DEFAULT_LOCATIONS_PATH,
    *,
    room_index: Mapping[str, Sequence[str]] | None = None,
    services: ChatServices | None = None,
) -> list[BaseTool]:
    """Cria as tools de iluminação com closures (sem estado global).

    Args:
        controller: HueController (usa SOMENTE métodos públicos).
        manager: LightSetupsManager.
        locations_path: caminho do JSON de localizações físicas (injetável p/ testes).
        room_index: optional room → light names snapshot (registry at agent build).
            If None, falls back to grouping physical locations JSON by room/location.
            Disabled lights should already be omitted when built from the registry;
            listing still re-checks ``is_enabled_for_app`` at call time.
        services: providers dos serviços do app (``ChatServices``); usado por
            ``turn_off_lights("all")`` no caminho async. None → padrão.

    Returns:
        Lista de BaseTool prontas para create_agent (list/status/control + room tools).

    Note:
        Control tools rely on HueController skipping ``enabled_for_app=false`` lights.
        Room metadata is a build-time snapshot; registry room edits need agent rebuild.
    """
    rooms_map = normalize_room_index(room_index, locations_path)
    chat_services = services or ChatServices()

    # ----- schemas de argumentos (guiam o LLM) -----
    class _SetColorArgs(BaseModel):
        light_name: str = Field(description="Nome exato da lâmpada")
        red: int = Field(ge=0, le=255, description="Vermelho 0-255")
        green: int = Field(ge=0, le=255, description="Verde 0-255")
        blue: int = Field(ge=0, le=255, description="Azul 0-255")
        brightness: int = Field(default=200, ge=0, le=254, description="Brilho 0-254")

    class _ApplyConfigArgs(BaseModel):
        config_name: str = Field(
            description="Nome da configuração/preset de iluminação"
        )
        transition_time: float = Field(default=0.0, ge=0, description="Transição (s)")

    class _ListConfigsArgs(BaseModel):
        search: str = Field(
            default="",
            max_length=100,
            description="Filtro opcional só pelo NOME (tema/mood: search_configs)",
        )

    class _LightNameAllArgs(BaseModel):
        light_name: str = Field(
            default="all", description="Nome da lâmpada ou 'all' para todas"
        )

    class _SetBrightnessArgs(BaseModel):
        light_name: str = Field(description="Nome da lâmpada ou 'all' para todas")
        brightness: int = Field(
            ge=0, le=100, description="Brilho em porcentagem (0-100)"
        )

    class _SaveConfigArgs(BaseModel):
        # pattern ^\w+$ : letras (incl. acentuadas)/dígitos/underscore — rejeita
        # espaços e quebras de linha. Além de impor "sem espaços", fecha o vetor
        # de injeção de prompt via nome de preset reinjetado no system message.
        config_name: str = Field(
            pattern=r"^\w+$",
            max_length=64,
            description="Nome único, sem espaços (use underscores). Crie um nome "
            "criativo baseado nas cores atuais (ex: 'sunset_warm', 'natal_festivo').",
        )
        description: str = Field(
            max_length=200,
            pattern=SINGLE_LINE,
            description="Descrição de uma linha capturando o mood/ambiente das cores.",
        )

    class _RoomArgs(BaseModel):
        room: str = Field(
            default="",
            max_length=100,
            description="Sala ou parte do nome (ex.: 'teto'). Vazio lista salas e contagens.",
        )

    class _SetRoomPowerArgs(BaseModel):
        room: str = Field(max_length=100, description="Sala ou parte do nome (ex.: 'teto')")
        on: bool = Field(description="True para ligar, False para desligar")

    class _SetRoomBrightnessArgs(BaseModel):
        room: str = Field(max_length=100, description="Sala ou parte do nome (ex.: 'teto')")
        brightness: int = Field(
            ge=0, le=100, description="Brilho em porcentagem (0-100)"
        )

    # ----- implementações (closures) -----
    def _list_lights() -> str:
        # Exclude disabled (enabled_for_app=false); controller also skips controls.
        names = enabled_names(controller.list_lights())
        if not names:
            return "Nenhuma lâmpada habilitada disponível."
        return f"Lâmpadas disponíveis: {', '.join(names)}"

    def _get_light_status() -> str:
        result_parts = ["Status das lâmpadas:"]
        any_row = False
        for light in controller.get_lights_status():
            name = light.get("name", "")
            if not is_enabled_for_app(str(name)):
                continue
            any_row = True
            state = "Ligada" if light["on"] else "Desligada"
            color = light["color"]
            rgb_str = f"RGB({color['r']}, {color['g']}, {color['b']})"
            brightness = int((light["brightness"] / 254) * 100)
            reachable = "Sim" if light["reachable"] else "Não"
            result_parts.append(
                f"- {light['name']}: {state}, Cor: {rgb_str}, "
                f"Brilho: {brightness}%, Acessível: {reachable}"
            )
        if not any_row:
            return "Nenhuma lâmpada habilitada com status disponível."
        return "\n".join(result_parts)

    def _set_light_color(
        light_name: str, red: int, green: int, blue: int, brightness: int = 200
    ) -> str:
        # Clamp defensivo (alguns valores podem ser derivados/computados).
        # Disabled lights: controller raises ValueError (skip / block).
        red, green, blue = (max(0, min(255, v)) for v in (red, green, blue))
        brightness = max(0, min(254, brightness))
        try:
            controller.set_light_color(light_name, Color(red, green, blue, brightness))
            return f"Cor de '{light_name}' -> RGB({red},{green},{blue}) brilho {brightness}."
        except Exception as e:  # noqa: BLE001
            return f"Erro ao alterar '{light_name}': {e}"

    def _apply_not_found(config_name: str) -> str:
        available = [c.name for c in manager.configs[:10]]
        return (
            f"Configuração '{config_name}' não encontrada. "
            f"Algumas disponíveis: {', '.join(available)}..."
        )

    def _apply_message(config_name: str, description: str, result: ApplyResult) -> str:
        if result.ok:
            return f"Configuração '{config_name}' aplicada! Descrição: {description}"
        failed_txt = ", ".join(f"{name} ({err})" for name, err in result.failed)
        if result.partial:
            applied_txt = ", ".join(result.applied)
            return (
                f"Configuração '{config_name}' aplicada parcialmente. "
                f"Aplicadas: {applied_txt}. Falhas: {failed_txt}."
            )
        return (
            f"Falha ao aplicar configuração '{config_name}'. "
            f"Nenhuma lâmpada aplicada. Falhas: {failed_txt}."
        )

    def _apply_config(config_name: str, transition_time: float = 0.0) -> str:
        # Sync path: never drives the event-loop-bound services (no snapshot,
        # no last-applied record).
        config = manager.get_config(config_name)
        if not config:
            return _apply_not_found(config_name)
        try:
            # Controller skips disabled lights inside apply_light_config.
            result = controller.apply_light_config(config, transition_time)
        except Exception as e:  # noqa: BLE001
            return f"Erro ao aplicar '{config_name}': {e}"
        return _apply_message(config_name, config.description, result)

    async def _apply_config_async(
        config_name: str, transition_time: float = 0.0
    ) -> str:
        # Same use case as POST /apply: "before apply" snapshot (so undo works)
        # and the last-applied record (>=1 light applied), both best-effort.
        config = manager.get_config(config_name)
        if not config:
            return _apply_not_found(config_name)
        service = ApplyConfigService(
            manager,
            controller,
            chat_services.history(),
            last_applied=chat_services.last_applied(),
        )
        try:
            result = await service.apply(
                config_name, transition_time=transition_time, source=SOURCE_CHAT
            )
        except ApplyConfigNotFoundError:
            return _apply_not_found(config_name)
        except Exception as e:  # noqa: BLE001
            return f"Erro ao aplicar '{config_name}': {e}"
        return _apply_message(config_name, config.description, result)

    def _list_configs(search: str = "") -> str:
        configs = manager.configs
        if search:
            s = search.lower()
            configs = [c for c in configs if s in c.name.lower()]
        if not configs:
            return f"Nenhuma configuração encontrada com o termo '{search}'."
        shown = sorted(configs, key=lambda c: c.name)[:15]
        result_parts = ["Configurações disponíveis:"]
        for config in shown:
            desc = (
                (config.description[:60] + "...")
                if len(config.description) > 60
                else config.description
            )
            result_parts.append(f"- {config.name}: {desc}")
        if len(manager.configs) > 15:
            result_parts.append(
                f"\n(Mostrando 15 de {len(manager.configs)} configurações)"
            )
        return "\n".join(result_parts)

    def _turn_off_lights(light_name: str = "all") -> str:
        # Controller skips disabled (turn_off → False; set_all skips).
        if light_name.lower() == "all":
            controller.set_all(False)
            return "Todas as lâmpadas foram desligadas."
        if controller.turn_off(light_name):
            return f"Lâmpada '{light_name}' foi desligada."
        return f"Lâmpada '{light_name}' não encontrada."

    def _turn_on_lights(light_name: str = "all") -> str:
        if light_name.lower() == "all":
            controller.set_all(True)
            return "Todas as lâmpadas foram ligadas."
        if controller.turn_on(light_name):
            return f"Lâmpada '{light_name}' foi ligada."
        return f"Lâmpada '{light_name}' não encontrada."

    def _set_brightness(light_name: str, brightness: int) -> str:
        pct = max(0, min(100, brightness))
        hue_brightness = pct_to_hue(pct)
        if light_name.lower() == "all":
            controller.set_all_brightness(hue_brightness)
            return f"Brilho de todas as lâmpadas ajustado para {pct}%."
        if controller.set_brightness(light_name, hue_brightness):
            return f"Brilho da lâmpada '{light_name}' ajustado para {pct}%."
        return f"Lâmpada '{light_name}' não encontrada."

    def _save_current_config(config_name: str, description: str) -> str:
        duplicate = (
            "Já existe uma configuração com o nome '{name}'. "
            "Escolha outro nome ou delete a existente primeiro."
        )
        if is_reserved_config_name(config_name):
            return reserved_scene_name(config_name)
        if manager.get_config(config_name):
            return duplicate.format(name=config_name)
        from marvin_hue.basics import LightSetting, LightConfig

        settings = []
        for light in controller.get_lights_status():
            name = str(light.get("name", ""))
            if not is_enabled_for_app(name):
                continue
            if light["on"] and light["reachable"]:
                c = light["color"]
                settings.append(
                    LightSetting(
                        light["name"],
                        Color(c["r"], c["g"], c["b"], light["brightness"]),
                    )
                )
        if not settings:
            return "Nenhuma lâmpada ligada encontrada. Ligue algumas lâmpadas primeiro."
        new_config = LightConfig(
            name=config_name,
            settings=settings,
            description=description or "Configuração salva pelo chat",
        )
        try:
            manager.add_config(new_config)
        except ReservedConfigNameError:
            return reserved_scene_name(config_name)
        except DuplicateConfigError:
            return duplicate.format(name=config_name)
        except Exception as e:  # noqa: BLE001
            return unexpected_error(f"salvar a cena '{config_name}'", e, verb="Erro ao")
        names = ", ".join(s.light_name for s in settings)
        return (
            f"Configuração '{config_name}' salva com sucesso!\n"
            f"Descrição: {new_config.description}\nLâmpadas incluídas: {names}"
        )

    def _get_light_locations(light_name: str = "all") -> str:
        # Prefer registry snapshot carried on room_index; JSON only if None.
        registry_locations = getattr(rooms_map, "locations", None)
        if registry_locations is not None:
            return _format_registry_locations(registry_locations, light_name)
        return _format_json_locations(locations_path, light_name)

    def _get_rooms() -> str:
        if not rooms_map:
            return (
                "Nenhuma sala no índice (registry vazio ou localizações indisponíveis). "
                "Sincronize o registry ou configure room_index no agente."
            )
        parts = ["Salas (registry / room_index):"]
        for room in sorted(rooms_map.keys(), key=str.lower):
            enabled = enabled_names(rooms_map[room])
            parts.append(f"- {room}: {len(enabled)} lâmpada(s)")
        return "\n".join(parts)

    def _room_counts(title: str) -> str:
        parts = [title]
        for r in sorted(rooms_map.keys(), key=str.lower):
            parts.append(f"- {r}: {len(enabled_names(rooms_map[r]))} lâmpada(s)")
        return "\n".join(parts)

    def _room_not_found(room: str) -> str:
        return f"Sala '{room}' não encontrada. Salas: {room_list(rooms_map)}"

    def _list_lights_by_room(room: str = "") -> str:
        if not rooms_map:
            return (
                "Nenhuma sala no índice. Use get_rooms após carregar o registry "
                "ou confira light_physical_locations.json."
            )
        room = (room or "").strip()
        if not room:
            return _room_counts("Salas e contagens:")
        keys = match_rooms(rooms_map, room)
        if not keys:
            return _room_not_found(room)
        lines = []
        for key in keys:
            names = enabled_names(rooms_map[key])
            if names:
                lines.append(f"Lâmpadas em '{key}': {', '.join(names)}")
            else:
                lines.append(f"Sala '{key}' sem lâmpadas habilitadas.")
        return "\n".join(lines)

    def _room_targets(room: str) -> tuple[str, list[str]] | str:
        resolved = resolve_room_lights(rooms_map, (room or "").strip())
        if resolved is None:
            return _room_not_found(room)
        label, names = resolved
        label = label[0].upper() + label[1:]
        if not names:
            return f"{label} sem lâmpadas habilitadas."
        return label, names

    def _set_room_power(room: str, on: bool) -> str:
        targets = _room_targets(room)
        if isinstance(targets, str):
            return targets
        label, names = targets
        ok: list[str] = []
        failed: list[str] = []
        for name in names:
            # Controller returns False for missing/disabled.
            success = controller.turn_on(name) if on else controller.turn_off(name)
            (ok if success else failed).append(name)
        action = "ligadas" if on else "desligadas"
        msg = f"{label}: {len(ok)} lâmpada(s) {action}."
        if failed:
            msg += f" Falha/skip: {', '.join(failed)}."
        return msg

    def _set_room_brightness(room: str, brightness: int) -> str:
        targets = _room_targets(room)
        if isinstance(targets, str):
            return targets
        label, names = targets
        pct = max(0, min(100, brightness))
        hue_brightness = pct_to_hue(pct)
        ok: list[str] = []
        failed: list[str] = []
        for name in names:
            # Controller applies eye-safety clamp and skips disabled.
            if controller.set_brightness(name, hue_brightness):
                ok.append(name)
            else:
                failed.append(name)
        msg = f"{label}: brilho {pct}% em {len(ok)} lâmpada(s)."
        if failed:
            msg += f" Falha/skip: {', '.join(failed)}."
        return msg

    async def _turn_off_lights_async(light_name: str = "all") -> str:
        if light_name.lower() != "all":
            return await asyncio.to_thread(_turn_off_lights, light_name)
        service = chat_services.lights_off(controller)
        if service is None:
            return await asyncio.to_thread(_turn_off_lights, light_name)
        try:
            result = await service.turn_off_all()
        except LightsOffBridgeError:
            return "Não consegui ler a bridge para desligar as lâmpadas (bridge inacessível)."
        except Exception as e:  # noqa: BLE001
            return unexpected_error("desligar as lâmpadas", e)
        msg = f"Todas as lâmpadas foram desligadas ({len(result.applied)})."
        if result.failed:
            failed_txt = ", ".join(f"{name} ({err})" for name, err in result.failed)
            msg += f" Falhas: {failed_txt}."
        return msg

    # ----- montagem das StructuredTools -----
    return [
        StructuredTool.from_function(
            func=_list_lights,
            name="list_lights",
            description=(
                "Lista lâmpadas habilitadas no app (exclui enabled_for_app=false). "
                "Controles no controller também ignoram desabilitadas."
            ),
        ),
        StructuredTool.from_function(
            func=_get_light_status,
            name="get_light_status",
            description="Status atual das lâmpadas habilitadas (estado, cor, brilho).",
        ),
        StructuredTool.from_function(
            func=_set_light_color,
            name="set_light_color",
            description=(
                "Define cor RGB e brilho de UMA lâmpada. "
                "Lâmpadas desabilitadas no app são rejeitadas pelo controller."
            ),
            args_schema=_SetColorArgs,
        ),
        StructuredTool.from_function(
            func=_apply_config,
            coroutine=_apply_config_async,
            name="apply_config",
            description=(
                "Aplica uma cena/preset salvo em todas as lâmpadas dela "
                "(para só um grupo use apply_config_to_group)."
            ),
            args_schema=_ApplyConfigArgs,
        ),
        StructuredTool.from_function(
            func=_list_configs,
            name="list_configs",
            description=(
                "Lista os presets pelo nome (filtro só no nome). Para buscar por "
                "tema, mood ou descrição use search_configs."
            ),
            args_schema=_ListConfigsArgs,
        ),
        StructuredTool.from_function(
            func=_turn_off_lights,
            coroutine=_turn_off_lights_async,
            name="turn_off_lights",
            description=(
                "Desliga uma lâmpada específica ou todas ('all'). "
                "Desabilitadas são ignoradas pelo controller."
            ),
            args_schema=_LightNameAllArgs,
        ),
        StructuredTool.from_function(
            func=_turn_on_lights,
            name="turn_on_lights",
            description=(
                "Liga uma lâmpada específica ou todas ('all'). "
                "Desabilitadas são ignoradas pelo controller."
            ),
            args_schema=_LightNameAllArgs,
        ),
        StructuredTool.from_function(
            func=_set_brightness,
            name="set_brightness",
            description=(
                "Ajusta o brilho (0-100%) de uma lâmpada ou de todas ('all'). "
                "Desabilitadas são ignoradas; eye-safety clampa no controller."
            ),
            args_schema=_SetBrightnessArgs,
        ),
        StructuredTool.from_function(
            func=_save_current_config,
            name="save_current_config",
            description=(
                "Salva o estado ATUAL das lâmpadas como nova cena (para definir "
                "cores sem aplicar use create_config)."
            ),
            args_schema=_SaveConfigArgs,
        ),
        StructuredTool.from_function(
            func=_get_light_locations,
            name="get_light_locations",
            description="Localização física das lâmpadas e restrições de intensidade.",
            args_schema=_LightNameAllArgs,
        ),
        StructuredTool.from_function(
            func=_get_rooms,
            name="get_rooms",
            description="Lista as salas (locais físicos, não grupos) com contagem de lâmpadas.",
        ),
        StructuredTool.from_function(
            func=_list_lights_by_room,
            name="list_lights_by_room",
            description=(
                "Lista lâmpadas por sala. room vazio → salas e contagens; "
                "room preenchido → nomes habilitados na sala."
            ),
            args_schema=_RoomArgs,
        ),
        StructuredTool.from_function(
            func=_set_room_power,
            name="set_room_power",
            description=(
                "Liga ou desliga as lâmpadas de uma sala ou local (ex.: 'teto'); "
                "salas não são grupos."
            ),
            args_schema=_SetRoomPowerArgs,
        ),
        StructuredTool.from_function(
            func=_set_room_brightness,
            name="set_room_brightness",
            description=(
                "Ajusta o brilho (0-100%) das lâmpadas de uma sala ou local "
                "(ex.: 'teto'); salas não são grupos."
            ),
            args_schema=_SetRoomBrightnessArgs,
        ),
    ]
