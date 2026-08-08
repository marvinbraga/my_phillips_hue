"""Tests for SqliteSceneHistoryRepository."""

from datetime import datetime, timedelta, timezone

import pytest

from marvin_hue.domain.scene_history import (
    SceneHistoryNotFoundError,
    SceneHistoryValidationError,
    SceneSnapshot,
)
from marvin_hue.persistence.scene_history_repository import SqliteSceneHistoryRepository
from marvin_hue.persistence.schema import init_db


@pytest.fixture
async def repo(tmp_path):
    path = str(tmp_path / "scene.sqlite")
    await init_db(path)
    r = await SqliteSceneHistoryRepository.open(path)
    yield r
    await r.close()


def _snap(**kwargs) -> SceneSnapshot:
    defaults = dict(
        source="manual",
        label="test",
        payload=[{"name": "Lâmpada 1", "on": True, "brightness": 100}],
    )
    defaults.update(kwargs)
    return SceneSnapshot(**defaults)


@pytest.mark.asyncio
async def test_create_and_get_by_id(repo):
    created = await repo.create(_snap(label="before apply", source="apply"))
    assert created.id is not None
    found = await repo.get_by_id(created.id)
    assert found.label == "before apply"
    assert found.source == "apply"
    assert found.payload[0]["name"] == "Lâmpada 1"


@pytest.mark.asyncio
async def test_get_by_id_missing(repo):
    with pytest.raises(SceneHistoryNotFoundError):
        await repo.get_by_id(99999)


@pytest.mark.asyncio
async def test_get_latest_and_list_recent(repo):
    assert await repo.get_latest() is None

    base = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    s1 = await repo.create(
        _snap(label="first", created_at=base, payload=[{"n": 1}])
    )
    s2 = await repo.create(
        _snap(
            label="second",
            source="mirror_stop",
            created_at=base + timedelta(minutes=1),
            payload=[{"n": 2}],
        )
    )
    latest = await repo.get_latest()
    assert latest is not None
    assert latest.id == s2.id
    assert latest.label == "second"

    recent = await repo.list_recent(limit=10)
    assert [s.id for s in recent] == [s2.id, s1.id]


@pytest.mark.asyncio
async def test_list_recent_limit_validation(repo):
    with pytest.raises(SceneHistoryValidationError):
        await repo.list_recent(limit=0)


@pytest.mark.asyncio
async def test_prune_keep_latest(repo):
    base = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    ids = []
    for i in range(5):
        snap = await repo.create(
            _snap(
                label=f"s{i}",
                created_at=base + timedelta(seconds=i),
                payload=[{"i": i}],
            )
        )
        ids.append(snap.id)

    deleted = await repo.prune_keep_latest(2)
    assert deleted == 3
    remaining = await repo.list_recent(limit=10)
    assert len(remaining) == 2
    assert {s.label for s in remaining} == {"s3", "s4"}


@pytest.mark.asyncio
async def test_prune_keep_zero(repo):
    await repo.create(_snap())
    deleted = await repo.prune_keep_latest(0)
    assert deleted >= 1
    assert await repo.get_latest() is None


@pytest.mark.asyncio
async def test_domain_rejects_invalid_source():
    with pytest.raises(SceneHistoryValidationError):
        SceneSnapshot(source="nope", payload=[])


@pytest.mark.asyncio
async def test_payload_roundtrip_complex(repo):
    payload = [
        {
            "name": "Hue Play 1",
            "on": True,
            "brightness": 200,
            "color": {"r": 10, "g": 20, "b": 30},
        },
        {"name": "Fita Led", "on": False, "brightness": 0},
    ]
    created = await repo.create(_snap(source="group_apply", payload=payload))
    found = await repo.get_by_id(created.id)
    assert found.payload == payload
