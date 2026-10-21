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


def test_chat_page_loads_dompurify_with_sri_before_chat_js(
    fastapi_test_client: TestClient,
) -> None:
    html = fastapi_test_client.get("/chat").text
    purify = html.find("cdn.jsdelivr.net/npm/dompurify@3.")
    marked = html.find("cdn.jsdelivr.net/npm/marked@")
    chat_js = html.find('src="/static/chat.js')
    assert purify != -1, "DOMPurify must be loaded from a pinned jsDelivr URL"
    assert marked != -1
    assert purify < chat_js and marked < chat_js


def test_chat_js_sanitizes_markdown_and_never_injects_raw_html(
    fastapi_test_client: TestClient,
) -> None:
    body = fastapi_test_client.get("/static/chat.js").text
    assert "DOMPurify.sanitize(window.marked.parse(" in body
    assert "innerHTML = marked.parse(" not in body
    assert "textContent = text" in body
    assert "${light.name}" not in body


def test_chat_js_renders_approval_card_without_html_injection(
    fastapi_test_client: TestClient,
) -> None:
    body = fastapi_test_client.get("/static/chat.js").text
    assert "case 'approval_required'" in body
    assert "action: 'resume'" in body
    assert "action: 'pending'" in body
    assert "'Aprovar'" in body and "'Rejeitar'" in body
    start = body.index("function renderApprovalCard")
    end = body.index("function sendResume")
    card_code = body[start:end]
    assert "innerHTML" not in card_code
    assert "dd.textContent = summarizeArg(" in card_code


def test_chat_page_busts_cache_for_hitl_js(fastapi_test_client: TestClient) -> None:
    assert 'src="/static/chat.js?v=hitl-1"' in fastapi_test_client.get("/chat").text
