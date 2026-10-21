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

Favorites (``list_favorites`` / ``add_favorite`` / ``remove_favorite``)
-----------------------------------------------------------------------
``SceneFavoritesService`` is async and owns one aiosqlite connection plus an
``asyncio.Lock`` bound to the FastAPI event loop. The tools therefore do the
real work only in their ``coroutine`` (used by ``ainvoke``/``astream``, i.e.
REST and WebSocket chat). The sync ``func`` never drives the service from a
second event loop (that would be a cross-loop use of the lock/connection); it
returns a clear message instead. The service is resolved lazily on each call
through ``favorites_provider`` and the tools fail open: no service → message,
never an exception.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from marvin_hue.basics import LightSetupsManager
from marvin_hue.colors import Color
from marvin_hue.controllers import HueController
from marvin_hue.eye_safety import is_enabled_for_app
from marvin_hue.services.scene_favorites import FavoriteConfigNotFoundError

if TYPE_CHECKING:
    from marvin_hue.services.scene_favorites import SceneFavoritesService


_DEFAULT_LOCATIONS_PATH = ".res/light_physical_locations.json"
_DEFAULT_ROOM = "sem_sala"

FavoritesProvider = Callable[[], "SceneFavoritesService | None"]

_FAVORITES_UNAVAILABLE = (
    "Favoritos indisponíveis no momento (serviço de favoritos não inicializado)."
)
_FAVORITES_SYNC_ONLY = (
    "Favoritos só podem ser consultados ou alterados pelo chat do servidor "
    "(web/API), que roda no contexto assíncrono do app."
)


def default_favorites_provider() -> "SceneFavoritesService | None":
    """Resolve o SceneFavoritesService registrado no lifespan (ou None).

    Import tardio: evita ciclo chat → api no import do pacote.
    """
    try:
        from marvin_hue.api.dependencies import get_scene_favorites_service

        return get_scene_favorites_service()
    except (RuntimeError, ImportError):
        return None


@dataclass(frozen=True)
class RegistryLocation:
    """Registry snapshot row used by get_light_locations (name is Hue join key)."""

    name: str
    room: str
    notes: str | None = None
    eye_safety_limit_pct: int | None = None


class RegistryRoomIndex(dict[str, list[str]]):
    """room → light names, plus registry location rows when built from catalog."""

    def __init__(
        self,
        rooms: Mapping[str, Sequence[str]],
        locations: tuple[RegistryLocation, ...] | None = None,
    ) -> None:
        super().__init__({str(k): [str(n) for n in v] for k, v in rooms.items()})
        self.locations = locations


class RoomIndex(Protocol):
    """Thin read-only view of room → light names (optional DI alternative)."""

    def rooms(self) -> Sequence[str]:
        """Distinct room labels."""
        ...

    def lights_in_room(self, room: str) -> Sequence[str]:
        """Light names in ``room`` (case-insensitive match preferred by caller)."""
        ...


def _eye_safety_pct(raw: object) -> int | None:
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    return raw


def build_room_index_from_registry_rows(
    lights: Sequence[object],
) -> dict[str, list[str]]:
    """Build room_index from registry-like objects (name, room, enabled_for_app).

    Disabled lights are omitted. Empty/missing room → ``sem_sala``.
    Carries ``RegistryLocation`` rows (name, room, notes, eye_safety_limit_pct)
    so get_light_locations can prefer the catalog over JSON.
    """
    room_index: dict[str, list[str]] = {}
    locations: list[RegistryLocation] = []
    for lt in lights:
        if not bool(getattr(lt, "enabled_for_app", True)):
            continue
        name = str(getattr(lt, "name", "") or "").strip()
        if not name:
            continue
        room_raw = getattr(lt, "room", None)
        room = (str(room_raw).strip() if room_raw is not None else "") or _DEFAULT_ROOM
        room_index.setdefault(room, []).append(name)
        notes_raw = getattr(lt, "notes", None)
        notes = str(notes_raw).strip() if notes_raw else None
        locations.append(
            RegistryLocation(
                name=name,
                room=room,
                notes=notes or None,
                eye_safety_limit_pct=_eye_safety_pct(
                    getattr(lt, "eye_safety_limit_pct", None)
                ),
            )
        )
    return RegistryRoomIndex(room_index, tuple(locations))


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


