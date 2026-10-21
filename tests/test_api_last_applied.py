"""Last applied scene (issue #14): recorded on apply, cleared by off / undo.

``GET /configurations/last-applied`` is open on the LAN path (like
``/configurations``); the ``/api`` alias comes from the double router include.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from marvin_hue import eye_safety
from marvin_hue.api import dependencies
from marvin_hue.apply_result import ApplyResult
from marvin_hue.basics import LightSetupsManager
from marvin_hue.controllers import HueController
from marvin_hue.services.lights_off import LightsOffService

EMPTY = {"name": None, "source": None, "applied_at": None}
L1 = "Lâmpada 1"
L2 = "Lâmpada 2"


@pytest.fixture
def clean_policy() -> Iterator[None]:
    eye_safety.clear_runtime_policy()
    yield
    eye_safety.clear_runtime_policy()


def _last(client: TestClient, prefix: str = "") -> dict[str, Any]:
    response = client.get(f"{prefix}/configurations/last-applied")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _apply(client: TestClient, name: str = "concentration") -> int:
    response = client.post(
        "/apply", json={"config_name": name, "transition_time_secs": 0}
    )
    return response.status_code


# --- GET endpoint ---------------------------------------------------------


def test_empty_returns_nulls(fastapi_test_client: TestClient) -> None:
    assert _last(fastapi_test_client) == EMPTY


def test_apply_records_last_applied(
    fastapi_test_client: TestClient, clean_policy: None
) -> None:
    assert _apply(fastapi_test_client, "relax") == 200

    body = _last(fastapi_test_client)
    assert body["name"] == "relax"
    assert body["source"] == "apply"
    applied_at = datetime.fromisoformat(body["applied_at"])
    assert applied_at.tzinfo is not None


def test_latest_apply_wins(fastapi_test_client: TestClient, clean_policy: None) -> None:
    assert _apply(fastapi_test_client, "relax") == 200
    assert _apply(fastapi_test_client, "concentration") == 200
    assert _last(fastapi_test_client)["name"] == "concentration"


def test_api_alias(fastapi_test_client: TestClient, clean_policy: None) -> None:
    assert _last(fastapi_test_client, "/api") == EMPTY
    assert _apply(fastapi_test_client, "relax") == 200
    assert _last(fastapi_test_client, "/api")["name"] == "relax"


def test_production_app_registers_alias() -> None:
    import app

    paths = {getattr(r, "path", None) for r in app.app.routes}
    assert "/configurations/last-applied" in paths
    assert "/api/configurations/last-applied" in paths


def test_partial_apply_records(
    fastapi_test_client: TestClient,
    mock_hue_controller: HueController,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mock_hue_controller,
        "apply_light_config",
        lambda cfg, t=0: ApplyResult(applied=(L1,), failed=((L2, "boom"),)),
    )
    assert _apply(fastapi_test_client, "concentration") == 207
    assert _last(fastapi_test_client)["name"] == "concentration"


def test_all_failed_apply_does_not_record(
    fastapi_test_client: TestClient,
    mock_hue_controller: HueController,
    monkeypatch: pytest.MonkeyPatch,
    clean_policy: None,
) -> None:
    assert _apply(fastapi_test_client, "relax") == 200
    monkeypatch.setattr(
        mock_hue_controller,
        "apply_light_config",
        lambda cfg, t=0: ApplyResult(applied=(), failed=((L1, "x"), (L2, "y"))),
    )
    assert _apply(fastapi_test_client, "concentration") == 500
    # Previous successful scene is still the last applied one
    assert _last(fastapi_test_client)["name"] == "relax"


def test_orphan_scene_returns_null(
    fastapi_test_client: TestClient, tmp_path, clean_policy: None
) -> None:
    assert _apply(fastapi_test_client, "relax") == 200
    setups = tmp_path / "without_relax.json"
    setups.write_text(
        json.dumps({"setups": [{"name": "other", "description": "", "settings": []}]}),
        encoding="utf-8",
    )
    dependencies.set_manager(LightSetupsManager(str(setups)))
    assert _last(fastapi_test_client) == EMPTY


def test_service_missing_returns_nulls_and_apply_still_works(
    fastapi_test_client: TestClient, clean_policy: None
) -> None:
    service = dependencies.get_last_applied_scene_service_optional()
    dependencies.set_last_applied_scene_service(None)
    try:
        assert _last(fastapi_test_client) == EMPTY
        assert _apply(fastapi_test_client, "relax") == 200
        assert fastapi_test_client.post("/lights/off", json={}).status_code == 200
    finally:
        dependencies.set_last_applied_scene_service(service)


# --- clear on lights off / undo -----------------------------------------


def test_lights_off_clears(fastapi_test_client: TestClient, clean_policy: None) -> None:
    assert _apply(fastapi_test_client, "relax") == 200
    response = fastapi_test_client.post("/lights/off", json={})
    assert response.status_code == 200, response.text
    assert _last(fastapi_test_client) == EMPTY


def test_lights_off_with_nothing_turned_off_keeps_record(
    fastapi_test_client: TestClient, clean_policy: None
) -> None:
    assert _apply(fastapi_test_client, "relax") == 200
    eye_safety.set_runtime_policy(limits_pct={}, disabled_names={L1, L2})
    response = fastapi_test_client.post("/lights/off", json={})
    assert response.status_code == 200
    assert _last(fastapi_test_client)["name"] == "relax"


def test_undo_clears(fastapi_test_client: TestClient, clean_policy: None) -> None:
    assert _apply(fastapi_test_client, "relax") == 200
    response = fastapi_test_client.post("/api/history/undo")
    assert response.status_code == 200, response.text
    assert _last(fastapi_test_client) == EMPTY


def test_failed_undo_keeps_record(
    fastapi_test_client: TestClient, clean_policy: None
) -> None:
    service = dependencies.get_last_applied_scene_service_optional()
    assert service is not None
    asyncio.run(service.record("relax", source="apply"))
    # Fresh DB: no snapshot to restore → 404, nothing changed on the lights
    response = fastapi_test_client.post("/api/history/undo")
    assert response.status_code == 404
    assert _last(fastapi_test_client)["name"] == "relax"


def test_undo_restoring_nothing_keeps_record(
    fastapi_test_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    clean_policy: None,
) -> None:
    assert _apply(fastapi_test_client, "relax") == 200
    history = dependencies.get_scene_history_service()

    async def restore_nothing(hue: Any) -> dict[str, Any]:
        return {
            "snapshot_id": 1,
            "source": "apply",
            "label": None,
            "created_at": "2026-01-01T00:00:00+00:00",
            "restored_lights": [],
            "restored_count": 0,
        }

    monkeypatch.setattr(history, "restore_last", restore_nothing)
    response = fastapi_test_client.post("/api/history/undo")
    assert response.status_code == 200, response.text
    assert _last(fastapi_test_client)["name"] == "relax"


def test_undo_clear_failure_is_fail_open(
    fastapi_test_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    clean_policy: None,
) -> None:
    assert _apply(fastapi_test_client, "relax") == 200
    service = dependencies.get_last_applied_scene_service_optional()
    assert service is not None

    async def broken_clear(source: str) -> None:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(service._repo, "clear", broken_clear)
    response = fastapi_test_client.post("/api/history/undo")
    assert response.status_code == 200, response.text


def test_lights_off_clear_failure_is_fail_open(
    fastapi_test_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    clean_policy: None,
) -> None:
    service = dependencies.get_last_applied_scene_service_optional()
    assert service is not None

    async def broken_clear(source: str) -> None:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(service._repo, "clear", broken_clear)
    response = fastapi_test_client.post("/lights/off", json={})
    assert response.status_code == 200, response.text


# --- other sources --------------------------------------------------------


def test_group_apply_records_group_source(
    fastapi_test_client: TestClient, clean_policy: None
) -> None:
    light = fastapi_test_client.post("/api/lights", json={"name": L1}).json()
    group = fastapi_test_client.post(
        "/api/groups", json={"name": "Desk", "light_ids": [light["id"]]}
    ).json()
    response = fastapi_test_client.post(
        f"/api/groups/{group['id']}/apply",
        json={"config_name": "concentration", "transition_time_secs": 0},
    )
    assert response.status_code == 200, response.text
    body = _last(fastapi_test_client)
    assert body["name"] == "concentration"
    assert body["source"] == "group"


# --- LightsOffService port (unit) ---------------------------------------


class _FakeClear:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.sources: list[str] = []

    async def clear(self, *, source: str) -> None:
        self.sources.append(source)
        if self.error is not None:
            raise self.error


def test_service_lights_off_clears_last_applied(
    mock_hue_controller: HueController, clean_policy: None
) -> None:
    clear = _FakeClear()
    service = LightsOffService(mock_hue_controller, last_applied=clear)
    result = asyncio.run(service.turn_off_all(transition_time=0))
    assert result.applied
    assert clear.sources == ["lights_off"]


def test_service_lights_off_all_failed_does_not_clear(
    mock_hue_controller: HueController,
    monkeypatch: pytest.MonkeyPatch,
    clean_policy: None,
) -> None:
    def broken(name: str, tenths: int) -> bool:
        raise RuntimeError("boom")

    monkeypatch.setattr(mock_hue_controller, "turn_off_with_transition", broken)
    clear = _FakeClear()
    service = LightsOffService(mock_hue_controller, last_applied=clear)
    result = asyncio.run(service.turn_off_all(transition_time=0))
    assert not result.applied
    assert clear.sources == []
