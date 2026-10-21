"""HITL pelas rotas: POST /api/chat/message|resume, GET /api/chat/pending e /ws/chat.

Agente REAL (create_hue_agent + subagents) com modelo roteirizado e serviços
fake; nada toca a bridge.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.chat.fakes import FakeMirror
from tests.chat.test_hitl_flow import START_MIRROR, Router, _agent


@pytest.fixture
def mirror():
    return FakeMirror()


@pytest.fixture
def hitl_client(fastapi_test_client, monkeypatch, mirror):
    from unittest.mock import MagicMock

    from marvin_hue.api import dependencies

    controller = MagicMock()
    controller.list_lights.return_value = ["Lâmpada 1"]
    controller.get_lights_status.return_value = []
    manager = MagicMock()
    manager.configs = []
    agent = _agent(monkeypatch, controller, manager, Router(START_MIRROR), mirror=mirror)
    monkeypatch.setattr(dependencies, "_chat_agent", agent)
    return fastapi_test_client


def test_rest_message_then_approve(hitl_client, mirror):
    r = hitl_client.post("/api/chat/message", json={"message": "liga", "session_id": "s1"})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True and body["session_id"] == "s1"
    assert "response" not in body
    [req] = body["approval_required"]
    assert req["tool"] == "start_mirror" and req["args"] == {"mode": "screen"}
    assert req["allowed_decisions"] == ["approve", "reject"]
    assert mirror.start_calls == []

    pending = hitl_client.get("/api/chat/pending", params={"session_id": "s1"}).json()
    assert [p["id"] for p in pending["approval_required"]] == [req["id"]]

    r = hitl_client.post(
        "/api/chat/resume",
        json={"session_id": "s1", "decisions": [{"id": req["id"], "type": "approve"}]},
    )
    assert r.status_code == 200
    assert r.json()["response"].startswith("fim:")
    assert len(mirror.start_calls) == 1
    assert hitl_client.get("/api/chat/pending", params={"session_id": "s1"}).json()[
        "approval_required"
    ] == []


def test_rest_reject(hitl_client, mirror):
    hitl_client.post("/api/chat/message", json={"message": "liga", "session_id": "s1"})
    r = hitl_client.post(
        "/api/chat/resume",
        json={"session_id": "s1", "decisions": [{"type": "reject", "message": "não"}]},
    )
    assert r.status_code == 200
    assert "rejeitou" in r.json()["response"]
    assert mirror.start_calls == []


def test_rest_resume_errors(hitl_client):
    r = hitl_client.post(
        "/api/chat/resume", json={"session_id": "nada", "decisions": [{"type": "approve"}]}
    )
    assert r.status_code == 409

    hitl_client.post("/api/chat/message", json={"message": "liga", "session_id": "s1"})
    r = hitl_client.post(
        "/api/chat/resume",
        json={"session_id": "s1", "decisions": [{"type": "approve"}, {"type": "reject"}]},
    )
    assert r.status_code == 400
    # "edit" não é aceito pela API (o middleware aceitaria trocar o NOME da tool).
    r = hitl_client.post(
        "/api/chat/resume", json={"session_id": "s1", "decisions": [{"type": "edit"}]}
    )
    assert r.status_code == 422
    r = hitl_client.post("/api/chat/resume", json={"session_id": "s1", "decisions": []})
    assert r.status_code == 422


def test_rest_resume_unavailable(fastapi_test_client, monkeypatch):
    from marvin_hue.api import dependencies

    monkeypatch.setattr(dependencies, "_chat_agent", None)
    r = fastapi_test_client.post(
        "/api/chat/resume", json={"session_id": "s", "decisions": [{"type": "approve"}]}
    )
    assert r.status_code == 503


def test_rest_message_flag_off_is_unchanged(fastapi_test_client, monkeypatch, mirror):
    from unittest.mock import MagicMock

    from marvin_hue.api import dependencies

    agent = _agent(
        monkeypatch, MagicMock(), MagicMock(configs=[]), Router(START_MIRROR),
        require_approval=False, mirror=mirror,
    )
    monkeypatch.setattr(dependencies, "_chat_agent", agent)
    r = fastapi_test_client.post("/api/chat/message", json={"message": "liga", "session_id": "s"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"response", "success"}
    assert len(mirror.start_calls) == 1


def test_ws_message_resume_flow(hitl_client, mirror):
    with hitl_client.websocket_connect("/ws/chat", headers={"origin": "http://testserver"}) as ws:
        ws.send_json({"action": "message", "message": "liga", "session_id": "w1"})
        assert ws.receive_json() == {"type": "typing", "content": True}
        frame = ws.receive_json()
        assert frame["type"] == "approval_required"
        [req] = frame["requests"]
        assert req["tool"] == "start_mirror"
        assert ws.receive_json() == {"type": "typing", "content": False}

        # Página recarregada: "pending" reapresenta o pedido.
        ws.send_json({"action": "pending", "session_id": "w1"})
        assert ws.receive_json()["requests"][0]["id"] == req["id"]

        ws.send_json({
            "action": "resume", "session_id": "w1",
            "decisions": [{"id": req["id"], "type": "approve"}],
        })
        assert ws.receive_json() == {"type": "typing", "content": True}
        done = ws.receive_json()
        assert done["type"] == "response" and done["content"].startswith("fim:")
        assert ws.receive_json() == {"type": "typing", "content": False}
    assert len(mirror.start_calls) == 1


def test_ws_resume_errors(hitl_client):
    with hitl_client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"action": "resume", "session_id": "w2", "decisions": [{"type": "nope"}]})
        assert ws.receive_json() == {
            "type": "error", "content": "Decisões de aprovação inválidas.",
        }
        ws.send_json({"action": "resume", "session_id": "w2", "decisions": [{"type": "approve"}]})
        assert ws.receive_json()["type"] == "typing"
        err = ws.receive_json()
        assert err["type"] == "error" and "Nenhuma aprovação pendente" in err["content"]
        assert ws.receive_json() == {"type": "typing", "content": False}

        # Sem pendência, "pending" não responde nada; o próximo frame é do clear.
        ws.send_json({"action": "pending", "session_id": "w2"})
        ws.send_json({"action": "clear", "session_id": "w2"})
        assert ws.receive_json()["type"] == "cleared"


def test_ws_pending_is_silent_without_agent(fastapi_test_client, monkeypatch):
    """A tela Chat manda "pending" ao conectar; sem agente não vira erro na tela."""
    from marvin_hue.api import dependencies

    monkeypatch.setattr(dependencies, "_chat_agent", None)
    monkeypatch.setattr(dependencies, "_chat_unavailable_reason", "sem agente")
    with fastapi_test_client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"action": "pending", "session_id": "x"})
        ws.send_json({"action": "message", "message": "oi", "session_id": "x"})
        assert ws.receive_json() == {"type": "error", "content": "sem agente"}


def test_resume_route_requires_api_key():
    from marvin_hue.api.middleware.api_key import ApiKeyMiddleware
    from marvin_hue.api.routes import chat

    app = FastAPI()
    app.add_middleware(ApiKeyMiddleware, api_key="segredo")
    app.include_router(chat.router)
    client = TestClient(app)
    body = {"session_id": "s", "decisions": [{"type": "approve"}]}
    assert client.post("/api/chat/resume", json=body).status_code == 401
    assert client.get("/api/chat/pending").status_code == 401
