"""#25: sem imagens externas no chat (DOMPurify) + CSP img-src nas páginas HTML."""
from __future__ import annotations

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.testclient import TestClient

from marvin_hue.api.middleware.csp import CSP_POLICY, ContentSecurityPolicyMiddleware


@pytest.mark.parametrize("path", ["/", "/chat", "/lights", "/mirror"])
def test_html_pages_carry_img_src_csp(fastapi_test_client: TestClient, path: str) -> None:
    r = fastapi_test_client.get(path)
    assert r.status_code == 200
    assert r.headers["content-security-policy"] == "img-src 'self' data:"


def test_json_and_static_responses_have_no_csp(fastapi_test_client: TestClient) -> None:
    assert "content-security-policy" not in fastapi_test_client.get("/api/chat/status").headers
    assert "content-security-policy" not in fastapi_test_client.get("/static/chat.js").headers


def test_favicon_is_same_origin_so_csp_allows_it(fastapi_test_client: TestClient) -> None:
    html = fastapi_test_client.get("/chat").text
    assert 'href="/static/favicon.png"' in html
    assert "<img" not in html


def test_middleware_keeps_existing_policy_and_skips_websockets() -> None:
    app = FastAPI()
    app.add_middleware(ContentSecurityPolicyMiddleware)

    @app.get("/page", response_class=HTMLResponse)
    def page() -> str:
        return "<p>oi</p>"

    @app.get("/own")
    def own() -> HTMLResponse:
        return HTMLResponse("<p/>", headers={"Content-Security-Policy": "default-src 'none'"})

    @app.get("/data")
    def data() -> JSONResponse:
        return JSONResponse({"ok": True})

    @app.websocket("/ws")
    async def ws(socket: WebSocket):
        await socket.accept()
        await socket.send_json({"ok": True})
        await socket.close()

    client = TestClient(app)
    assert client.get("/page").headers["content-security-policy"] == CSP_POLICY
    assert client.get("/own").headers["content-security-policy"] == "default-src 'none'"
    assert "content-security-policy" not in client.get("/data").headers
    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json() == {"ok": True}


def test_chat_js_forbids_images_and_hardens_links(fastapi_test_client: TestClient) -> None:
    body = fastapi_test_client.get("/static/chat.js").text
    assert "window.DOMPurify.sanitize(window.marked.parse(text), PURIFY_CONFIG)" in body
    config = body[body.index("const PURIFY_CONFIG"):body.index("let purifyHooked")]
    for tag in ("'img'", "'picture'", "'source'", "'svg'"):
        assert tag in config
    for attr in ("'src'", "'srcset'", "'style'"):
        assert attr in config
    assert "addHook('afterSanitizeAttributes'" in body
    assert "node.setAttribute('rel', 'noopener noreferrer')" in body
    assert "node.setAttribute('target', '_blank')" in body
