"""/ws/chat recusa conexões cross-origin (Gate 8 #16, item 7).

O chat é um canal com privilégio total (luzes, cenas, agendamentos); sem
checagem de Origin, qualquer página aberta no navegador da LAN poderia abrir o
WebSocket e comandar o agente (CSWSH).
"""
from __future__ import annotations

import pytest
from starlette.websockets import WebSocketDisconnect


def test_cross_origin_is_rejected(fastapi_test_client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with fastapi_test_client.websocket_connect(
            "/ws/chat", headers={"origin": "http://evil.example"}
        ) as ws:
            ws.receive_json()
    assert exc.value.code == 1008


def test_same_origin_is_accepted(fastapi_test_client, monkeypatch):
    from marvin_hue.api import dependencies

    monkeypatch.setattr(dependencies, "_chat_agent", None)
    monkeypatch.setattr(dependencies, "_chat_unavailable_reason", "sem agente")
    with fastapi_test_client.websocket_connect(
        "/ws/chat", headers={"origin": "http://testserver"}
    ) as ws:
        ws.send_json({"action": "message", "message": "oi"})
        assert ws.receive_json() == {"type": "error", "content": "sem agente"}


def test_missing_origin_is_accepted(fastapi_test_client, monkeypatch):
    """Clientes fora do navegador (CLI, scripts) não mandam Origin."""
    from marvin_hue.api import dependencies

    monkeypatch.setattr(dependencies, "_chat_agent", None)
    monkeypatch.setattr(dependencies, "_chat_unavailable_reason", "sem agente")
    with fastapi_test_client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"action": "message", "message": "oi"})
        assert ws.receive_json()["type"] == "error"


@pytest.mark.parametrize(
    ("origin", "host", "ok"),
    [
        ("http://192.168.0.10:5081", "192.168.0.10:5081", True),
        ("https://hue.local", "hue.local", True),
        ("http://192.168.0.10:9999", "192.168.0.10:5081", False),
        ("null", "192.168.0.10:5081", False),
        (None, "192.168.0.10:5081", True),
    ],
)
def test_origin_allowed(origin, host, ok):
    from marvin_hue.api.websockets import origin_allowed

    assert origin_allowed(origin, host) is ok
