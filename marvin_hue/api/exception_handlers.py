"""Global FastAPI handlers for domain errors and opaque 500s.

Maps marvin_hue ``*ConflictError`` → 409, ``*NotFoundError`` → 404,
``*ValidationError`` → 400. Unhandled exceptions return a generic 500 body
(never ``str(exc)``) after logging the traceback.
"""

from __future__ import annotations

import importlib
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from marvin_hue.logging_config import get_logger

logger = get_logger("api.exceptions")

OPAQUE_500_DETAIL = "Internal server error"

_DOMAIN_ERROR_MODULES: tuple[str, ...] = (
    "marvin_hue.domain.lights",
    "marvin_hue.domain.groups",
    "marvin_hue.domain.schedules",
    "marvin_hue.domain.scene_history",
    "marvin_hue.services.backup",
    "marvin_hue.services.mirror_control",
)

_SUFFIX_STATUS: tuple[tuple[str, int], ...] = (
    ("ConflictError", 409),
    ("NotFoundError", 404),
    ("ValidationError", 400),
)


def _is_domain_module(module: str) -> bool:
    return module == "marvin_hue" or module.startswith("marvin_hue.")


def _status_for_error_type(cls: type[Any]) -> int | None:
    if not isinstance(cls, type):
        return None
    if not _is_domain_module(getattr(cls, "__module__", "") or ""):
        return None
    name = cls.__name__
    for suffix, code in _SUFFIX_STATUS:
        if name.endswith(suffix):
            return code
    return None


def http_status_for_exception(exc: BaseException) -> int | None:
    """Return 400/404/409 for domain errors; ``None`` if not a mapped type."""
    return _status_for_error_type(type(exc))


def iter_domain_http_errors() -> list[type[BaseException]]:
    """Domain exception classes registered on the FastAPI app."""
    found: list[type[BaseException]] = []
    seen: set[type[BaseException]] = set()
    for modname in _DOMAIN_ERROR_MODULES:
        module = importlib.import_module(modname)
        for obj in vars(module).values():
            if not isinstance(obj, type):
                continue
            try:
                if not issubclass(obj, BaseException):
                    continue
            except TypeError:
                continue
            if _status_for_error_type(obj) is None:
                continue
            if obj in seen:
                continue
            seen.add(obj)
            found.append(obj)
    return found


async def handle_domain_exception(_request: Request, exc: Exception) -> JSONResponse:
    """JSON ``detail`` body matching FastAPI ``HTTPException`` shape."""
    status_code = http_status_for_exception(exc) or 400
    return JSONResponse(status_code=status_code, content={"detail": str(exc)})


async def handle_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """Log the exception; never put ``str(exc)`` in the HTTP 500 body."""
    mapped = http_status_for_exception(exc)
    if mapped is not None:
        return JSONResponse(status_code=mapped, content={"detail": str(exc)})
    logger.exception(f"unhandled_api_exception path={request.url.path}")
    return JSONResponse(
        status_code=500,
        content={"detail": OPAQUE_500_DETAIL},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach domain handlers (ExceptionMiddleware) and opaque 500 handler."""
    for cls in iter_domain_http_errors():
        app.add_exception_handler(cls, handle_domain_exception)
    app.add_exception_handler(Exception, handle_unhandled_exception)
