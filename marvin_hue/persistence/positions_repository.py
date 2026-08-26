"""Light positions repository: Protocol + JSON file adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import aiofiles  # type: ignore[import-untyped]

from marvin_hue.config import settings

_CANONICAL_LIGHTS: tuple[tuple[str, str], ...] = (
    ("Lâmpada 1", "none"),
    ("Lâmpada 2", "none"),
    ("Lâmpada 3", "none"),
    ("Lâmpada 4", "none"),
    ("Hue Iris", "none"),
    ("Hue Play 1", "left"),
    ("Hue Play 2", "right"),
    ("Fita Led", "top"),
    ("Led cima", "top"),
)

_POSITION_CATALOG: tuple[tuple[str, str, str], ...] = (
    ("none", "Não usar", "Lâmpada não participa do espelhamento"),
    ("left", "Esquerda", "Lado esquerdo do monitor"),
    ("right", "Direita", "Lado direito do monitor"),
    ("top", "Topo", "Parte superior do monitor"),
    ("bottom", "Base", "Parte inferior do monitor"),
    ("top-left", "Topo Esquerdo", "Canto superior esquerdo"),
    ("top-right", "Topo Direito", "Canto superior direito"),
    ("bottom-left", "Base Esquerda", "Canto inferior esquerdo"),
    ("bottom-right", "Base Direita", "Canto inferior direito"),
    ("center", "Centro", "Região central da tela"),
    ("ambient", "Ambiente", "Cor média de toda a tela"),
)


@runtime_checkable
class PositionsRepository(Protocol):
    async def load(self) -> dict[str, Any]: ...

    async def save(self, data: dict[str, Any]) -> None: ...

    def default_payload(self) -> dict[str, Any]: ...


class JsonPositionsRepository:
    """JSON adapter for light positions. Path defaults to settings.positions_file."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._path_override = Path(path) if path is not None else None

    def _resolve_path(self) -> Path:
        if self._path_override is not None:
            return self._path_override
        return Path(settings.positions_file)

    def default_payload(self) -> dict[str, Any]:
        return {
            "lights": [
                {"name": name, "position": position, "enabled": True}
                for name, position in _CANONICAL_LIGHTS
            ],
            "positions": [
                {"id": pid, "label": label, "description": description}
                for pid, label, description in _POSITION_CATALOG
            ],
        }

    async def load(self) -> dict[str, Any]:
        filepath = self._resolve_path()
        if not filepath.exists():
            return {}
        async with aiofiles.open(filepath, "r", encoding="utf-8") as handle:
            content = await handle.read()
        parsed: object = json.loads(content)
        if not isinstance(parsed, dict):
            return {}
        return parsed

    async def save(self, data: dict[str, Any]) -> None:
        filepath = self._resolve_path()
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        async with aiofiles.open(filepath, "w", encoding="utf-8") as handle:
            await handle.write(payload)
