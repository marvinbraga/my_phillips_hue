"""API tests for /configurations/favorites (+ /api alias)."""

from __future__ import annotations

import json
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from marvin_hue.api import dependencies
from marvin_hue.basics import LightSetupsManager

ACCENTED_SCENE = "Pôr do sol na Lâmpada"
SLASH_SCENE = "a/b"


@pytest.fixture
def accented_manager(fastapi_test_client: TestClient, tmp_path):
    """Troca o manager por um com nomes com espaço/acento (restaurado no teardown)."""
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


def test_list_empty(fastapi_test_client: TestClient) -> None:
    r = fastapi_test_client.get("/configurations/favorites")
    assert r.status_code == 200
    assert r.json() == {"favorites": []}


def test_add_then_list(fastapi_test_client: TestClient) -> None:
    r = fastapi_test_client.put("/configurations/favorites/relax")
    assert r.status_code == 200, r.text
    assert r.json() == {"name": "relax", "favorite": True}

    put = fastapi_test_client.put("/configurations/favorites/concentration")
    assert put.status_code == 200, put.text
    listed = fastapi_test_client.get("/configurations/favorites")
    assert listed.json() == {"favorites": ["concentration", "relax"]}


def test_add_is_idempotent(fastapi_test_client: TestClient) -> None:
    first = fastapi_test_client.put("/configurations/favorites/relax")
    second = fastapi_test_client.put("/configurations/favorites/relax")
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == {"name": "relax", "favorite": True}
    listed = fastapi_test_client.get("/configurations/favorites").json()
    assert listed == {"favorites": ["relax"]}


def test_add_unknown_scene_404(fastapi_test_client: TestClient) -> None:
    r = fastapi_test_client.put("/configurations/favorites/nonexistent_xyz")
    assert r.status_code == 404
    assert "nonexistent_xyz" in r.json()["detail"]
    assert fastapi_test_client.get("/configurations/favorites").json() == {
        "favorites": []
    }


def test_remove_returns_204_and_is_idempotent(fastapi_test_client: TestClient) -> None:
    put = fastapi_test_client.put("/configurations/favorites/relax")
    assert put.status_code == 200, put.text
    r = fastapi_test_client.delete("/configurations/favorites/relax")
    assert r.status_code == 204
    assert r.content == b""
    again = fastapi_test_client.delete("/configurations/favorites/relax")
    assert again.status_code == 204
    unknown = fastapi_test_client.delete("/configurations/favorites/never_added")
    assert unknown.status_code == 204
    assert fastapi_test_client.get("/configurations/favorites").json() == {
        "favorites": []
    }


def test_encoded_name_with_spaces_and_accents(
    fastapi_test_client: TestClient, accented_manager
) -> None:
    path = f"/configurations/favorites/{quote(ACCENTED_SCENE)}"
    r = fastapi_test_client.put(path)
    assert r.status_code == 200, r.text
    assert r.json() == {"name": ACCENTED_SCENE, "favorite": True}

    listed = fastapi_test_client.get("/configurations/favorites").json()
    assert listed == {"favorites": [ACCENTED_SCENE]}

    d = fastapi_test_client.delete(path)
    assert d.status_code == 204
    assert fastapi_test_client.get("/configurations/favorites").json() == {
        "favorites": []
    }


@pytest.mark.parametrize("encoded", [SLASH_SCENE, quote(SLASH_SCENE, safe="")])
def test_name_with_slash(
    fastapi_test_client: TestClient, accented_manager, encoded: str
) -> None:
    path = f"/configurations/favorites/{encoded}"
    r = fastapi_test_client.put(path)
    assert r.status_code == 200, r.text
    assert r.json() == {"name": SLASH_SCENE, "favorite": True}

    # GET da coleção continua respondendo a lista (sem conflito com {name:path}).
    listed = fastapi_test_client.get("/configurations/favorites")
    assert listed.status_code == 200
    assert listed.json() == {"favorites": [SLASH_SCENE]}

    d = fastapi_test_client.delete(path)
    assert d.status_code == 204
    assert fastapi_test_client.get("/configurations/favorites").json() == {
        "favorites": []
    }


