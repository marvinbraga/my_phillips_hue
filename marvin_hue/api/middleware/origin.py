"""Same-origin check para requisições do navegador que mudam estado (anti-CSRF).

As rotas da UI (``/apply``, ``/lights/off``, ``DELETE /configurations/...``,
``/mirror/*``...) ficam abertas na LAN, sem API key. Sem esta checagem,
qualquer página aberta num navegador da LAN poderia disparar um ``fetch``
cross-origin e mudar o estado (o navegador envia a requisição mesmo que a
resposta seja bloqueada pelo CORS).

Regra (mesma do ``WS /ws/chat``): sem ``Origin`` (curl, CLI, scripts) →
permitido; com ``Origin``, o host:porta tem de bater com o ``Host`` da
requisição, ou a origem tem de estar listada explicitamente em
``CORS_ORIGINS`` (``*`` não libera escrita). ``Origin: null`` é recusado.
"""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from marvin_hue.logging_config import get_logger

logger = get_logger("api.origin")

STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
CROSS_ORIGIN_DETAIL = "Requisição cross-origin recusada."


def origin_allowed(origin: str | None, host: str | None) -> bool:
    """Same-origin check (navegador): ``Origin`` tem de casar com ``Host``.

    Sem ``Origin`` (CLI/scripts, fora do navegador) → permitido. Com
    ``Origin``, o host:porta tem de bater com o ``Host`` da requisição;
    ``null`` (iframes sandbox, file://) é recusado.
    """
    if origin is None:
        return True
    if not host:
        return False
    netloc = urlsplit(origin).netloc
    return bool(netloc) and netloc.casefold() == host.strip().casefold()


def normalize_origin(origin: str) -> str:
    return origin.strip().rstrip("/").casefold()


def explicit_origins(origins: Iterable[str]) -> frozenset[str]:
    """Origens listadas em ``CORS_ORIGINS``, sem o curinga ``*``."""
    return frozenset(
        normalize_origin(o) for o in origins if o.strip() and o.strip() != "*"
    )


class SameOriginMiddleware:
    """ASGI puro: 403 para POST/PUT/PATCH/DELETE cross-origin (não toca WS)."""

    def __init__(self, app: ASGIApp, allowed_origins: Iterable[str] = ()) -> None:
        self.app = app
        self.allowed_origins = explicit_origins(allowed_origins)

    def is_allowed(self, origin: str | None, host: str | None) -> bool:
        if origin is None or origin_allowed(origin, host):
            return True
        return normalize_origin(origin) in self.allowed_origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in STATE_CHANGING_METHODS:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        origin = headers.get("origin")
        if self.is_allowed(origin, headers.get("host")):
            await self.app(scope, receive, send)
            return
        logger.warning(
            f"{scope['method']} {scope['path']} recusado: origin cross-site {origin!r}"
        )
        response = JSONResponse({"detail": CROSS_ORIGIN_DETAIL}, status_code=403)
        await response(scope, receive, send)
