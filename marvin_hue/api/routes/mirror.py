"""
Mirror Routes
Endpoints para controle de espelhamento de tela.
"""

from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from marvin_hue.screen_mirror import MIRROR_PROFILES, ScreenMirror
from marvin_hue.api.dependencies import (
    get_hue_controller,
    get_scene_history_service,
    get_screen_mirror,
)
from marvin_hue.api.models import (
    MirrorProfileRequest,
    MirrorSettingsRequest,
    MirrorStartRequest,
)
from marvin_hue.controllers import HueController
from marvin_hue.logging_config import get_logger
from marvin_hue.services.scene_history import SceneHistoryService

logger = get_logger("mirror")

router = APIRouter(tags=["Mirror"])

# Configurar templates
templates = Jinja2Templates(directory="web/templates")


@router.get("/mirror", response_class=HTMLResponse)
async def mirror_page(request: Request):
    """Página de espelhamento de tela."""
    return templates.TemplateResponse(
        request, "mirror.html", {"active": "espelhamento"}
    )


@router.post("/mirror/start")
async def start_mirror(
    request: MirrorStartRequest,
    screen_mirror: ScreenMirror = Depends(get_screen_mirror),
):
    """
    Inicia o espelhamento de tela.

    Args:
        request: FPS/brilho e/ou profile (cinema|fps|ambient)

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
        screen_mirror.start(
            fps=request.fps,
            brightness=request.brightness,
            profile=request.profile,
        )
        return {
            "message": "Espelhamento iniciado",
            "status": screen_mirror.get_status(),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception(f"Error starting mirror: {e}")
        raise HTTPException(
            status_code=500, detail=f"Erro ao iniciar espelhamento: {str(e)}"
        )


@router.post("/mirror/stop")
async def stop_mirror(
    screen_mirror: ScreenMirror = Depends(get_screen_mirror),
    hue: HueController = Depends(get_hue_controller),
    history: SceneHistoryService = Depends(get_scene_history_service),
):
    """Para o espelhamento de tela (snapshot before stop for undo)."""
    if not screen_mirror.is_running():
        raise HTTPException(status_code=400, detail="Espelhamento não está ativo")

    try:
        await history.snapshot(hue, source="mirror_stop", label="before mirror stop")
    except Exception as snap_exc:
        logger.warning(f"Scene snapshot before mirror stop failed: {snap_exc}")

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
    if screen_mirror is None:
        raise HTTPException(status_code=503, detail="Espelhamento não disponível")

    try:
        if request.profile is not None:
            screen_mirror.apply_profile(request.profile)
        # Explicit fields override profile values when both are sent.
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
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return {
        "message": "Configurações atualizadas",
        "status": screen_mirror.get_status(),
    }


@router.get("/mirror/profiles")
async def list_mirror_profiles():
    """Lista perfis de espelhamento disponíveis e seus defaults."""
    return {"profiles": MIRROR_PROFILES}


@router.post("/mirror/profile")
async def set_mirror_profile(
    request: MirrorProfileRequest,
    screen_mirror: ScreenMirror = Depends(get_screen_mirror),
):
    """Aplica um perfil nomeado (cinema|fps|ambient) sem reiniciar o loop."""
    if screen_mirror is None:
        raise HTTPException(status_code=503, detail="Espelhamento não disponível")

    try:
        screen_mirror.apply_profile(request.profile)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return {
        "message": f"Perfil '{request.profile}' aplicado",
        "status": screen_mirror.get_status(),
    }
