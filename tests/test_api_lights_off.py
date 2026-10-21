"""POST /lights/off (issue #9): turn off every enabled light.

Maps the per-light ``ApplyResult`` to HTTP 200 / 207 / 500 like ``/apply``.
Before turning off it stops an active mirror, then takes a fail-open
``lights_off`` snapshot (skipped when every enabled light is already off) so
"Desfazer" restores the lit scene. Open on the LAN path; the ``/api`` alias
honours ``API_KEY``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from marvin_hue import eye_safety
from marvin_hue.api import dependencies
from marvin_hue.api.middleware.api_key import ApiKeyMiddleware
from marvin_hue.apply_result import ApplyResult
from marvin_hue.controllers import HueController
from marvin_hue.services.lights_off import LightsOffBridgeError, LightsOffService
from marvin_hue.services.mirror_control import MirrorNotActiveError

L1 = "Lâmpada 1"
L2 = "Lâmpada 2"


def _bridge_light(controller: HueController, name: str) -> Any:
    light = controller._get_light_by_name(name)
    assert light is not None
    return light


def _off_calls(controller: HueController) -> list[tuple[Any, ...]]:
    """``bridge.set_light`` calls as (light_id, param, value, kwargs)."""
    bridge: Mock = controller.bridge
    return [
        (*c.args, c.kwargs)
        for c in bridge.set_light.call_args_list
        if c.args[1:3] == ("on", False)
    ]


@pytest.fixture
def clean_policy() -> Iterator[None]:
    eye_safety.clear_runtime_policy()
    yield
    eye_safety.clear_runtime_policy()


def _snapshot_sources() -> list[str]:
    """Snapshot sources, newest first."""
    history = dependencies.get_scene_history_service()
    assert history is not None
    return [s.source for s in asyncio.run(history.list_recent(limit=50))]


# --- happy path / params -------------------------------------------------


def test_lights_off_all_ok_returns_200(
    fastapi_test_client: TestClient,
    mock_hue_controller: HueController,
    clean_policy: None,
) -> None:
    response = fastapi_test_client.post("/lights/off", json={"transition_time_secs": 1})

    assert response.status_code == 200
    assert response.json() == {
        "message": "Lâmpadas desligadas",
        "applied": [L1, L2],
        "failed": [],
        "details": {"config_name": "lights_off", "transition_time_secs": 1.0},
    }
    assert _bridge_light(mock_hue_controller, L1).on is False
    assert _off_calls(mock_hue_controller) == [
        (1, "on", False, {"transitiontime": 10}),
        (2, "on", False, {"transitiontime": 10}),
    ]
    # One-shot transition: the persistent phue attribute is never mutated.
    assert _bridge_light(mock_hue_controller, L1).transitiontime is None
    assert _bridge_light(mock_hue_controller, L2).transitiontime is None


def test_lights_off_without_body_uses_one_second_default(
    fastapi_test_client: TestClient,
    mock_hue_controller: HueController,
    clean_policy: None,
) -> None:
    response = fastapi_test_client.post("/lights/off")

    assert response.status_code == 200
    body = response.json()
    assert body["details"] == {"config_name": "lights_off", "transition_time_secs": 1.0}
    assert body["applied"] == [L1, L2]
    assert _off_calls(mock_hue_controller) == [
        (1, "on", False, {"transitiontime": 10}),
        (2, "on", False, {"transitiontime": 10}),
    ]
    assert _bridge_light(mock_hue_controller, L1).on is False
    assert _snapshot_sources() == ["lights_off"]


@pytest.mark.parametrize("value", [-1, 61])
def test_lights_off_rejects_out_of_range_transition(
    fastapi_test_client: TestClient,
    mock_hue_controller: HueController,
    value: int,
) -> None:
    response = fastapi_test_client.post(
        "/lights/off", json={"transition_time_secs": value}
    )

    assert response.status_code == 422
    assert _off_calls(mock_hue_controller) == []
    assert _bridge_light(mock_hue_controller, L1).on is True


def test_lights_off_zero_transition_sends_no_transitiontime(
    fastapi_test_client: TestClient,
    mock_hue_controller: HueController,
    clean_policy: None,
) -> None:
    response = fastapi_test_client.post("/lights/off", json={"transition_time_secs": 0})

    assert response.status_code == 200
    assert response.json()["details"]["transition_time_secs"] == 0.0
    assert _off_calls(mock_hue_controller) == [
        (1, "on", False, {}),
        (2, "on", False, {}),
    ]


def test_lights_off_max_transition_accepted(
    fastapi_test_client: TestClient,
    mock_hue_controller: HueController,
    clean_policy: None,
) -> None:
    response = fastapi_test_client.post(
        "/lights/off", json={"transition_time_secs": 60}
    )

    assert response.status_code == 200
    assert _off_calls(mock_hue_controller)[0] == (
        1,
        "on",
        False,
        {"transitiontime": 600},
    )


# --- partial / failure ----------------------------------------------------


def test_lights_off_partial_returns_207(
    fastapi_test_client: TestClient,
    mock_hue_controller: HueController,
    monkeypatch: pytest.MonkeyPatch,
    clean_policy: None,
) -> None:
    original = mock_hue_controller.turn_off_with_transition

    def flaky(name: str, tenths: int) -> bool:
        if name == L2:
            raise RuntimeError("boom")
        return original(name, tenths)

    monkeypatch.setattr(mock_hue_controller, "turn_off_with_transition", flaky)

    response = fastapi_test_client.post("/lights/off", json={})

    assert response.status_code == 207
    assert response.json() == {
        "message": "Lâmpadas desligadas parcialmente; algumas lâmpadas falharam",
        "applied": [L1],
        "failed": [{"name": L2, "error": "boom"}],
        "details": {"config_name": "lights_off", "transition_time_secs": 1.0},
    }


def test_lights_off_all_failed_returns_500(
    fastapi_test_client: TestClient,
    mock_hue_controller: HueController,
    monkeypatch: pytest.MonkeyPatch,
    clean_policy: None,
) -> None:
    def broken(name: str, tenths: int) -> bool:
        raise RuntimeError(f"down {name}")

    monkeypatch.setattr(mock_hue_controller, "turn_off_with_transition", broken)

    response = fastapi_test_client.post("/lights/off", json={})

    assert response.status_code == 500
    body = response.json()
    assert body["message"] == "Falha ao desligar as lâmpadas; nenhuma lâmpada desligada"
    assert body["applied"] == []
    assert body["failed"] == [
        {"name": L1, "error": f"down {L1}"},
        {"name": L2, "error": f"down {L2}"},
    ]


def test_lights_off_turn_off_false_counts_as_failed(
    fastapi_test_client: TestClient,
    mock_hue_controller: HueController,
    monkeypatch: pytest.MonkeyPatch,
    clean_policy: None,
) -> None:
    monkeypatch.setattr(
        mock_hue_controller, "turn_off_with_transition", lambda name, tenths: False
    )

    response = fastapi_test_client.post("/lights/off", json={})

    assert response.status_code == 500
    assert response.json()["failed"] == [
        {"name": L1, "error": "Lâmpada não encontrada ou desabilitada"},
        {"name": L2, "error": "Lâmpada não encontrada ou desabilitada"},
    ]


def test_lights_off_bridge_error_reply_counts_as_failed(
    fastapi_test_client: TestClient,
    mock_hue_controller: HueController,
    clean_policy: None,
) -> None:
    bridge: Mock = mock_hue_controller.bridge
    bridge.set_light.side_effect = lambda *a, **k: [
        [{"error": {"description": "device is set to off"}}]
    ]

    response = fastapi_test_client.post("/lights/off", json={})

    assert response.status_code == 500
    assert response.json()["failed"] == [
        {"name": L1, "error": "device is set to off"},
        {"name": L2, "error": "device is set to off"},
    ]


def test_lights_off_status_failure_returns_documented_500(
    fastapi_test_client: TestClient,
    mock_hue_controller: HueController,
    monkeypatch: pytest.MonkeyPatch,
    clean_policy: None,
) -> None:
    def bridge_down() -> list[dict[str, Any]]:
        raise OSError("bridge unreachable")

    monkeypatch.setattr(mock_hue_controller, "get_lights_status", bridge_down)

    response = fastapi_test_client.post("/lights/off", json={})

    assert response.status_code == 500
    assert response.json() == {
        "message": "Bridge indisponível; nenhuma lâmpada desligada",
        "applied": [],
        "failed": [
            {"name": L1, "error": "bridge unreachable"},
            {"name": L2, "error": "bridge unreachable"},
        ],
        "details": {"config_name": "lights_off", "transition_time_secs": 1.0},
    }
    assert _off_calls(mock_hue_controller) == []
    assert _snapshot_sources() == []


def test_lights_off_list_failure_returns_documented_500(
    fastapi_test_client: TestClient,
    mock_hue_controller: HueController,
    monkeypatch: pytest.MonkeyPatch,
    clean_policy: None,
) -> None:
    def broken_list() -> list[str]:
        raise OSError("no inventory")

    monkeypatch.setattr(mock_hue_controller, "list_lights", broken_list)

    response = fastapi_test_client.post("/lights/off", json={})

    assert response.status_code == 500
    assert response.json() == {
        "message": "Bridge indisponível; nenhuma lâmpada desligada",
        "applied": [],
        "failed": [],
        "details": {"config_name": "lights_off", "transition_time_secs": 1.0},
    }


# --- enabled_for_app / empty ---------------------------------------------


def test_lights_off_skips_disabled_light(
    fastapi_test_client: TestClient,
    mock_hue_controller: HueController,
    clean_policy: None,
) -> None:
    lamp2 = _bridge_light(mock_hue_controller, L2)
    lamp2.on = True
    eye_safety.set_runtime_policy(limits_pct={}, disabled_names={L2})

    response = fastapi_test_client.post("/lights/off", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["applied"] == [L1]
    assert body["failed"] == []
    assert lamp2.on is True
    assert [c[0] for c in _off_calls(mock_hue_controller)] == [1]


def test_lights_off_no_enabled_lights_returns_200_with_message(
    fastapi_test_client: TestClient,
    mock_hue_controller: HueController,
    clean_policy: None,
) -> None:
    eye_safety.set_runtime_policy(limits_pct={}, disabled_names={L1, L2})

    response = fastapi_test_client.post("/lights/off", json={})

    assert response.status_code == 200
    assert response.json() == {
        "message": "Nenhuma lâmpada habilitada para desligar",
        "applied": [],
        "failed": [],
        "details": {"config_name": "lights_off", "transition_time_secs": 1.0},
    }
    assert _snapshot_sources() == []
    assert _off_calls(mock_hue_controller) == []


# --- snapshot / undo ------------------------------------------------------


def test_lights_off_exact_call_order(
    fastapi_test_client: TestClient,
    mock_hue_controller: HueController,
    monkeypatch: pytest.MonkeyPatch,
    clean_policy: None,
) -> None:
    calls: list[str] = []
    history = dependencies.get_scene_history_service()
    assert history is not None
    original_snapshot_status = history.snapshot_status
    original_status = mock_hue_controller.get_lights_status
    original_off = mock_hue_controller.turn_off_with_transition

    async def spy_snapshot_status(
        status: list[dict[str, Any]], *, source: str, label: str | None = None
    ) -> Any:
        calls.append(f"snapshot:{source}:{label}")
        return await original_snapshot_status(status, source=source, label=label)

    def spy_status() -> list[dict[str, Any]]:
        calls.append("status")
        return original_status()

    def spy_off(name: str, tenths: int) -> bool:
        calls.append(f"off:{name}:{tenths}")
        return original_off(name, tenths)

    monkeypatch.setattr(history, "snapshot_status", spy_snapshot_status)
    monkeypatch.setattr(mock_hue_controller, "get_lights_status", spy_status)
    monkeypatch.setattr(mock_hue_controller, "turn_off_with_transition", spy_off)

    response = fastapi_test_client.post("/lights/off", json={})

    assert response.status_code == 200
    assert calls == [
        "status",
        "snapshot:lights_off:before lights off",
        f"off:{L1}:10",
        f"off:{L2}:10",
    ]


def test_lights_off_snapshot_failure_does_not_block(
    fastapi_test_client: TestClient,
    mock_hue_controller: HueController,
    monkeypatch: pytest.MonkeyPatch,
    clean_policy: None,
) -> None:
    history = dependencies.get_scene_history_service()
    assert history is not None

    async def broken_snapshot(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("db locked")

    monkeypatch.setattr(history, "snapshot_status", broken_snapshot)

    response = fastapi_test_client.post("/lights/off", json={})

    assert response.status_code == 200
    assert response.json()["applied"] == [L1, L2]
    assert _bridge_light(mock_hue_controller, L1).on is False


def test_lights_off_then_undo_restores_lit_scene(
    fastapi_test_client: TestClient,
    mock_hue_controller: HueController,
    clean_policy: None,
) -> None:
    lamp1 = _bridge_light(mock_hue_controller, L1)
    assert fastapi_test_client.post("/lights/off", json={}).status_code == 200
    assert lamp1.on is False

    undo = fastapi_test_client.post("/api/history/undo")

    assert undo.status_code == 200
    assert undo.json()["source"] == "lights_off"
    assert lamp1.on is True
    assert _bridge_light(mock_hue_controller, L2).on is False


def test_lights_off_twice_takes_one_snapshot_and_undo_restores_lit(
    fastapi_test_client: TestClient,
    mock_hue_controller: HueController,
    clean_policy: None,
) -> None:
    assert fastapi_test_client.post("/lights/off", json={}).status_code == 200
    second = fastapi_test_client.post("/lights/off", json={})

    assert second.status_code == 200
    assert second.json()["applied"] == [L1, L2]
    assert _snapshot_sources() == ["lights_off"]

    undo = fastapi_test_client.post("/api/history/undo")

    assert undo.status_code == 200
    assert _bridge_light(mock_hue_controller, L1).on is True


# --- active mirror ----------------------------------------------------------


def test_lights_off_stops_running_mirror_first(
    fastapi_test_client: TestClient,
    mock_hue_controller: HueController,
    mock_screen_mirror: Mock,
    clean_policy: None,
) -> None:
    mock_screen_mirror.is_running.return_value = True

    response = fastapi_test_client.post("/lights/off", json={})

    assert response.status_code == 200
    mock_screen_mirror.stop.assert_called_once_with(end_output=False)
    # lights_off is the newest snapshot, so undo restores the post-mirror scene.
    assert _snapshot_sources() == ["lights_off", "mirror_stop"]
    assert _bridge_light(mock_hue_controller, L1).on is False


def test_lights_off_does_not_touch_idle_mirror(
    fastapi_test_client: TestClient,
    mock_screen_mirror: Mock,
    mock_audio_mirror: Mock,
    clean_policy: None,
) -> None:
    response = fastapi_test_client.post("/lights/off", json={})

    assert response.status_code == 200
    mock_screen_mirror.stop.assert_not_called()
    mock_audio_mirror.stop.assert_not_called()
    assert _snapshot_sources() == ["lights_off"]


class _FakeMirror:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.stopped = 0

    async def stop(self) -> dict[str, Any]:
        self.stopped += 1
        if self.error is not None:
            raise self.error
        return {"message": "Espelhamento parado"}


class _FakeHistory:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def snapshot_status(
        self, status: list[dict[str, Any]], *, source: str, label: str | None = None
    ) -> Any:
        self.calls.append((source, label))
        return None


@pytest.mark.parametrize(
    "error", [MirrorNotActiveError("idle"), RuntimeError("dtls stuck")]
)
def test_service_mirror_stop_failure_is_fail_open(
    mock_hue_controller: HueController,
    clean_policy: None,
    error: Exception,
) -> None:
    mirror = _FakeMirror(error)
    history = _FakeHistory()
    service = LightsOffService(mock_hue_controller, history, mirror=mirror)

    result = asyncio.run(service.turn_off_all(transition_time=0))

    assert mirror.stopped == 1
    assert result == ApplyResult(applied=(L1, L2), failed=())
    assert history.calls == [("lights_off", "before lights off")]


def test_service_without_history_or_mirror(
    mock_hue_controller: HueController,
    clean_policy: None,
) -> None:
    service = LightsOffService(mock_hue_controller)
    result = asyncio.run(service.turn_off_all(transition_time=0))
    assert result == ApplyResult(applied=(L1, L2), failed=())


def test_service_skips_snapshot_when_all_enabled_already_off(
    mock_hue_controller: HueController,
    clean_policy: None,
) -> None:
    _bridge_light(mock_hue_controller, L1).on = False
    history = _FakeHistory()
    service = LightsOffService(mock_hue_controller, history)

    result = asyncio.run(service.turn_off_all(transition_time=0))

    assert result.ok
    assert history.calls == []


def test_service_snapshot_ignores_lit_disabled_light(
    mock_hue_controller: HueController,
    clean_policy: None,
) -> None:
    """A lit but app-disabled light is not ours to turn off: no snapshot."""
    _bridge_light(mock_hue_controller, L1).on = False
    _bridge_light(mock_hue_controller, L2).on = True
    eye_safety.set_runtime_policy(limits_pct={}, disabled_names={L2})
    history = _FakeHistory()
    service = LightsOffService(mock_hue_controller, history)

    asyncio.run(service.turn_off_all(transition_time=0))

    assert history.calls == []


def test_service_list_failure_raises_domain_error(
    mock_hue_controller: HueController,
    monkeypatch: pytest.MonkeyPatch,
    clean_policy: None,
) -> None:
    def broken_list() -> list[str]:
        raise OSError("no inventory")

    monkeypatch.setattr(mock_hue_controller, "list_lights", broken_list)
    service = LightsOffService(mock_hue_controller)

    with pytest.raises(LightsOffBridgeError) as exc_info:
        asyncio.run(service.turn_off_all(transition_time=0))
    assert exc_info.value.light_names == ()


# --- routing / API key ------------------------------------------------------


def test_production_app_registers_lights_off_alias() -> None:
    from app import app

    methods: dict[str, set[str]] = {}
    for route in app.routes:
        path = getattr(route, "path", None)
        route_methods = getattr(route, "methods", None)
        if path and route_methods:
            methods.setdefault(path, set()).update(route_methods)

    assert "POST" in methods["/lights/off"]
    assert "POST" in methods["/api/lights/off"]


def test_api_lights_off_alias_matches_lan(
    fastapi_test_client: TestClient,
    clean_policy: None,
) -> None:
    lan = fastapi_test_client.post("/lights/off", json={})
    api = fastapi_test_client.post("/api/lights/off", json={})
    assert lan.status_code == 200
    assert api.status_code == 200
    assert api.json() == lan.json()
    assert api.json()["applied"] == [L1, L2]
    assert api.json()["failed"] == []


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


def test_lights_off_api_key_boundary(
    fastapi_test_client: TestClient,
    clean_policy: None,
) -> None:
    from app import app as fastapi_app

    fastapi_test_client.get("/configurations")
    mw = _live_api_key_middleware(fastapi_app)
    original = mw._api_key
    mw._api_key = "s3cret"
    try:
        assert fastapi_test_client.post("/lights/off", json={}).status_code == 200

        missing = fastapi_test_client.post("/api/lights/off", json={})
        assert missing.status_code == 401
        assert "detail" in missing.json()

        wrong = fastapi_test_client.post(
            "/api/lights/off", json={}, headers={"X-API-Key": "wrong"}
        )
        assert wrong.status_code == 401

        ok = fastapi_test_client.post(
            "/api/lights/off", json={}, headers={"X-API-Key": "s3cret"}
        )
        assert ok.status_code == 200
    finally:
        mw._api_key = original
