"""POST /apply maps ApplyResult to HTTP 200 / 207 / 500.

Does not treat duration_minutes as a scheduled restore timer.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from marvin_hue.apply_result import ApplyResult
from marvin_hue.controllers import HueController


def _first_config_name(client: TestClient) -> str:
    configs = client.get("/configurations").json()
    assert configs, "expected at least one setup in the test manager"
    return str(configs[0]["name"])


def _stub_apply(
    controller: HueController,
    monkeypatch: pytest.MonkeyPatch,
    result: ApplyResult,
) -> None:
    monkeypatch.setattr(
        controller,
        "apply_light_config",
        Mock(return_value=result),
    )


def test_apply_ok_returns_200_with_applied_and_empty_failed(
    fastapi_test_client: TestClient,
    mock_hue_controller: HueController,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_apply(
        mock_hue_controller,
        monkeypatch,
        ApplyResult(applied=("A",), failed=()),
    )
    name = _first_config_name(fastapi_test_client)
    response = fastapi_test_client.post("/apply", json={"config_name": name})

    assert response.status_code == 200
    body = response.json()
    assert body["applied"] == ["A"]
    assert body["failed"] == []
    assert "message" in body


def test_apply_partial_returns_207_with_applied_and_failed(
    fastapi_test_client: TestClient,
    mock_hue_controller: HueController,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_apply(
        mock_hue_controller,
        monkeypatch,
        ApplyResult(applied=("A",), failed=(("B", "boom"),)),
    )
    name = _first_config_name(fastapi_test_client)
    response = fastapi_test_client.post("/apply", json={"config_name": name})

    assert response.status_code == 207
    body = response.json()
    assert body["applied"] == ["A"]
    assert body["failed"] == [{"name": "B", "error": "boom"}]
    message = str(body.get("message", "")).lower()
    assert "fail" in message or "parcial" in message


def test_apply_all_failed_returns_500_with_applied_and_failed(
    fastapi_test_client: TestClient,
    mock_hue_controller: HueController,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_apply(
        mock_hue_controller,
        monkeypatch,
        ApplyResult(applied=(), failed=(("B", "boom"),)),
    )
    name = _first_config_name(fastapi_test_client)
    response = fastapi_test_client.post("/apply", json={"config_name": name})

    assert response.status_code == 500
    body = response.json()
    assert body["applied"] == []
    assert body["failed"] == [{"name": "B", "error": "boom"}]


def test_apply_duration_minutes_is_not_echoed_as_scheduled(
    fastapi_test_client: TestClient,
    mock_hue_controller: HueController,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_apply(
        mock_hue_controller,
        monkeypatch,
        ApplyResult(applied=("A",), failed=()),
    )
    name = _first_config_name(fastapi_test_client)
    response = fastapi_test_client.post(
        "/apply",
        json={"config_name": name, "duration_minutes": 30.0},
    )

    assert response.status_code == 200
    body = response.json()
    assert "duration_minutes" not in body
    details = body.get("details") or {}
    assert "duration_minutes" not in details


def test_apply_missing_config_returns_404(fastapi_test_client: TestClient) -> None:
    response = fastapi_test_client.post(
        "/apply", json={"config_name": "nonexistent_config_xyz"}
    )
    assert response.status_code == 404
    assert "detail" in response.json()
