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
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Protocol, Sequence

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from marvin_hue.controllers import HueController
from marvin_hue.basics import LightSetupsManager
from marvin_hue.colors import Color
from marvin_hue.eye_safety import is_enabled_for_app


_DEFAULT_LOCATIONS_PATH = ".res/light_physical_locations.json"
_DEFAULT_ROOM = "sem_sala"


class RoomIndex(Protocol):
    """Thin read-only view of room → light names (optional DI alternative)."""

    def rooms(self) -> Sequence[str]:
        """Distinct room labels."""
        ...

    def lights_in_room(self, room: str) -> Sequence[str]:
        """Light names in ``room`` (case-insensitive match preferred by caller)."""
        ...


def build_room_index_from_registry_rows(
    lights: Sequence[object],
) -> dict[str, list[str]]:
    """Build room_index from registry-like objects (name, room, enabled_for_app).

    Disabled lights are omitted. Empty/missing room → ``sem_sala``.
    """
    room_index: dict[str, list[str]] = {}
    for lt in lights:
        if not bool(getattr(lt, "enabled_for_app", True)):
            continue
        name = str(getattr(lt, "name", "") or "").strip()
        if not name:
            continue
        room_raw = getattr(lt, "room", None)
        room = (str(room_raw).strip() if room_raw is not None else "") or _DEFAULT_ROOM
        room_index.setdefault(room, []).append(name)
    return room_index


