"""Índice de salas do chat: sala → nomes de lâmpadas (registry ou JSON).

``room_index`` é um snapshot síncrono montado na construção do agente
(lifespan / reconfigure) a partir do registry. Sem registry, as lâmpadas são
agrupadas pelo ``room`` ou ``location`` de ``light_physical_locations.json``
(ex.: "Teto, à direita").

Casamento de sala (``match_rooms``): nome exato (sem maiúsculas) primeiro;
senão, cada termo da consulta tem de ser prefixo de uma palavra do nome da
sala, sem acentos. Assim "teto" casa "Teto, à direita" e "Teto, à esquerda".
Várias salas casadas → as tools agem na união e dizem quais salas usaram.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from marvin_hue.eye_safety import is_enabled_for_app

DEFAULT_LOCATIONS_PATH = ".res/light_physical_locations.json"
DEFAULT_ROOM = "sem_sala"


@dataclass(frozen=True)
class RegistryLocation:
    """Registry snapshot row used by get_light_locations (name is Hue join key)."""

    name: str
    room: str
    notes: str | None = None
    eye_safety_limit_pct: int | None = None


class RegistryRoomIndex(dict[str, list[str]]):
    """room → light names; ``locations`` só existe quando veio do registry.

    ``locations is None`` (fallback JSON) faz ``get_light_locations`` ler o
    arquivo de localizações físicas em vez do catálogo.
    """

    def __init__(
        self,
        rooms: Mapping[str, Sequence[str]],
        locations: tuple[RegistryLocation, ...] | None = None,
    ) -> None:
        super().__init__({str(k): [str(n) for n in v] for k, v in rooms.items()})
        self.locations = locations


def _eye_safety_pct(raw: object) -> int | None:
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    return raw


def build_room_index_from_registry_rows(lights: Sequence[object]) -> RegistryRoomIndex:
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
        room = (str(room_raw).strip() if room_raw is not None else "") or DEFAULT_ROOM
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


def room_index_from_locations(path: str) -> dict[str, list[str]]:
    """Fallback sem registry: agrupa por ``room`` ou ``location`` do JSON."""
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
        room_raw = light.get("room") or light.get("location") or DEFAULT_ROOM
        room = str(room_raw).strip() or DEFAULT_ROOM
        room_index.setdefault(room, []).append(name)
    return room_index


def _locations_from_room_index(
    room_index: Mapping[str, Sequence[str]],
) -> tuple[RegistryLocation, ...]:
    return tuple(
        RegistryLocation(name=str(n), room=str(room))
        for room, names in room_index.items()
        for n in names
    )


def normalize_room_index(
    room_index: Mapping[str, Sequence[str]] | None,
    locations_path: str = DEFAULT_LOCATIONS_PATH,
) -> RegistryRoomIndex:
    """Normaliza uma vez (idempotente): ``RegistryRoomIndex`` volta como está."""
    if isinstance(room_index, RegistryRoomIndex):
        return room_index
    if room_index is not None:
        return RegistryRoomIndex(room_index, _locations_from_room_index(room_index))
    return RegistryRoomIndex(room_index_from_locations(locations_path), None)


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", _fold(text))


def match_room(rooms: Mapping[str, Sequence[str]], room: str) -> str | None:
    """Exact then case-insensitive room key match (single room)."""
    if room in rooms:
        return room
    key = room.strip().casefold()
    for name in rooms:
        if name.casefold() == key:
            return name
    return None


def match_rooms(rooms: Mapping[str, Sequence[str]], query: str) -> list[str]:
    """Salas que casam com ``query``: exata, senão prefixo de palavra (sem acento)."""
    exact = match_room(rooms, query or "")
    if exact is not None:
        return [exact]
    terms = _words(query or "")
    if not terms:
        return []
    hits = []
    for name in rooms:
        words = _words(name)
        if all(any(w.startswith(t) for w in words) for t in terms):
            hits.append(name)
    return sorted(hits, key=str.casefold)


def enabled_names(names: Sequence[str]) -> list[str]:
    return [n for n in names if is_enabled_for_app(n)]


def resolve_room_lights(
    rooms: Mapping[str, Sequence[str]], query: str
) -> tuple[str, list[str]] | None:
    """(rótulo, lâmpadas habilitadas sem repetição) das salas casadas, ou None."""
    keys = match_rooms(rooms, query)
    if not keys:
        return None
    names: list[str] = []
    for key in keys:
        for name in enabled_names(rooms[key]):
            if name not in names:
                names.append(name)
    if len(keys) == 1:
        return f"sala '{keys[0]}'", names
    return "salas " + ", ".join(f"'{k}'" for k in keys), names


def room_list(rooms: Mapping[str, Sequence[str]]) -> str:
    return ", ".join(sorted(rooms.keys(), key=str.lower)) or "(nenhuma)"
