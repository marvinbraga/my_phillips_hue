"""Global domain exception handlers: 400 / 404 / 409 / opaque 500."""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from marvin_hue.domain.groups import (
    GroupConflictError,
    GroupNotFoundError,
    GroupValidationError,
)
from marvin_hue.domain.lights import (
    LightConflictError,
    LightNotFoundError,
    LightValidationError,
)
from marvin_hue.services.backup import BackupValidationError


def _client_for(app: FastAPI, *, raise_server_exceptions: bool = True) -> TestClient:
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def test_handlers_registered_on_app() -> None:
    from app import app
    from marvin_hue.api.exception_handlers import register_exception_handlers

    assert LightNotFoundError in app.exception_handlers
    assert LightValidationError in app.exception_handlers
    assert LightConflictError in app.exception_handlers
    assert GroupNotFoundError in app.exception_handlers
    assert GroupValidationError in app.exception_handlers
    assert GroupConflictError in app.exception_handlers
    assert BackupValidationError in app.exception_handlers
    assert Exception in app.exception_handlers
    # Idempotent registration helper exists and is what app.py uses.
    assert callable(register_exception_handlers)


def test_missing_light_via_existing_route_is_404(
    fastapi_test_client: TestClient,
) -> None:
    response = fastapi_test_client.get(
        "/api/lights/00000000-0000-0000-0000-000000000000"
    )
    assert response.status_code == 404
    body = response.json()
    assert "detail" in body


def test_duplicate_light_via_existing_route_is_409(
    fastapi_test_client: TestClient,
) -> None:
    fastapi_test_client.post("/api/lights", json={"name": "HandlerDup"})
    response = fastapi_test_client.post("/api/lights", json={"name": "HandlerDup"})
    assert response.status_code == 409
    assert "detail" in response.json()


def _app_raising(exc: BaseException) -> FastAPI:
    from marvin_hue.api.exception_handlers import register_exception_handlers

    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/raise")
    async def _raise() -> None:
        raise exc

    return app


def test_domain_not_found_handler_returns_404() -> None:
    client = _client_for(_app_raising(LightNotFoundError("lamp gone")))
    response = client.get("/raise")
    assert response.status_code == 404
    assert response.json()["detail"] == "lamp gone"


def test_domain_validation_handler_returns_400() -> None:
    client = _client_for(_app_raising(LightValidationError("bad name")))
    response = client.get("/raise")
    assert response.status_code == 400
    assert response.json()["detail"] == "bad name"


def test_domain_conflict_handler_returns_409_not_400() -> None:
    """LightConflictError subclasses LightValidationError — must stay 409."""
    client = _client_for(_app_raising(LightConflictError("name taken")))
    response = client.get("/raise")
    assert response.status_code == 409
    assert response.json()["detail"] == "name taken"


def test_backup_validation_handler_returns_400() -> None:
    client = _client_for(_app_raising(BackupValidationError("bad zip")))
    response = client.get("/raise")
    assert response.status_code == 400
    assert response.json()["detail"] == "bad zip"


def test_group_errors_map_to_http_status() -> None:
    not_found = _client_for(_app_raising(GroupNotFoundError("no group"))).get("/raise")
    assert not_found.status_code == 404
    invalid = _client_for(_app_raising(GroupValidationError("bad group"))).get("/raise")
    assert invalid.status_code == 400
    conflict = _client_for(_app_raising(GroupConflictError("group exists"))).get(
        "/raise"
    )
    assert conflict.status_code == 409


@pytest.mark.asyncio
async def test_unhandled_exception_handler_is_opaque() -> None:
    from starlette.requests import Request

    from marvin_hue.api.exception_handlers import (
        OPAQUE_500_DETAIL,
        handle_unhandled_exception,
    )

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/secret",
            "headers": [],
            "query_string": b"",
        }
    )
    secret = "internal-secret-token-xyz"
    response = await handle_unhandled_exception(request, RuntimeError(secret))
    assert response.status_code == 500
    payload = json.loads(response.body)
    assert payload["detail"] == OPAQUE_500_DETAIL
    assert secret not in response.body.decode("utf-8")
    assert secret not in json.dumps(payload)


def test_unhandled_exception_via_client_does_not_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marvin_hue.api.exception_handlers import OPAQUE_500_DETAIL

    logger = Mock()
    monkeypatch.setattr(
        "marvin_hue.api.exception_handlers.logger",
        logger,
    )
    app = _app_raising(RuntimeError("stack-trace-should-not-leak"))
    client = _client_for(app, raise_server_exceptions=False)
    response = client.get("/raise")
    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == OPAQUE_500_DETAIL
    assert "stack-trace-should-not-leak" not in response.text
    logger.exception.assert_called()
