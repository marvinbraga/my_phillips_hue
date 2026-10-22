"""API tests for DELETE /configurations/{name} (+ /api alias).

Usa sempre o manager do ``fastapi_test_client`` (setups em arquivo temporário);
nunca toca ``.res/setups.json``.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from marvin_hue.api import dependencies
from marvin_hue.basics import LightSetupsManager

ACCENTED_SCENE = "Pôr do sol na Lâmpada"
SLASH_SCENE = "a/b"


def _names_on_disk(manager: LightSetupsManager) -> list[str]:
    data = json.loads(Path(manager._filename).read_text("utf-8"))
    return [s["name"] for s in data["setups"]]


@pytest.fixture
def accented_manager(fastapi_test_client: TestClient, tmp_path) -> LightSetupsManager:
    setups = tmp_path / "accented_setups.json"
    setups.write_text(
        json.dumps(
            {
                "setups": [
                    {"name": ACCENTED_SCENE, "description": "d", "settings": []},
                    {"name": "relax", "description": "r", "settings": []},
                    {"name": SLASH_SCENE, "description": "s", "settings": []},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manager = LightSetupsManager(str(setups))
    dependencies.set_manager(manager)
    return manager


def test_delete_returns_200_and_persists(fastapi_test_client: TestClient) -> None:
    manager = dependencies.get_manager()
    r = fastapi_test_client.delete("/configurations/relax")
    assert r.status_code == 200, r.text
    assert r.json() == {"name": "relax", "deleted": True}

    names = [c["name"] for c in fastapi_test_client.get("/configurations").json()]
    assert names == ["concentration"]
    assert _names_on_disk(manager) == ["concentration"]


def test_delete_unknown_returns_404(fastapi_test_client: TestClient) -> None:
    manager = dependencies.get_manager()
    r = fastapi_test_client.delete("/configurations/nonexistent_xyz")
    assert r.status_code == 404
    assert "nonexistent_xyz" in r.json()["detail"]
    assert _names_on_disk(manager) == ["concentration", "relax"]


def test_delete_twice_second_is_404(fastapi_test_client: TestClient) -> None:
    assert fastapi_test_client.delete("/configurations/relax").status_code == 200
    assert fastapi_test_client.delete("/configurations/relax").status_code == 404


def test_delete_save_failure_returns_500_and_keeps_scene(
    fastapi_test_client: TestClient, monkeypatch
) -> None:
    import marvin_hue.atomic_io as aio

    manager = dependencies.get_manager()

    def boom(a, b):
        raise OSError("disk full")

    monkeypatch.setattr(aio.os, "replace", boom)
    r = fastapi_test_client.delete("/configurations/relax")
    assert r.status_code == 500
    assert "relax" in r.json()["detail"]
    assert manager.get_config("relax") is not None
    assert _names_on_disk(manager) == ["concentration", "relax"]


def test_delete_accented_and_slash_names(
    fastapi_test_client: TestClient, accented_manager: LightSetupsManager
) -> None:
    r = fastapi_test_client.delete(f"/configurations/{quote(ACCENTED_SCENE)}")
    assert r.status_code == 200, r.text
    assert r.json() == {"name": ACCENTED_SCENE, "deleted": True}

    r = fastapi_test_client.delete(f"/configurations/{quote(SLASH_SCENE, safe='')}")
    assert r.status_code == 200, r.text
    assert r.json() == {"name": SLASH_SCENE, "deleted": True}

    assert _names_on_disk(accented_manager) == ["relax"]


def test_favorites_delete_route_not_shadowed(fastapi_test_client: TestClient) -> None:
    """DELETE /configurations/favorites/{name} continua desmarcando (204), sem excluir a cena."""
    manager = dependencies.get_manager()
    put = fastapi_test_client.put("/configurations/favorites/relax")
    assert put.status_code == 200, put.text

    r = fastapi_test_client.delete("/configurations/favorites/relax")
    assert r.status_code == 204
    assert r.content == b""
    assert fastapi_test_client.get("/configurations/favorites").json() == {
        "favorites": []
    }
    assert manager.get_config("relax") is not None
    assert _names_on_disk(manager) == ["concentration", "relax"]


def test_deleted_scene_disappears_from_favorites_and_last_applied(
    fastapi_test_client: TestClient,
) -> None:
    put = fastapi_test_client.put("/configurations/favorites/relax")
    assert put.status_code == 200, put.text
    applied = fastapi_test_client.post(
        "/apply", json={"config_name": "relax", "transition_time_secs": 0}
    )
    assert applied.status_code in (200, 207), applied.text
    assert fastapi_test_client.get("/configurations/last-applied").json()["name"] == (
        "relax"
    )

    assert fastapi_test_client.delete("/configurations/relax").status_code == 200

    assert fastapi_test_client.get("/configurations/favorites").json() == {
        "favorites": []
    }
    assert fastapi_test_client.get("/configurations/last-applied").json()["name"] is None


def test_api_alias_requires_key(fastapi_test_client: TestClient) -> None:
    from app import app as fastapi_app
    from tests.test_api_key_middleware import _live_api_key_middleware

    fastapi_test_client.get("/configurations")
    mw = _live_api_key_middleware(fastapi_app)
    original = mw._api_key
    mw._api_key = "s3cret"
    try:
        assert fastapi_test_client.delete("/api/configurations/relax").status_code == 401
        r = fastapi_test_client.delete(
            "/api/configurations/relax", headers={"X-API-Key": "s3cret"}
        )
        assert r.status_code == 200
        # LAN route stays open (como o resto de /configurations*)
        assert fastapi_test_client.delete("/configurations/concentration").status_code == 200
    finally:
        mw._api_key = original


def test_production_app_registers_delete_route() -> None:
    from app import app

    collected: dict[str, set[str]] = {}
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path and methods:
            collected.setdefault(path, set()).update(methods)

    assert "DELETE" in collected["/configurations/{name:path}"]
    assert "DELETE" in collected["/api/configurations/{name:path}"]


def test_schedule_referencing_deleted_scene_fails_cleanly(
    fastapi_test_client: TestClient,
) -> None:
    """Agendamento apply_config órfão: run manual → 400; tick → status error, sem exceção."""
    import asyncio
    from datetime import datetime

    created = fastapi_test_client.post(
        "/api/schedules",
        json={
            "name": "Relax noturno",
            "time_hhmm": "22:00",
            "action_type": "apply_config",
            "days_of_week": "0,1,2,3,4,5,6",
            "enabled": True,
            "action_payload": {"config_name": "relax"},
        },
    )
    assert created.status_code == 201, created.text
    sid = created.json()["id"]

    assert fastapi_test_client.delete("/configurations/relax").status_code == 200

    run = fastapi_test_client.post(f"/api/schedules/{sid}/run")
    assert run.status_code == 400
    assert "relax" in run.json()["detail"]

    service = dependencies.get_schedule_service()
    local_now = datetime(2026, 10, 22, 22, 0).astimezone()
    results = asyncio.run(service.tick(local_now))
    assert [(r["schedule_id"], r["status"]) for r in results] == [(sid, "error")]
