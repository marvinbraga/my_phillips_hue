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
        client.get("/api/lights/status", headers={"X-API-Key": "s3cret"}).status_code
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


def _live_api_key_middleware(app: FastAPI) -> ApiKeyMiddleware:
    stack = app.middleware_stack
    seen: set[int] = set()
    while stack is not None and id(stack) not in seen:
        seen.add(id(stack))
        if isinstance(stack, ApiKeyMiddleware):
            return stack
        inner = getattr(stack, "app", None)
        if inner is stack:
            break
        stack = inner
    raise AssertionError("ApiKeyMiddleware not found on app")


def test_unprefixed_apply_open_when_api_key_set(
    fastapi_test_client: TestClient,
) -> None:
    from app import app as fastapi_app

    fastapi_test_client.get("/configurations")
    mw = _live_api_key_middleware(fastapi_app)
    original = mw._api_key
    mw._api_key = "s3cret"
    try:
        configs = fastapi_test_client.get("/configurations").json()
        assert configs
        payload = {"config_name": configs[0]["name"]}
        response = fastapi_test_client.post("/apply", json=payload)
        assert response.status_code in (200, 207)
        missing = fastapi_test_client.post(
            "/apply", json={"config_name": "nonexistent_config_xyz"}
        )
        assert missing.status_code == 404
    finally:
        mw._api_key = original


def test_api_apply_requires_key_when_configured(
    fastapi_test_client: TestClient,
) -> None:
    from app import app as fastapi_app

    fastapi_test_client.get("/configurations")
    mw = _live_api_key_middleware(fastapi_app)
    original = mw._api_key
    mw._api_key = "s3cret"
    try:
        configs = fastapi_test_client.get("/configurations").json()
        payload = {"config_name": configs[0]["name"]}

        missing = fastapi_test_client.post("/api/apply", json=payload)
        assert missing.status_code == 401
        assert "detail" in missing.json()

        wrong = fastapi_test_client.post(
            "/api/apply", json=payload, headers={"X-API-Key": "wrong"}
        )
        assert wrong.status_code == 401

        ok = fastapi_test_client.post(
            "/api/apply", json=payload, headers={"X-API-Key": "s3cret"}
        )
        assert ok.status_code in (200, 207)

        not_found = fastapi_test_client.post(
            "/api/apply",
            json={"config_name": "nonexistent_config_xyz"},
            headers={"X-API-Key": "s3cret"},
        )
        assert not_found.status_code == 404
    finally:
        mw._api_key = original


def test_api_mirror_and_positions_aliases_require_key(
    fastapi_test_client: TestClient,
) -> None:
    from app import app as fastapi_app

    fastapi_test_client.get("/mirror/status")
    mw = _live_api_key_middleware(fastapi_app)
    original = mw._api_key
    mw._api_key = "s3cret"
    try:
        assert fastapi_test_client.get("/mirror/status").status_code == 200
        assert fastapi_test_client.get("/positions").status_code == 200

        assert fastapi_test_client.get("/api/mirror/status").status_code == 401
        assert fastapi_test_client.get("/api/positions").status_code == 401

        headers = {"X-API-Key": "s3cret"}
        assert (
            fastapi_test_client.get("/api/mirror/status", headers=headers).status_code
            == 200
        )
        assert (
            fastapi_test_client.get("/api/positions", headers=headers).status_code
            == 200
        )
    finally:
        mw._api_key = original
