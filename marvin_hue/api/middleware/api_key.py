"""Optional API key middleware for machine-to-machine /api/* routes.

When ``api_key`` is None or blank, the middleware is a no-op (open access).
When set, requests whose path starts with ``/api/`` must present the key via
``X-API-Key`` or ``Authorization: Bearer <key>``. HTML pages, static files,
WebSockets, and non-``/api`` JSON routes (e.g. ``/apply``, ``/mirror/*``)
remain open for local LAN UI usability.
"""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Protect ``/api/*`` with an optional shared secret when configured."""

    def __init__(self, app: ASGIApp, api_key: str | None = None) -> None:
        super().__init__(app)
        self._api_key = (api_key or "").strip() or None

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if self._api_key is None:
            return await call_next(request)

        # Let CORS preflight through (no credentials on OPTIONS).
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)

        provided = self._extract_key(request)
        if provided is None or not self._keys_match(provided, self._api_key):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
            )
        return await call_next(request)

    @staticmethod
    def _keys_match(provided: str, expected: str) -> bool:
        """Constant-time compare; unequal lengths are a miss (not an error)."""
        if len(provided) != len(expected):
            return False
        return hmac.compare_digest(provided, expected)

    @staticmethod
    def _extract_key(request: Request) -> str | None:
        """Return key from X-API-Key or Authorization: Bearer (X-API-Key wins)."""
        header_key = request.headers.get("X-API-Key")
        if header_key is not None and header_key != "":
            return header_key

        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
            return token or None
        return None
