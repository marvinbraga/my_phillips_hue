"""WS /ws/mirror must dispatch start/stop/settings through MirrorControlService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.mark.asyncio
async def test_ws_dispatch_start_screen_calls_service_start() -> None:
    from marvin_hue.api.websockets import dispatch_ws_mirror_action

    svc = MagicMock()
    svc.start = AsyncMock(
        return_value={"message": "ok", "status": {"running": True, "mode": "screen"}}
    )

    await dispatch_ws_mirror_action(
        {"action": "start", "mode": "screen", "profile": "cinema", "fps": 12},
        svc,
    )

    svc.start.assert_awaited()
    kwargs = svc.start.await_args.kwargs
    assert svc.start.await_args.args[0] == "screen" or kwargs.get("mode") == "screen"
    assert kwargs.get("profile") == "cinema"
    assert kwargs.get("fps") == 12


@pytest.mark.asyncio
async def test_ws_dispatch_stop_calls_service_stop_not_mirror_stop() -> None:
    from marvin_hue.api.websockets import dispatch_ws_mirror_action

    svc = MagicMock()
    svc.stop = AsyncMock(return_value={"message": "Espelhamento parado"})
    screen = MagicMock()
    audio = MagicMock()

    await dispatch_ws_mirror_action({"action": "stop"}, svc)

    svc.stop.assert_awaited()
    screen.stop.assert_not_called()
    audio.stop.assert_not_called()


@pytest.mark.asyncio
async def test_ws_dispatch_settings_calls_service_apply_settings() -> None:
    from marvin_hue.api.websockets import dispatch_ws_mirror_action

    svc = MagicMock()
    svc.apply_settings = AsyncMock(
        return_value={"message": "ok", "status": {"running": True, "mode": "audio"}}
    )

    await dispatch_ws_mirror_action(
        {
            "action": "settings",
            "mode": "audio",
            "profile": "party",
            "config_name": "relax",
        },
        svc,
    )

    svc.apply_settings.assert_awaited()
    kwargs = svc.apply_settings.await_args.kwargs
    assert kwargs.get("mode") == "audio"
    assert kwargs.get("profile") == "party"
    assert kwargs.get("config_name") == "relax"
    assert kwargs.get("config_name_provided") is True


def test_ws_start_screen_invokes_same_service(
    fastapi_test_client: TestClient,
) -> None:
    from marvin_hue.api import dependencies

    running = {"v": False}

    def _status() -> dict:
        return {
            "running": running["v"],
            "mode": "screen" if running["v"] else None,
            "colors": {},
            "transport": "rest",
        }

    svc = MagicMock()
    svc.unified_status.side_effect = _status

    async def _start(mode: str, **_kwargs: object) -> dict:
        running["v"] = True
        return {"message": "Espelhamento iniciado", "status": _status()}

    svc.start = AsyncMock(side_effect=_start)
    svc.stop = AsyncMock(return_value={"message": "ok"})
    svc.apply_settings = AsyncMock(return_value={"message": "ok", "status": _status()})

    previous = getattr(dependencies, "_mirror_control_service", None)
    dependencies.set_mirror_control_service(svc)
    try:
        with fastapi_test_client.websocket_connect("/ws/mirror") as ws:
            ws.send_json({"action": "start", "mode": "screen", "profile": "cinema"})
            payload = ws.receive_json()
        svc.start.assert_awaited()
        called_mode = svc.start.await_args.kwargs.get("mode")
        if called_mode is None and svc.start.await_args.args:
            called_mode = svc.start.await_args.args[0]
        assert called_mode == "screen"
        assert payload.get("running") is True or payload.get("mode") == "screen"
    finally:
        dependencies.set_mirror_control_service(previous)
