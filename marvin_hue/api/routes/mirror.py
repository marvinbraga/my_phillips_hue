"""
Mirror Routes
Endpoints para controle de espelhamento de tela.
"""

from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from marvin_hue.screen_mirror import ScreenMirror
from marvin_hue.api.dependencies import get_screen_mirror
from marvin_hue.api.models import MirrorStartRequest, MirrorSettingsRequest
from marvin_hue.logging_config import get_logger

logger = get_logger("mirror")

router = APIRouter(tags=["Mirror"])

# Configurar templates
templates = Jinja2Templates(directory="web/templates")


@router.get("/mirror", response_class=HTMLResponse)
async def mirror_page(request: Request):
    """Página de espelhamento de tela."""
    return templates.TemplateResponse("mirror.html", {"request": request})


@router.post("/mirror/start")
async def start_mirror(
    request: MirrorStartRequest,
    screen_mirror: ScreenMirror = Depends(get_screen_mirror),
):
    """
    Inicia o espelhamento de tela.

    Args:
        request: Parâmetros de FPS e brilho

    Returns:
        dict: Status do espelhamento

    Raises:
        HTTPException: Se já estiver ativo ou houver erro
    """
    if screen_mirror is None:
        raise HTTPException(status_code=503, detail="Espelhamento não disponível")

    if screen_mirror.is_running():
        raise HTTPException(status_code=400, detail="Espelhamento já está ativo")

    try:
        screen_mirror.start(fps=request.fps, brightness=request.brightness)
        return {
            "message": "Espelhamento iniciado",
            "status": screen_mirror.get_status(),
        }
    except Exception as e:
        logger.exception(f"Error starting mirror: {e}")
        raise HTTPException(
            status_code=500, detail=f"Erro ao iniciar espelhamento: {str(e)}"
        )


@router.post("/mirror/stop")
async def stop_mirror(screen_mirror: ScreenMirror = Depends(get_screen_mirror)):
    """Para o espelhamento de tela."""
    if not screen_mirror.is_running():
        raise HTTPException(status_code=400, detail="Espelhamento não está ativo")

    screen_mirror.stop()
    return {"message": "Espelhamento parado"}


@router.get("/mirror/status")
async def mirror_status(screen_mirror: ScreenMirror = Depends(get_screen_mirror)):
    """Retorna o status atual do espelhamento."""
    return screen_mirror.get_status()


@router.post("/mirror/settings")
async def update_mirror_settings(
    request: MirrorSettingsRequest,
    screen_mirror: ScreenMirror = Depends(get_screen_mirror),
):
    """Atualiza configurações do espelhamento em tempo real."""
    if request.fps is not None:
        screen_mirror.fps = request.fps
    if request.brightness is not None:
        screen_mirror.brightness = request.brightness
    if request.saturation_boost is not None:
        screen_mirror.saturation_boost = request.saturation_boost
    if request.smoothing_factor is not None:
        screen_mirror.smoothing_factor = request.smoothing_factor
    if request.transition_time is not None:
        screen_mirror.transition_time = request.transition_time

    return {
        "message": "Configurações atualizadas",
        "status": screen_mirror.get_status(),
    }