def test_orphan_hidden_after_scene_disappears(
    fastapi_test_client: TestClient, tmp_path
) -> None:
    """D4: favorito órfão some do GET, mas volta quando a cena volta."""
    original = dependencies.get_manager()
    put = fastapi_test_client.put("/configurations/favorites/relax")
    assert put.status_code == 200, put.text

    setups = tmp_path / "only_concentration.json"
    setups.write_text(
        json.dumps(
            {"setups": [{"name": "concentration", "description": "c", "settings": []}]}
        ),
        encoding="utf-8",
    )
    dependencies.set_manager(LightSetupsManager(str(setups)))
    assert fastapi_test_client.get("/configurations/favorites").json() == {
        "favorites": []
    }

    dependencies.set_manager(original)
    assert fastapi_test_client.get("/configurations/favorites").json() == {
        "favorites": ["relax"]
    }


def test_configurations_default_response_unchanged(
    fastapi_test_client: TestClient,
) -> None:
    put = fastapi_test_client.put("/configurations/favorites/relax")
    assert put.status_code == 200, put.text
    r = fastapi_test_client.get("/configurations")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert all(set(item) == {"name", "description"} for item in body)


def test_api_alias_parity(fastapi_test_client: TestClient) -> None:
    put = fastapi_test_client.put("/api/configurations/favorites/relax")
    assert put.status_code == 200
    assert put.json() == {"name": "relax", "favorite": True}

    lan = fastapi_test_client.get("/configurations/favorites")
    api = fastapi_test_client.get("/api/configurations/favorites")
    assert lan.status_code == 200
    assert api.status_code == 200
    assert api.json() == lan.json() == {"favorites": ["relax"]}

    assert (
        fastapi_test_client.put("/api/configurations/favorites/nope_xyz").status_code
        == 404
    )
    assert (
        fastapi_test_client.delete("/api/configurations/favorites/relax").status_code
        == 204
    )
    assert fastapi_test_client.get("/configurations/favorites").json() == {
        "favorites": []
    }


def test_production_app_registers_favorites_routes() -> None:
    from app import app

    collected: dict[str, set[str]] = {}
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path and methods:
            collected.setdefault(path, set()).update(methods)

    assert "GET" in collected["/configurations/favorites"]
    assert "GET" in collected["/api/configurations/favorites"]
    assert {"PUT", "DELETE"} <= collected["/configurations/favorites/{name:path}"]
    assert {"PUT", "DELETE"} <= collected["/api/configurations/favorites/{name:path}"]


def test_api_key_boundary_for_favorites(fastapi_test_client: TestClient) -> None:
    """Com API_KEY: rota LAN aberta; alias /api/* exige a chave."""
    from app import app as fastapi_app
    from tests.test_api_key_middleware import _live_api_key_middleware

    fastapi_test_client.get("/configurations/favorites")
    mw = _live_api_key_middleware(fastapi_app)
    original = mw._api_key
    mw._api_key = "s3cret"
    try:
        lan = "/configurations/favorites"
        assert fastapi_test_client.get(lan).status_code == 200
        assert fastapi_test_client.put(f"{lan}/relax").status_code == 200
        assert fastapi_test_client.delete(f"{lan}/relax").status_code == 204

        api = "/api/configurations/favorites"
        assert fastapi_test_client.get(api).status_code == 401
        assert fastapi_test_client.put(f"{api}/relax").status_code == 401
        assert fastapi_test_client.delete(f"{api}/relax").status_code == 401

        headers = {"X-API-Key": "s3cret"}
        assert fastapi_test_client.get(api, headers=headers).status_code == 200
        assert (
            fastapi_test_client.put(f"{api}/relax", headers=headers).status_code == 200
        )
        assert (
            fastapi_test_client.delete(f"{api}/relax", headers=headers).status_code
            == 204
        )
    finally:
        mw._api_key = original
