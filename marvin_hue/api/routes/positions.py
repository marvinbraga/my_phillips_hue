"""
Position Routes
Endpoints para gerenciar posicionamento de lâmpadas para espelhamento.
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from marvin_hue.api import dependencies as deps
from marvin_hue.api.models import PositionsUpdate
from marvin_hue.logging_config import get_logger
from marvin_hue.persistence.positions_repository import (
    JsonPositionsRepository,
    PositionsRepository,
)

router = APIRouter(tags=["Positions"])
logger = get_logger("api.positions")

templates = Jinja2Templates(directory="web/templates")

_positions_repo: PositionsRepository = JsonPositionsRepository()


def _reload_audio_positions() -> None:
    try:
        audio = deps.get_audio_mirror()
    except RuntimeError:
        return
    reload_fn = getattr(audio, "reload_light_positions", None)
    if not callable(reload_fn):
        return
    try:
        reload_fn()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"AudioMirror position reload failed: {exc}")


@router.get("/positions-config", response_class=HTMLResponse)
async def positions_page(request: Request) -> HTMLResponse:
    """Página de configuração de posicionamento."""
    return templates.TemplateResponse(request, "positions.html", {"active": "posicoes"})


@router.get("/positions")
async def get_positions() -> dict[str, Any]:
    """Retorna a configuração de posicionamento das lâmpadas."""
    data = await _positions_repo.load()
    if not data:
        return await reset_positions()
    return data


@router.post("/positions")
async def save_positions(request: PositionsUpdate) -> dict[str, str]:
    """Salva a configuração de posicionamento."""
    current = await _positions_repo.load()
    current["lights"] = [light.model_dump() for light in request.lights]
    await _positions_repo.save(current)
    _reload_audio_positions()
    return {"message": "Configuração salva com sucesso"}


@router.post("/positions/reset")
async def reset_positions() -> dict[str, Any]:
    """Restaura a configuração padrão de posicionamento."""
    default_config = _positions_repo.default_payload()
    await _positions_repo.save(default_config)
    _reload_audio_positions()
    return default_config
