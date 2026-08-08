"""Unit tests for optional API key middleware (protects /api/* only)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from marvin_hue.api.middleware.api_key import ApiKeyMiddleware


def _app(key: str | None) -> FastAPI:
    app = FastAPI()
    app.add_middleware(ApiKeyMiddleware, api_key=key)

    @app.get("/api/secret")
    def secret() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/lights/status")
    def lights_status() -> dict[str, list[object]]:
        return {"lights": []}

    @app.get("/")
    def index() -> dict[str, bool]:
        return {"page": True}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/mirror")
    def mirror_page() -> dict[str, bool]:
        return {"page": True}

    @app.post("/apply")
    def apply() -> dict[str, bool]:
        return {"applied": True}

    return app


def test_no_key_configured_allows_all() -> None:
    client = TestClient(_app(None))
    assert client.get("/api/secret").status_code == 200
    assert client.get("/api/lights/status").status_code == 200

    client = TestClient(_app(""))
    assert client.get("/api/secret").status_code == 200

    client = TestClient(_app("   "))
    assert client.get("/api/secret").status_code == 200


def test_key_required_for_api() -> None:
    client = TestClient(_app("s3cret"))

    r = client.get("/api/secret")
    assert r.status_code == 401
    assert "detail" in r.json()

    assert client.get("/api/secret", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/api/secret", headers={"X-API-Key": "s3cret"}).status_code == 200
    assert (
        client.get(
            "/api/secret", headers={"Authorization": "Bearer s3cret"}
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/api/lights/status", headers={"X-API-Key": "s3cret"}
        ).status_code
        == 200
    )


def test_bearer_case_insensitive_scheme() -> None:
    client = TestClient(_app("s3cret"))
    assert (
        client.get(
            "/api/secret", headers={"Authorization": "bearer s3cret"}
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/api/secret", headers={"Authorization": "BEARER s3cret"}
        ).status_code
        == 200
    )


def test_html_and_non_api_routes_open_when_key_set() -> None:
    client = TestClient(_app("s3cret"))
    assert client.get("/").status_code == 200
    assert client.get("/health").status_code == 200
    assert client.get("/mirror").status_code == 200
    assert client.post("/apply").status_code == 200


def test_x_api_key_takes_precedence_over_authorization() -> None:
    client = TestClient(_app("s3cret"))
    # Wrong X-API-Key should fail even if Bearer is correct
    assert (
        client.get(
            "/api/secret",
            headers={
                "X-API-Key": "wrong",
                "Authorization": "Bearer s3cret",
            },
        ).status_code
        == 401
    )
    # Correct X-API-Key wins
    assert (
        client.get(
            "/api/secret",
            headers={
                "X-API-Key": "s3cret",
                "Authorization": "Bearer wrong",
            },
        ).status_code
        == 200
    )
