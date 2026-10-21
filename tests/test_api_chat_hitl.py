"""HITL pelas rotas: POST /api/chat/message|resume, GET /api/chat/pending e /ws/chat.

Agente REAL (create_hue_agent + subagents) com modelo roteirizado e serviços
fake; nada toca a bridge. Os ramos de erro genérico usam um agente stub.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.chat.fakes import START_MIRROR, FakeMirror, HitlRouter, hitl_agent

WS_HEADERS = {"origin": "http://testserver"}


@pytest.fixture
def mirror():
    return FakeMirror()


def _controller():
    controller = MagicMock()
    controller.list_lights.return_value = ["Lâmpada 1"]
    controller.get_lights_status.return_value = []
    return controller


@pytest.fixture
def hitl_client(fastapi_test_client, monkeypatch, mirror):
    from marvin_hue.api import dependencies

    agent = hitl_agent(
        monkeypatch, _controller(), MagicMock(configs=[]), HitlRouter([START_MIRROR]),
        mirror=mirror,
    )
    monkeypatch.setattr(dependencies, "_chat_agent", agent)
    return fastapi_test_client


class _BrokenAgent:
    """Stub cujo agente explode em qualquer chamada (ramos 500 / WS error)."""

    async def ainvoke(self, *a, **k):
        raise RuntimeError("modelo caiu")

    async def aresume(self, *a, **k):
        raise RuntimeError("modelo caiu")

    async def apending(self, *a, **k):
        raise RuntimeError("estado ilegível")

    async def aclear_history(self, *a, **k):
        return None


@pytest.fixture
def broken_client(fastapi_test_client, monkeypatch):
    from marvin_hue.api import dependencies

    monkeypatch.setattr(dependencies, "_chat_agent", _BrokenAgent())
    return fastapi_test_client


@pytest.fixture
def no_agent_client(fastapi_test_client, monkeypatch):
    from marvin_hue.api import dependencies

    monkeypatch.setattr(dependencies, "_chat_agent", None)
    monkeypatch.setattr(dependencies, "_chat_unavailable_reason", "sem agente")
    return fastapi_test_client


def _ask(client, session_id="s1"):
    r = client.post("/api/chat/message", json={"message": "liga", "session_id": session_id})
    assert r.status_code == 200
    return r.json()


def test_rest_message_then_approve(hitl_client, mirror):
    body = _ask(hitl_client)
    assert body["success"] is True and body["session_id"] == "s1"
    assert "response" not in body
    [req] = body["approval_required"]
    assert req["tool"] == "start_mirror" and req["args"] == {"mode": "screen"}
    assert req["allowed_decisions"] == ["approve", "reject"]
    assert req["description"].startswith("Iniciar o espelhamento")
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
    assert hitl_client.get("/api/chat/pending", params={"session_id": "s1"}).json() == {
        "session_id": "s1", "approval_required": [],
    }


def test_rest_reject(hitl_client, mirror):
    rid = _ask(hitl_client)["approval_required"][0]["id"]
    r = hitl_client.post(
        "/api/chat/resume",
        json={"session_id": "s1", "decisions": [{"id": rid, "type": "reject", "message": "não"}]},
    )
    assert r.status_code == 200
    assert "rejeitou" in r.json()["response"]
    assert mirror.start_calls == []


def test_rest_resume_nothing_pending_is_409(hitl_client):
    r = hitl_client.post(
        "/api/chat/resume",
        json={"session_id": "nada", "decisions": [{"id": "x:0", "type": "approve"}]},
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "Nenhuma aprovação pendente nesta sessão."


@pytest.mark.parametrize(
    ("decisions", "detail"),
    [
        (lambda rid: [{"id": "outro:0", "type": "approve"}], "não batem"),
        (lambda rid: [{"id": rid, "type": "approve"}, {"id": rid, "type": "reject"}],
         "repetidas"),
    ],
    ids=["unknown-id", "duplicate-id"],
)
def test_rest_resume_mismatch_is_400(hitl_client, mirror, decisions, detail):
    rid = _ask(hitl_client)["approval_required"][0]["id"]
    r = hitl_client.post(
        "/api/chat/resume", json={"session_id": "s1", "decisions": decisions(rid)}
    )
    assert r.status_code == 400
    assert detail in r.json()["detail"]
    assert mirror.start_calls == []


@pytest.mark.parametrize(
    "decisions",
    [
        [{"type": "approve"}],                    # id obrigatório
        [{"id": "", "type": "approve"}],          # id vazio
        [{"id": "a:0", "type": "edit"}],          # edit não aceito
        [{"id": "a:0", "type": "reject", "message": "x" * 501}],
        [],
    ],
    ids=["no-id", "empty-id", "edit", "long-message", "empty-list"],
)
def test_rest_resume_bad_body_is_422(hitl_client, decisions):
    r = hitl_client.post("/api/chat/resume", json={"session_id": "s1", "decisions": decisions})
    assert r.status_code == 422


def test_rest_resume_and_pending_unavailable(no_agent_client):
    r = no_agent_client.post(
        "/api/chat/resume",
        json={"session_id": "s", "decisions": [{"id": "x:0", "type": "approve"}]},
    )
    assert r.status_code == 503 and r.json()["detail"] == "sem agente"
    r = no_agent_client.get("/api/chat/pending", params={"session_id": "s"})
    assert r.status_code == 503 and r.json()["detail"] == "sem agente"


def test_rest_resume_unexpected_error_is_500(broken_client):
    r = broken_client.post(
        "/api/chat/resume",
        json={"session_id": "s", "decisions": [{"id": "x:0", "type": "approve"}]},
    )
    assert r.status_code == 500
    assert r.json()["detail"] == "Erro ao retomar a conversa: modelo caiu"


def test_rest_message_flag_off_is_unchanged(fastapi_test_client, monkeypatch, mirror):
    from marvin_hue.api import dependencies

    agent = hitl_agent(
        monkeypatch, _controller(), MagicMock(configs=[]), HitlRouter([START_MIRROR]),
        require_approval=False, mirror=mirror,
    )
    monkeypatch.setattr(dependencies, "_chat_agent", agent)
    body = _ask(fastapi_test_client)
    assert set(body) == {"response", "success"}
    assert len(mirror.start_calls) == 1


def test_configure_route_threads_require_approval(fastapi_test_client, monkeypatch):
    import marvin_hue.api.routes.chat as chat_routes
    from marvin_hue.api import dependencies

    seen = {}
    monkeypatch.setattr(chat_routes.settings, "chat_require_approval", True)
    monkeypatch.setattr(
        chat_routes, "create_hue_agent", lambda **kw: seen.update(kw) or object()
    )
    monkeypatch.setattr(dependencies, "_chat_agent", dependencies._chat_agent)
    r = fastapi_test_client.post(
        "/api/chat/configure", json={"provider": "openai", "model": "gpt-4o-mini"}
    )
    assert r.status_code == 200
    assert seen["require_approval"] is True


# --- WebSocket ---------------------------------------------------------------


def test_ws_message_resume_flow(hitl_client, mirror):
    with hitl_client.websocket_connect("/ws/chat", headers=WS_HEADERS) as ws:
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

        # Nada mais pendente: "pending" responde lista vazia.
        ws.send_json({"action": "pending", "session_id": "w1"})
        assert ws.receive_json() == {"type": "approval_required", "requests": []}
    assert len(mirror.start_calls) == 1


def test_ws_resume_errors(hitl_client):
    with hitl_client.websocket_connect("/ws/chat") as ws:
        for bad in ([{"type": "nope", "id": "a:0"}], [{"type": "approve"}], "x"):
            ws.send_json({"action": "resume", "session_id": "w2", "decisions": bad})
            assert ws.receive_json() == {
                "type": "error", "content": "Decisões de aprovação inválidas.",
            }
        ws.send_json({
            "action": "resume", "session_id": "w2",
            "decisions": [{"id": "x:0", "type": "approve"}],
        })
        assert ws.receive_json()["type"] == "typing"
        assert ws.receive_json() == {
            "type": "error", "content": "Nenhuma aprovação pendente nesta sessão.",
        }
        assert ws.receive_json() == {"type": "typing", "content": False}


def test_ws_ignores_non_object_frames(hitl_client):
    with hitl_client.websocket_connect("/ws/chat") as ws:
        ws.send_json(["não", "é", "objeto"])
        ws.send_json("texto")
        ws.send_json({"action": "pending", "session_id": "w3"})
        assert ws.receive_json() == {"type": "approval_required", "requests": []}


def test_ws_generic_errors_are_reported(broken_client):
    with broken_client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"action": "message", "message": "oi", "session_id": "w4"})
        assert ws.receive_json()["type"] == "typing"
        assert ws.receive_json() == {"type": "error", "content": "Erro: modelo caiu"}
        assert ws.receive_json() == {"type": "typing", "content": False}

        ws.send_json({
            "action": "resume", "session_id": "w4",
            "decisions": [{"id": "x:0", "type": "approve"}],
        })
        assert ws.receive_json()["type"] == "typing"
        assert ws.receive_json() == {"type": "error", "content": "Erro: modelo caiu"}
        assert ws.receive_json() == {"type": "typing", "content": False}

        # Falha ao ler o estado: responde "nada pendente" (o cliente destrava).
        ws.send_json({"action": "pending", "session_id": "w4"})
        assert ws.receive_json() == {"type": "approval_required", "requests": []}


def test_ws_pending_without_agent_answers_empty(no_agent_client):
    """A tela Chat manda "pending" ao conectar; sem agente não vira erro na tela."""
    with no_agent_client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"action": "pending", "session_id": "x"})
        assert ws.receive_json() == {"type": "approval_required", "requests": []}
        ws.send_json({"action": "message", "message": "oi", "session_id": "x"})
        assert ws.receive_json() == {"type": "error", "content": "sem agente"}


def test_resume_route_requires_api_key():
    from marvin_hue.api.middleware.api_key import ApiKeyMiddleware
    from marvin_hue.api.routes import chat

    app = FastAPI()
    app.add_middleware(ApiKeyMiddleware, api_key="segredo")
    app.include_router(chat.router)
    client = TestClient(app)
    body = {"session_id": "s", "decisions": [{"id": "x:0", "type": "approve"}]}
    assert client.post("/api/chat/resume", json=body).status_code == 401
    assert client.get("/api/chat/pending").status_code == 401
