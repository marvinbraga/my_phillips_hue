"""JsonPositionsRepository: Protocol + JSON adapter for light positions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from marvin_hue.config import settings
from marvin_hue.persistence.positions_repository import (
    JsonPositionsRepository,
    PositionsRepository,
)

CANONICAL_NAMES = [
    "Lâmpada 1",
    "Lâmpada 2",
    "Lâmpada 3",
    "Lâmpada 4",
    "Hue Iris",
    "Hue Play 1",
    "Hue Play 2",
    "Fita Led",
    "Led cima",
]


@pytest.fixture
def repo(tmp_path: Path) -> JsonPositionsRepository:
    return JsonPositionsRepository(path=tmp_path / "light_positions.json")


def test_json_adapter_satisfies_protocol() -> None:
    repo = JsonPositionsRepository(path="unused.json")
    assert isinstance(repo, PositionsRepository)


def test_default_payload_has_nine_canonical_lights() -> None:
    repo = JsonPositionsRepository(path="unused.json")
    payload = repo.default_payload()
    names = [item["name"] for item in payload["lights"]]
    assert names == CANONICAL_NAMES
    by_name = {item["name"]: item for item in payload["lights"]}
    for ceiling in ("Lâmpada 1", "Lâmpada 2", "Lâmpada 3", "Lâmpada 4"):
        assert by_name[ceiling]["position"] == "none"
        assert by_name[ceiling]["enabled"] is True
    assert by_name["Hue Iris"]["position"] == "none"
    assert by_name["Hue Play 1"]["position"] == "left"
    assert by_name["Hue Play 2"]["position"] == "right"
    assert by_name["Fita Led"]["position"] == "top"
    assert by_name["Led cima"]["position"] == "top"
    assert isinstance(payload["positions"], list)
    assert {item["id"] for item in payload["positions"]} >= {
        "none",
        "left",
        "right",
        "top",
        "bottom",
        "center",
        "ambient",
    }


@pytest.mark.asyncio
async def test_load_missing_file_returns_empty_dict(
    repo: JsonPositionsRepository,
) -> None:
    assert await repo.load() == {}


@pytest.mark.asyncio
async def test_load_non_object_json_returns_empty_dict(
    tmp_path: Path,
) -> None:
    path = tmp_path / "light_positions.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    repo = JsonPositionsRepository(path=path)
    assert await repo.load() == {}


@pytest.mark.asyncio
async def test_save_then_load_roundtrip(
    repo: JsonPositionsRepository, tmp_path: Path
) -> None:
    payload = repo.default_payload()
    await repo.save(payload)
    loaded = await repo.load()
    assert loaded["lights"][2]["name"] == "Lâmpada 3"
    on_disk = json.loads(
        (tmp_path / "light_positions.json").read_text(encoding="utf-8")
    )
    assert on_disk["lights"][2]["name"] == "Lâmpada 3"
    assert on_disk["lights"][5]["position"] == "left"
    assert on_disk["lights"][6]["position"] == "right"


@pytest.mark.asyncio
async def test_injected_path_not_settings_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    default_path = tmp_path / "settings_default.json"
    injected = tmp_path / "injected.json"
    monkeypatch.setattr(settings, "positions_file", str(default_path))
    repo = JsonPositionsRepository(path=injected)
    await repo.save({"lights": [{"name": "Injected"}]})
    assert injected.exists()
    assert not default_path.exists()
    loaded = await repo.load()
    assert loaded["lights"][0]["name"] == "Injected"


@pytest.mark.asyncio
async def test_default_constructor_uses_settings_positions_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest = tmp_path / "from_settings.json"
    dest.write_text(
        json.dumps({"lights": [{"name": "FromSettings"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "positions_file", str(dest))
    repo = JsonPositionsRepository()
    loaded = await repo.load()
    assert loaded["lights"][0]["name"] == "FromSettings"


@pytest.mark.asyncio
async def test_save_preserves_non_lights_keys(
    repo: JsonPositionsRepository,
) -> None:
    await repo.save({"lights": [{"name": "A"}], "positions": [{"id": "none"}]})
    loaded = await repo.load()
    assert loaded["positions"][0]["id"] == "none"