def _locations_from_room_index(
    room_index: Mapping[str, Sequence[str]],
) -> tuple[RegistryLocation, ...] | None:
    existing = getattr(room_index, "locations", None)
    if existing is not None:
        return tuple(existing)
    return tuple(
        RegistryLocation(name=str(n), room=str(room))
        for room, names in room_index.items()
        for n in names
    )


def _normalize_room_index(
    room_index: Mapping[str, Sequence[str]] | None,
    locations_path: str,
) -> dict[str, list[str]]:
    if room_index is not None:
        rooms = {
            str(room): [str(n) for n in names] for room, names in room_index.items()
        }
        return RegistryRoomIndex(rooms, _locations_from_room_index(room_index))
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
    locations_path: str = _DEFAULT_LOCATIONS_PATH,
    *,
    room_index: Mapping[str, Sequence[str]] | None = None,
    favorites_provider: FavoritesProvider | None = None,
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
        favorites_provider: resolve o SceneFavoritesService a cada chamada
            (None → ``default_favorites_provider``). Retornar None ou levantar
            torna as tools de favoritos indisponíveis (fail-open, sem exceção).

    Returns:
        Lista de BaseTool prontas para create_agent (list/status/control + room tools).

    Note:
        Control tools rely on HueController skipping ``enabled_for_app=false`` lights.
        Room metadata is a build-time snapshot; registry room edits need agent rebuild.
    """
    rooms_map = _normalize_room_index(room_index, locations_path)
    resolve_favorites = favorites_provider or default_favorites_provider

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
            default="", description="Termo opcional para filtrar pelo nome"
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
            description="Nome único, sem espaços (use underscores). Crie um nome "
            "criativo baseado nas cores atuais (ex: 'sunset_warm', 'natal_festivo').",
        )
        description: str = Field(
            description="Descrição de uma linha capturando o mood/ambiente das cores."
        )

    class _FavoriteArgs(BaseModel):
        config_name: str = Field(
            description="Nome exato da cena/preset (veja list_configs)."
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
        brightness: int = Field(
            ge=0, le=100, description="Brilho em porcentagem (0-100)"
        )

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
            result = controller.apply_light_config(config, transition_time)
            if result.ok:
                return (
                    f"Configuração '{config_name}' aplicada! "
                    f"Descrição: {config.description}"
                )
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
        manager.configs.append(new_config)
        manager.save()
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
            available = (
                ", ".join(sorted(rooms_map.keys(), key=str.lower)) or "(nenhuma)"
            )
            return f"Sala '{room}' não encontrada. Salas: {available}"
        names = _enabled_names(rooms_map[key])
        if not names:
            return f"Sala '{key}' sem lâmpadas habilitadas."
        return f"Lâmpadas em '{key}': {', '.join(names)}"

    def _set_room_power(room: str, on: bool) -> str:
        key = _match_room(rooms_map, (room or "").strip())
        if key is None:
            available = (
                ", ".join(sorted(rooms_map.keys(), key=str.lower)) or "(nenhuma)"
            )
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
            available = (
                ", ".join(sorted(rooms_map.keys(), key=str.lower)) or "(nenhuma)"
            )
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

    # ----- favoritos (async; ver docstring do módulo) -----
    def _favorites_service() -> "SceneFavoritesService | None":
        try:
            return resolve_favorites()
        except Exception:  # noqa: BLE001 — fail-open
            return None

    def _resolve_scene(name: str) -> tuple[str | None, str | None]:
        """(nome canônico, None) ou (None, mensagem de erro)."""
        if manager.get_config(name) is not None:
            return name, None
        key = name.strip().casefold()
        matches = sorted(
            {c.name for c in manager.configs if c.name.casefold() == key}
        )
        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            return None, (
                f"Nome '{name}' é ambíguo: {', '.join(matches)}. "
                "Use o nome exato."
            )
        return None, (
            f"A cena '{name}' não existe. Use list_configs para ver os nomes "
            "disponíveis."
        )

    def _favorites_sync() -> str:
        if _favorites_service() is None:
            return _FAVORITES_UNAVAILABLE
        return _FAVORITES_SYNC_ONLY

    def _list_favorites_sync() -> str:
        return _favorites_sync()

    def _add_favorite_sync(config_name: str) -> str:
        return _favorites_sync()

    def _remove_favorite_sync(config_name: str) -> str:
        return _favorites_sync()

    async def _list_favorites() -> str:
        service = _favorites_service()
        if service is None:
            return _FAVORITES_UNAVAILABLE
        try:
            names = await service.list_existing()
        except Exception as e:  # noqa: BLE001
            return f"Erro ao listar favoritos: {e}"
        if not names:
            return "Nenhuma cena favorita ainda."
        return "Cenas favoritas: " + ", ".join(names)

    async def _current_favorites(service: "SceneFavoritesService") -> str:
        # Devolve a lista atualizada: o modelo pode chamar list_favorites em
        # paralelo no mesmo turno e ler o estado anterior à escrita.
        try:
            names = await service.list_existing()
        except Exception:  # noqa: BLE001
            return ""
        return "Favoritas agora: " + (", ".join(names) or "nenhuma") + "."

    async def _add_favorite(config_name: str) -> str:
        service = _favorites_service()
        if service is None:
            return _FAVORITES_UNAVAILABLE
        name, error = _resolve_scene(config_name)
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
            return f"Erro ao marcar '{name}' como favorita: {e}"
        return (
            f"Cena '{name}' marcada como favorita "
            "(aparece com estrela na tela Controle). "
            + await _current_favorites(service)
        )

    async def _remove_favorite(config_name: str) -> str:
        service = _favorites_service()
        if service is None:
            return _FAVORITES_UNAVAILABLE
        name, error = _resolve_scene(config_name)
        if name is None:
            return error or ""
        try:
            if name not in await service.list_existing():
                return f"A cena '{name}' não era favorita."
            await service.remove(name)
        except Exception as e:  # noqa: BLE001
            return f"Erro ao remover '{name}' dos favoritos: {e}"
        return f"Cena '{name}' removida dos favoritos. " + await _current_favorites(
            service
        )

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
            name="apply_config",
            description=(
                "Aplica uma configuração/preset de iluminação predefinida. "
                "Lâmpadas desabilitadas no preset são ignoradas pelo controller."
            ),
            args_schema=_ApplyConfigArgs,
        ),
        StructuredTool.from_function(
            func=_list_configs,
            name="list_configs",
            description="Lista os presets de iluminação disponíveis (filtro opcional).",
            args_schema=_ListConfigsArgs,
        ),
        StructuredTool.from_function(
            func=_turn_off_lights,
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
            description="Salva o estado atual das lâmpadas habilitadas como um novo preset.",
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
            description="Lista salas distintas do registry (room_index) com contagem de lâmpadas.",
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
                "Liga ou desliga todas as lâmpadas habilitadas de uma sala. "
                "Desabilitadas são ignoradas pelo controller."
            ),
            args_schema=_SetRoomPowerArgs,
        ),
        StructuredTool.from_function(
            func=_set_room_brightness,
            name="set_room_brightness",
            description=(
                "Ajusta brilho (0-100%) de todas as lâmpadas habilitadas de uma sala. "
                "Eye-safety e skip de desabilitadas via controller."
            ),
            args_schema=_SetRoomBrightnessArgs,
        ),
        StructuredTool.from_function(
            func=_list_favorites_sync,
            coroutine=_list_favorites,
            name="list_favorites",
            description="Lista as cenas favoritas (marcadas com estrela na tela Controle).",
        ),
        StructuredTool.from_function(
            func=_add_favorite_sync,
            coroutine=_add_favorite,
            name="add_favorite",
            description=(
                "Marca uma cena/preset existente como favorita (estrela na tela "
                "Controle). Idempotente."
            ),
            args_schema=_FavoriteArgs,
        ),
        StructuredTool.from_function(
            func=_remove_favorite_sync,
            coroutine=_remove_favorite,
            name="remove_favorite",
            description="Remove uma cena dos favoritos. Idempotente.",
            args_schema=_FavoriteArgs,
        ),
    ]