def _room_index_from_locations(path: str) -> dict[str, list[str]]:
    """Fallback when no registry snapshot: group by optional ``room`` or location."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    lights = data.get("lights", []) if isinstance(data, dict) else []
    room_index: dict[str, list[str]] = {}
    for light in lights:
        if not isinstance(light, dict):
            continue
        name = str(light.get("name", "") or "").strip()
        if not name:
            continue
        room_raw = light.get("room") or light.get("location") or _DEFAULT_ROOM
        room = str(room_raw).strip() or _DEFAULT_ROOM
        room_index.setdefault(room, []).append(name)
    return room_index


def _normalize_room_index(
    room_index: Mapping[str, Sequence[str]] | None,
    locations_path: str,
) -> dict[str, list[str]]:
    if room_index is not None:
        return {
            str(room): [str(n) for n in names]
            for room, names in room_index.items()
        }
    return _room_index_from_locations(locations_path)


def _match_room(rooms: Mapping[str, Sequence[str]], room: str) -> str | None:
    """Exact then case-insensitive room key match."""
    if room in rooms:
        return room
    lower = room.lower()
    for key in rooms:
        if key.lower() == lower:
            return key
    return None


def _enabled_names(names: Sequence[str]) -> list[str]:
    return [n for n in names if is_enabled_for_app(n)]


def build_light_tools(
    controller: HueController,
    manager: LightSetupsManager,
    locations_path: str = _DEFAULT_LOCATIONS_PATH,
    *,
    room_index: Mapping[str, Sequence[str]] | None = None,
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

    Returns:
        Lista de BaseTool prontas para create_agent (list/status/control + room tools).

    Note:
        Control tools rely on HueController skipping ``enabled_for_app=false`` lights.
        Room metadata is a build-time snapshot; registry room edits need agent rebuild.
    """
    rooms_map = _normalize_room_index(room_index, locations_path)

    # ----- schemas de argumentos (guiam o LLM) -----
    class _SetColorArgs(BaseModel):
        light_name: str = Field(description="Nome exato da lâmpada")
        red: int = Field(ge=0, le=255, description="Vermelho 0-255")
        green: int = Field(ge=0, le=255, description="Verde 0-255")
        blue: int = Field(ge=0, le=255, description="Azul 0-255")
        brightness: int = Field(default=200, ge=0, le=254, description="Brilho 0-254")

    class _ApplyConfigArgs(BaseModel):
        config_name: str = Field(description="Nome da configuração/preset de iluminação")
        transition_time: float = Field(default=0.0, ge=0, description="Transição (s)")

    class _ListConfigsArgs(BaseModel):
        search: str = Field(default="", description="Termo opcional para filtrar pelo nome")

    class _LightNameAllArgs(BaseModel):
        light_name: str = Field(default="all", description="Nome da lâmpada ou 'all' para todas")

    class _SetBrightnessArgs(BaseModel):
        light_name: str = Field(description="Nome da lâmpada ou 'all' para todas")
        brightness: int = Field(ge=0, le=100, description="Brilho em porcentagem (0-100)")

    class _SaveConfigArgs(BaseModel):
        # pattern ^\w+$ : letras (incl. acentuadas)/dígitos/underscore — rejeita
        # espaços e quebras de linha. Além de impor "sem espaços", fecha o vetor
        # de injeção de prompt via nome de preset reinjetado no system message.
        config_name: str = Field(
            pattern=r"^\w+$",
            description="Nome único, sem espaços (use underscores). Crie um nome "
            "criativo baseado nas cores atuais (ex: 'sunset_warm', 'natal_festivo')."
        )
        description: str = Field(
            description="Descrição de uma linha capturando o mood/ambiente das cores."
        )

    class _RoomArgs(BaseModel):
        room: str = Field(
            default="",
            description="Nome da sala. Vazio em list_lights_by_room lista salas e contagens.",
        )

    class _SetRoomPowerArgs(BaseModel):
        room: str = Field(description="Nome da sala")
        on: bool = Field(description="True para ligar, False para desligar")

    class _SetRoomBrightnessArgs(BaseModel):
        room: str = Field(description="Nome da sala")
        brightness: int = Field(ge=0, le=100, description="Brilho em porcentagem (0-100)")

    # ----- implementações (closures) -----
    def _list_lights() -> str:
        # Exclude disabled (enabled_for_app=false); controller also skips controls.
        names = _enabled_names(controller.list_lights())
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

    def _set_light_color(light_name: str, red: int, green: int, blue: int,
                         brightness: int = 200) -> str:
        # Clamp defensivo (alguns valores podem ser derivados/computados).
        # Disabled lights: controller raises ValueError (skip / block).
        red, green, blue = (max(0, min(255, v)) for v in (red, green, blue))
        brightness = max(0, min(254, brightness))
        try:
            controller.set_light_color(light_name, Color(red, green, blue, brightness))
            return f"Cor de '{light_name}' -> RGB({red},{green},{blue}) brilho {brightness}."
        except Exception as e:  # noqa: BLE001
            return f"Erro ao alterar '{light_name}': {e}"

    def _apply_config(config_name: str, transition_time: float = 0.0) -> str:
        config = manager.get_config(config_name)
        if not config:
            available = [c.name for c in manager.configs[:10]]
            return (
                f"Configuração '{config_name}' não encontrada. "
                f"Algumas disponíveis: {', '.join(available)}..."
            )
        try:
            # Controller skips disabled lights inside apply_light_config.
            controller.apply_light_config(config, transition_time)
            return f"Configuração '{config_name}' aplicada! Descrição: {config.description}"
        except Exception as e:  # noqa: BLE001
            return f"Erro ao aplicar '{config_name}': {e}"

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
            desc = (config.description[:60] + "...") if len(config.description) > 60 else config.description
            result_parts.append(f"- {config.name}: {desc}")
        if len(manager.configs) > 15:
            result_parts.append(f"\n(Mostrando 15 de {len(manager.configs)} configurações)")
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
        hue_brightness = max(0, min(254, int((pct / 100) * 254)))
        if light_name.lower() == "all":
            controller.set_all_brightness(hue_brightness)
            return f"Brilho de todas as lâmpadas ajustado para {pct}%."
        if controller.set_brightness(light_name, hue_brightness):
            return f"Brilho da lâmpada '{light_name}' ajustado para {pct}%."
        return f"Lâmpada '{light_name}' não encontrada."

    def _save_current_config(config_name: str, description: str) -> str:
        if manager.get_config(config_name):
            return (
                f"Já existe uma configuração com o nome '{config_name}'. "
                "Escolha outro nome ou delete a existente primeiro."
            )
        from marvin_hue.basics import LightSetting, LightConfig

        settings = []
        for light in controller.get_lights_status():
            name = str(light.get("name", ""))
            if not is_enabled_for_app(name):
                continue
            if light["on"] and light["reachable"]:
                c = light["color"]
                settings.append(
                    LightSetting(light["name"], Color(c["r"], c["g"], c["b"], light["brightness"]))
                )
        if not settings:
            return "Nenhuma lâmpada ligada encontrada. Ligue algumas lâmpadas primeiro."
        new_config = LightConfig(
            name=config_name, settings=settings,
            description=description or "Configuração salva pelo chat",
        )
        manager.configs.append(new_config)
        manager.save()
        names = ", ".join(s.light_name for s in settings)
        return (
            f"Configuração '{config_name}' salva com sucesso!\n"
            f"Descrição: {new_config.description}\nLâmpadas incluídas: {names}"
        )

    def _get_light_locations(light_name: str = "all") -> str:
        path = Path(locations_path)
        if not path.exists():
            return "Arquivo de localizações físicas não encontrado."
        # Try/except cobre TODA a leitura/parse/acesso (espelha _locations_block):
        # um JSON malformado/forma inesperada vira erro de tool, não exceção.
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            lights = data.get("lights", []) if isinstance(data, dict) else []
            if light_name.lower() == "all":
                parts = ["Localizações físicas das lâmpadas:"]
                for light in lights:
                    if "name" not in light or "location" not in light:
                        continue
                    if not is_enabled_for_app(str(light["name"])):
                        continue
                    info = f"\n• {light['name']}: {light['location']}"
                    if "max_brightness_percent" in light:
                        info += f"\n  ⚠️ Intensidade máxima recomendada: {light['max_brightness_percent']}%"
                    if light.get("notes"):
                        info += f"\n  📝 {light['notes']}"
                    if "recommendations" in light:
                        info += "\n  💡 Recomendações:" + "".join(f"\n     - {r}" for r in light["recommendations"])
                    parts.append(info)
                env = data.get("environment_info", {})
                if "considerations" in env:
                    parts.append("\n⚙️ Considerações importantes:")
                    parts.extend(f"  • {c}" for c in env["considerations"])
                return "\n".join(parts)
            for light in lights:
                if light.get("name", "").lower() == light_name.lower():
                    if not is_enabled_for_app(str(light.get("name", ""))):
                        return f"Lâmpada '{light_name}' desabilitada no app."
                    info = f"Lâmpada '{light['name']}':\n• Localização: {light.get('location', '?')}"
                    if "max_brightness_percent" in light:
                        info += f"\n• ⚠️ Intensidade máxima recomendada: {light['max_brightness_percent']}%"
                    if light.get("notes"):
                        info += f"\n• Observação: {light['notes']}"
                    if "recommendations" in light:
                        info += "\n• Recomendações:" + "".join(f"\n  - {r}" for r in light["recommendations"])
                    return info
        except Exception as e:  # noqa: BLE001
            return f"Erro ao ler arquivo de localizações: {e}"
        return f"Lâmpada '{light_name}' não encontrada no arquivo de localizações."

    def _get_rooms() -> str:
        if not rooms_map:
            return (
                "Nenhuma sala no índice (registry vazio ou localizações indisponíveis). "
                "Sincronize o registry ou configure room_index no agente."
            )
        parts = ["Salas (registry / room_index):"]
        for room in sorted(rooms_map.keys(), key=str.lower):
            enabled = _enabled_names(rooms_map[room])
            parts.append(f"- {room}: {len(enabled)} lâmpada(s)")
        return "\n".join(parts)

    def _list_lights_by_room(room: str = "") -> str:
        if not rooms_map:
            return (
                "Nenhuma sala no índice. Use get_rooms após carregar o registry "
                "ou confira light_physical_locations.json."
            )
        room = (room or "").strip()
        if not room:
            parts = ["Salas e contagens:"]
            for r in sorted(rooms_map.keys(), key=str.lower):
                n = len(_enabled_names(rooms_map[r]))
                parts.append(f"- {r}: {n} lâmpada(s)")
            return "\n".join(parts)
        key = _match_room(rooms_map, room)
        if key is None:
            available = ", ".join(sorted(rooms_map.keys(), key=str.lower)) or "(nenhuma)"
            return f"Sala '{room}' não encontrada. Salas: {available}"
        names = _enabled_names(rooms_map[key])
        if not names:
            return f"Sala '{key}' sem lâmpadas habilitadas."
        return f"Lâmpadas em '{key}': {', '.join(names)}"

    def _set_room_power(room: str, on: bool) -> str:
        key = _match_room(rooms_map, (room or "").strip())
        if key is None:
            available = ", ".join(sorted(rooms_map.keys(), key=str.lower)) or "(nenhuma)"
            return f"Sala '{room}' não encontrada. Salas: {available}"
        names = _enabled_names(rooms_map[key])
        if not names:
            return f"Sala '{key}' sem lâmpadas habilitadas."
        ok: list[str] = []
        failed: list[str] = []
        for name in names:
            # Controller returns False for missing/disabled.
            success = controller.turn_on(name) if on else controller.turn_off(name)
            (ok if success else failed).append(name)
        action = "ligadas" if on else "desligadas"
        msg = f"Sala '{key}': {len(ok)} lâmpada(s) {action}."
        if failed:
            msg += f" Falha/skip: {', '.join(failed)}."
        return msg

    def _set_room_brightness(room: str, brightness: int) -> str:
        key = _match_room(rooms_map, (room or "").strip())
        if key is None:
            available = ", ".join(sorted(rooms_map.keys(), key=str.lower)) or "(nenhuma)"
            return f"Sala '{room}' não encontrada. Salas: {available}"
        names = _enabled_names(rooms_map[key])
        if not names:
            return f"Sala '{key}' sem lâmpadas habilitadas."
        pct = max(0, min(100, brightness))
        hue_brightness = max(0, min(254, int((pct / 100) * 254)))
        ok: list[str] = []
        failed: list[str] = []
        for name in names:
            # Controller applies eye-safety clamp and skips disabled.
            if controller.set_brightness(name, hue_brightness):
                ok.append(name)
            else:
                failed.append(name)
        msg = f"Sala '{key}': brilho {pct}% em {len(ok)} lâmpada(s)."
        if failed:
            msg += f" Falha/skip: {', '.join(failed)}."
        return msg

    # ----- montagem das StructuredTools -----
    return [
        StructuredTool.from_function(
            func=_list_lights, name="list_lights",
            description=(
                "Lista lâmpadas habilitadas no app (exclui enabled_for_app=false). "
                "Controles no controller também ignoram desabilitadas."
            ),
        ),
        StructuredTool.from_function(
            func=_get_light_status, name="get_light_status",
            description="Status atual das lâmpadas habilitadas (estado, cor, brilho).",
        ),
        StructuredTool.from_function(
            func=_set_light_color, name="set_light_color",
            description=(
                "Define cor RGB e brilho de UMA lâmpada. "
                "Lâmpadas desabilitadas no app são rejeitadas pelo controller."
            ),
            args_schema=_SetColorArgs,
        ),
        StructuredTool.from_function(
            func=_apply_config, name="apply_config",
            description=(
                "Aplica uma configuração/preset de iluminação predefinida. "
                "Lâmpadas desabilitadas no preset são ignoradas pelo controller."
            ),
            args_schema=_ApplyConfigArgs,
        ),
        StructuredTool.from_function(
            func=_list_configs, name="list_configs",
            description="Lista os presets de iluminação disponíveis (filtro opcional).",
            args_schema=_ListConfigsArgs,
        ),
        StructuredTool.from_function(
            func=_turn_off_lights, name="turn_off_lights",
            description=(
                "Desliga uma lâmpada específica ou todas ('all'). "
                "Desabilitadas são ignoradas pelo controller."
            ),
            args_schema=_LightNameAllArgs,
        ),
        StructuredTool.from_function(
            func=_turn_on_lights, name="turn_on_lights",
            description=(
                "Liga uma lâmpada específica ou todas ('all'). "
                "Desabilitadas são ignoradas pelo controller."
            ),
            args_schema=_LightNameAllArgs,
        ),
        StructuredTool.from_function(
            func=_set_brightness, name="set_brightness",
            description=(
                "Ajusta o brilho (0-100%) de uma lâmpada ou de todas ('all'). "
                "Desabilitadas são ignoradas; eye-safety clampa no controller."
            ),
            args_schema=_SetBrightnessArgs,
        ),
        StructuredTool.from_function(
            func=_save_current_config, name="save_current_config",
            description="Salva o estado atual das lâmpadas habilitadas como um novo preset.",
            args_schema=_SaveConfigArgs,
        ),
        StructuredTool.from_function(
            func=_get_light_locations, name="get_light_locations",
            description="Localização física das lâmpadas e restrições de intensidade.",
            args_schema=_LightNameAllArgs,
        ),
        StructuredTool.from_function(
            func=_get_rooms, name="get_rooms",
            description="Lista salas distintas do registry (room_index) com contagem de lâmpadas.",
        ),
        StructuredTool.from_function(
            func=_list_lights_by_room, name="list_lights_by_room",
            description=(
                "Lista lâmpadas por sala. room vazio → salas e contagens; "
                "room preenchido → nomes habilitados na sala."
            ),
            args_schema=_RoomArgs,
        ),
        StructuredTool.from_function(
            func=_set_room_power, name="set_room_power",
            description=(
                "Liga ou desliga todas as lâmpadas habilitadas de uma sala. "
                "Desabilitadas são ignoradas pelo controller."
            ),
            args_schema=_SetRoomPowerArgs,
        ),
        StructuredTool.from_function(
            func=_set_room_brightness, name="set_room_brightness",
            description=(
                "Ajusta brilho (0-100%) de todas as lâmpadas habilitadas de uma sala. "
                "Eye-safety e skip de desabilitadas via controller."
            ),
            args_schema=_SetRoomBrightnessArgs,
        ),
    ]
