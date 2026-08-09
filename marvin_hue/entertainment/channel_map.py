"""Map app light names to Entertainment area channels."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from marvin_hue.entertainment.models import EntertainmentAreaInfo

# Minimum similarity for fuzzy name match (casefold)
_FUZZY_THRESHOLD = 0.72


@dataclass(frozen=True, slots=True)
class MappedChannel:
    """One light name bound to an entertainment channel id."""

    light_name: str
    channel_id: int
    position: str = "ambient"


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.casefold(), b.casefold()).ratio()


def map_lights_to_channels(
    area: EntertainmentAreaInfo,
    light_names: list[str] | list[dict],
) -> list[MappedChannel]:
    """
    Match lights to area channels.

    Matching order per light:
    1. Exact casefold match on channel.name
    2. Fuzzy match on channel.name (SequenceMatcher)
    3. Zip leftover channels by sorted light name (best-effort)

    ``light_names`` may be a list of name strings or dicts with
    ``name`` / ``position`` / optional ``bridge_light_id``.
    """
    # Normalize input to (name, position, bridge_id)
    lights: list[tuple[str, str, str]] = []
    for item in light_names:
        if isinstance(item, str):
            name = item.strip()
            if name:
                lights.append((name, "ambient", ""))
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        pos = str(item.get("position") or "ambient")
        bridge_id = str(item.get("bridge_light_id") or "")
        lights.append((name, pos, bridge_id))

    if not lights or not area.channels:
        return []

    remaining = list(area.channels)
    mapped: list[MappedChannel] = []
    used_names: set[str] = set()

    # Pass 0: bridge id in light_ids / service_id
    for name, pos, bridge_id in lights:
        if not bridge_id:
            continue
        for ch in list(remaining):
            ids = {str(x) for x in ch.light_ids}
            if bridge_id in ids or bridge_id == (ch.service_id or ""):
                mapped.append(MappedChannel(name, ch.channel_id, pos))
                remaining.remove(ch)
                used_names.add(name)
                break

    # Pass 1: exact casefold name match on channel.name
    for name, pos, _bridge in lights:
        if name in used_names:
            continue
        target = name.casefold()
        for ch in list(remaining):
            ch_name = (ch.name or "").casefold()
            if ch_name and ch_name == target:
                mapped.append(MappedChannel(name, ch.channel_id, pos))
                remaining.remove(ch)
                used_names.add(name)
                break
            # light id strings containing the light name
            ids = {str(x).casefold() for x in ch.light_ids}
            if target in ids:
                mapped.append(MappedChannel(name, ch.channel_id, pos))
                remaining.remove(ch)
                used_names.add(name)
                break

    # Pass 2: fuzzy name match
    for name, pos, _bridge in lights:
        if name in used_names:
            continue
        best_score = 0.0
        best_ch = None
        for ch in remaining:
            score = _similarity(name, ch.name or "")
            if score > best_score:
                best_score = score
                best_ch = ch
        if best_ch is not None and best_score >= _FUZZY_THRESHOLD:
            mapped.append(MappedChannel(name, best_ch.channel_id, pos))
            remaining.remove(best_ch)
            used_names.add(name)

    # Pass 3: zip leftovers by name order (best-effort)
    unmatched = sorted(
        [(n, p) for n, p, _ in lights if n not in used_names],
        key=lambda t: t[0].casefold(),
    )
    remaining_sorted = sorted(remaining, key=lambda c: c.channel_id)
    for ch, (name, pos) in zip(remaining_sorted, unmatched):
        mapped.append(MappedChannel(name, ch.channel_id, pos))
        used_names.add(name)

    return mapped
