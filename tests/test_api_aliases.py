"""Wave 3: /api aliases for LAN JSON routes + app.state dual-write."""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from marvin_hue.api import dependencies


def _route_methods() -> dict[str, set[str]]:
    from app import app

    collected: dict[str, set[str]] = {}
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods:
            continue
        collected.setdefault(path, set()).update(methods)
    return collected


def test_production_app_registers_api_aliases() -> None:
    methods = _route_methods()

    assert "POST" in methods["/apply"]
    assert "POST" in methods["/api/apply"]
    assert "GET" in methods["/configurations"]
    assert "GET" in methods["/api/configurations"]

    assert "POST" in methods["/mirror/start"]
    assert "POST" in methods["/api/mirror/start"]
    assert "POST" in methods["/mirror/stop"]
    assert "POST" in methods["/api/mirror/stop"]
    assert "GET" in methods["/mirror/status"]
    assert "GET" in methods["/api/mirror/status"]
    assert "POST" in methods["/mirror/settings"]
    assert "POST" in methods["/api/mirror/settings"]

    assert "GET" in methods["/positions"]
    assert "GET" in methods["/api/positions"]
    assert "POST" in methods["/positions"]
    assert "POST" in methods["/api/positions"]

    assert "GET" in methods["/positions-config"]
    assert "/api/positions-config" not in methods
    assert "GET" in methods["/mirror"]
    assert "/api/mirror" not in methods


def test_html_pages_are_not_aliased_under_api(fastapi_test_client: TestClient) -> None:
    assert fastapi_test_client.get("/positions-config").status_code == 200
    assert fastapi_test_client.get("/mirror").status_code == 200
    assert fastapi_test_client.get("/api/positions-config").status_code == 404
    assert fastapi_test_client.get("/api/mirror").status_code == 404


def test_api_configurations_matches_lan(fastapi_test_client: TestClient) -> None:
    lan = fastapi_test_client.get("/configurations")
    api = fastapi_test_client.get("/api/configurations")
    assert lan.status_code == 200
    assert api.status_code == 200
    assert api.json() == lan.json()
    assert isinstance(api.json(), list)


def test_api_apply_matches_lan_not_found(fastapi_test_client: TestClient) -> None:
    payload = {"config_name": "nonexistent_config_xyz"}
    lan = fastapi_test_client.post("/apply", json=payload)
    api = fastapi_test_client.post("/api/apply", json=payload)
    assert lan.status_code == 404
    assert api.status_code == 404
    assert "nonexistent_config_xyz" in api.json()["detail"]
    assert api.json()["detail"] == lan.json()["detail"]


def test_api_apply_matches_lan_valid(fastapi_test_client: TestClient) -> None:
    configs = fastapi_test_client.get("/configurations").json()
    assert configs
    payload = {"config_name": configs[0]["name"]}
    lan = fastapi_test_client.post("/apply", json=payload)
    api = fastapi_test_client.post("/api/apply", json=payload)
    assert lan.status_code in (200, 207)
    assert api.status_code in (200, 207)
    assert api.json()["details"]["config_name"] == payload["config_name"]


def test_api_mirror_status_matches_lan(fastapi_test_client: TestClient) -> None:
    lan = fastapi_test_client.get("/mirror/status")
    api = fastapi_test_client.get("/api/mirror/status")
    assert lan.status_code == 200
    assert api.status_code == 200
    assert api.json() == lan.json()


def test_api_positions_get_matches_lan(fastapi_test_client: TestClient) -> None:
    lan = fastapi_test_client.get("/positions")
    api = fastapi_test_client.get("/api/positions")
    assert lan.status_code == 200
    assert api.status_code == 200
    assert api.json() == lan.json()


def test_populate_app_state_copies_hue_controller() -> None:
    original_hue = dependencies._hue_controller
    original_bound = getattr(dependencies, "_bound_app", None)
    app = FastAPI()
    hue = Mock(name="hue_controller")
    try:
        dependencies.set_hue_controller(hue)
        dependencies.populate_app_state(app)
        assert app.state.hue_controller is hue
    finally:
        dependencies._hue_controller = original_hue
        if hasattr(dependencies, "bind_fastapi_app"):
            dependencies.bind_fastapi_app(original_bound)


def test_set_hue_controller_dual_writes_bound_app_state() -> None:
    original_hue = dependencies._hue_controller
    original_bound = getattr(dependencies, "_bound_app", None)
    app = FastAPI()
    hue = Mock(name="bound_hue")
    try:
        dependencies.bind_fastapi_app(app)
        dependencies.set_hue_controller(hue)
        assert app.state.hue_controller is hue
        assert dependencies.get_hue_controller() is hue
    finally:
        dependencies._hue_controller = original_hue
        dependencies.bind_fastapi_app(original_bound)


def test_set_hue_controller_without_app_still_feeds_getter() -> None:
    original_hue = dependencies._hue_controller
    original_bound = getattr(dependencies, "_bound_app", None)
    hue = Mock(name="locator_hue")
    try:
        dependencies.bind_fastapi_app(None)
        dependencies.set_hue_controller(hue)
        assert dependencies.get_hue_controller() is hue
    finally:
        dependencies._hue_controller = original_hue
        if original_bound is not None:
            dependencies.bind_fastapi_app(original_bound)
        else:
            dependencies.bind_fastapi_app(None)


def test_populate_app_state_copies_main_services() -> None:
    originals: dict[str, Any] = {
        "hue": dependencies._hue_controller,
        "manager": dependencies._manager,
        "screen": dependencies._screen_mirror,
        "audio": dependencies._audio_mirror,
        "bound": getattr(dependencies, "_bound_app", None),
    }
    app = FastAPI()
    hue, manager, screen, audio = Mock(), Mock(), Mock(), Mock()
    try:
        dependencies.set_hue_controller(hue)
        dependencies.set_manager(manager)
        dependencies.set_screen_mirror(screen)
        dependencies.set_audio_mirror(audio)
        dependencies.populate_app_state(app)
        assert app.state.hue_controller is hue
        assert app.state.manager is manager
        assert app.state.screen_mirror is screen
        assert app.state.audio_mirror is audio
    finally:
        dependencies._hue_controller = originals["hue"]
        dependencies._manager = originals["manager"]
        dependencies._screen_mirror = originals["screen"]
        dependencies._audio_mirror = originals["audio"]
        dependencies.bind_fastapi_app(originals["bound"])
