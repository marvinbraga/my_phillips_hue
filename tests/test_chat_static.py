"""Chat page loads behavior from /static/chat.js (not an inline <script>)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_chat_page_includes_external_chat_js(fastapi_test_client: TestClient) -> None:
    response = fastapi_test_client.get("/chat")
    assert response.status_code == 200
    html = response.text
    assert 'src="/static/chat.js' in html
    assert 'id="model-badge"' in html
    assert "/api/chat/status" in html
    assert "function connectWebSocket" not in html
    assert "function getSessionId" not in html
    assert "marvin_hue_session_id" not in html


def test_chat_js_is_served_with_session_and_ws(fastapi_test_client: TestClient) -> None:
    response = fastapi_test_client.get("/static/chat.js")
    assert response.status_code == 200
    body = response.text
    assert "marvin_hue_session_id" in body
    assert "/ws/chat" in body
    assert "function getSessionId" in body
    assert "function connectWebSocket" in body
    assert "localStorage" in body
