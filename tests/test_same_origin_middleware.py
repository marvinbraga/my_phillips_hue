"""Anti-CSRF: escritas cross-origin do navegador recebem 403.

As rotas da UI (``/apply``, ``/lights/off``, ``DELETE /configurations/...``)
ficam abertas na LAN sem API key; sem checagem de Origin, qualquer página
aberta num navegador da LAN poderia mudar o estado via ``fetch``.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from marvin_hue.api import dependencies
from marvin_hue.api.middleware.origin import (
    CROSS_ORIGIN_DETAIL,
    SameOriginMiddleware,
    explicit_origins,
)

EVIL = {"origin": "http://evil.example"}
SAME = {"origin": "http://testserver"}


def _live_origin_middleware(app: FastAPI) -> SameOriginMiddleware:
    node = app.middleware_stack
    while node is not None:
        if isinstance(node, SameOriginMiddleware):
            return node
        node = getattr(node, "app", None)
    raise AssertionError("SameOriginMiddleware não está na pilha")


def test_cross_origin_delete_is_rejected(fastapi_test_client: TestClient) -> None:
    r = fastapi_test_client.delete("/configurations/relax", headers=EVIL)
    assert r.status_code == 403
    assert r.json() == {"detail": CROSS_ORIGIN_DETAIL}
    assert dependencies.get_manager().get_config("relax") is not None


def test_cross_origin_post_apply_is_rejected(fastapi_test_client: TestClient) -> None:
    r = fastapi_test_client.post(
        "/apply", json={"config_name": "relax", "transition_time_secs": 0}, headers=EVIL
    )
    assert r.status_code == 403
    assert r.json() == {"detail": CROSS_ORIGIN_DETAIL}


def test_cross_origin_post_lights_off_is_rejected(
    fastapi_test_client: TestClient,
) -> None:
    r = fastapi_test_client.post("/lights/off", json={}, headers=EVIL)
    assert r.status_code == 403


def test_null_origin_is_rejected(fastapi_test_client: TestClient) -> None:
    r = fastapi_test_client.delete("/configurations/relax", headers={"origin": "null"})
    assert r.status_code == 403


def test_same_origin_delete_passes(fastapi_test_client: TestClient) -> None:
    r = fastapi_test_client.delete("/configurations/relax", headers=SAME)
    assert r.status_code == 200, r.text
    assert r.json() == {"name": "relax", "deleted": True}


def test_missing_origin_passes(fastapi_test_client: TestClient) -> None:
    """curl/CLI/scripts não mandam Origin."""
    r = fastapi_test_client.delete("/configurations/relax")
    assert r.status_code == 200, r.text


def test_cross_origin_get_is_not_blocked(fastapi_test_client: TestClient) -> None:
    r = fastapi_test_client.get("/configurations", headers=EVIL)
    assert r.status_code == 200


def test_explicitly_listed_origin_may_write(fastapi_test_client: TestClient) -> None:
    from app import app

    fastapi_test_client.get("/configurations")  # monta a pilha de middlewares
    mw = _live_origin_middleware(app)
    original = mw.allowed_origins
    mw.allowed_origins = explicit_origins(["http://evil.example/"])
    try:
        r = fastapi_test_client.delete("/configurations/relax", headers=EVIL)
        assert r.status_code == 200, r.text
    finally:
        mw.allowed_origins = original


def test_cors_preflight_wildcard_does_not_allow_credentials(
    fastapi_test_client: TestClient,
) -> None:
    """Com o default ``*``, o CORS não reflete a origem nem libera credenciais."""
    from marvin_hue.config import settings

    if "*" not in settings.cors_origins:
        pytest.skip("CORS_ORIGINS local não usa '*'")
    r = fastapi_test_client.options(
        "/configurations/relax",
        headers={**EVIL, "access-control-request-method": "DELETE"},
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in r.headers


@pytest.mark.parametrize(
    ("origins", "expected"),
    [
        (["*"], frozenset()),
        (["*", "http://A:1/"], frozenset({"http://a:1"})),
        ([" ", "https://x.example"], frozenset({"https://x.example"})),
    ],
)
def test_explicit_origins_drops_wildcard(origins, expected) -> None:
    assert explicit_origins(origins) == expected


def test_middleware_blocks_only_cross_origin_writes() -> None:
    app = FastAPI()

    @app.get("/x")
    async def get_x() -> dict[str, bool]:
        return {"ok": True}

    @app.put("/x")
    async def put_x() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(SameOriginMiddleware, allowed_origins=["*"])
    client = TestClient(app)
    assert client.get("/x", headers=EVIL).status_code == 200
    assert client.put("/x", headers=EVIL).status_code == 403
    assert client.put("/x", headers=SAME).status_code == 200
    assert client.put("/x").status_code == 200
