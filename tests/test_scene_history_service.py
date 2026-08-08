"""Unit tests for SceneHistoryService."""

from unittest.mock import MagicMock

import pytest

from marvin_hue.domain.scene_history import SceneHistoryNotFoundError
from marvin_hue.persistence.scene_history_repository import SqliteSceneHistoryRepository
from marvin_hue.persistence.schema import init_db
from marvin_hue.services.scene_history import SceneHistoryService


@pytest.fixture
async def history_svc(tmp_path):
    path = str(tmp_path / "h.sqlite")
    await init_db(path)
    repo = await SqliteSceneHistoryRepository.open(path)
    svc = SceneHistoryService(repo, keep_latest=3)
    yield svc
    await svc.aclose()


def _hue_with_status(status):
    hue = MagicMock()
    hue.get_lights_status.return_value = status
    hue.turn_on.return_value = True
    hue.turn_off.return_value = True
    return hue


@pytest.mark.asyncio
async def test_snapshot_and_list(history_svc):
    hue = _hue_with_status(
        [{"name": "Lâmpada 1", "on": True, "brightness": 100, "color": {"r": 1, "g": 2, "b": 3}}]
    )
    snap = await history_svc.snapshot(hue, source="manual", label="t1")
    assert snap.id is not None
    recent = await history_svc.list_recent(5)
    assert len(recent) == 1
    assert recent[0].source == "manual"


@pytest.mark.asyncio
async def test_restore_last(history_svc):
    status = [
        {
            "name": "Lâmpada 1",
            "on": True,
            "brightness": 200,
            "color": {"r": 10, "g": 20, "b": 30},
        },
        {"name": "Hue Iris", "on": False, "brightness": 0, "color": {"r": 0, "g": 0, "b": 0}},
    ]
    hue = _hue_with_status(status)
    await history_svc.snapshot(hue, source="apply")
    result = await history_svc.restore_last(hue)
    assert result["restored_count"] == 2
    hue.turn_on.assert_any_call("Lâmpada 1")
    hue.turn_off.assert_any_call("Hue Iris")
    hue.set_light_color.assert_called()


@pytest.mark.asyncio
async def test_restore_empty_raises(history_svc):
    hue = _hue_with_status([])
    with pytest.raises(SceneHistoryNotFoundError):
        await history_svc.restore_last(hue)


@pytest.mark.asyncio
async def test_prune_keep_latest(history_svc):
    hue = _hue_with_status([{"name": "A", "on": False, "brightness": 0, "color": {}}])
    for i in range(5):
        await history_svc.snapshot(hue, source="manual", label=f"s{i}")
    recent = await history_svc.list_recent(20)
    assert len(recent) == 3
