"""
Mirror Routes
Endpoints para espelhamento de tela e de música/áudio (mutuamente exclusivos).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from marvin_hue.api.dependencies import (
    get_audio_mirror,
    get_hue_controller,
    get_scene_history_service,
    get_screen_mirror,
)
from marvin_hue.api.models import (
    MirrorProfileRequest,
    MirrorSettingsRequest,
    MirrorStartRequest,
)
from marvin_hue.audio_mirror import AUDIO_MIRROR_PROFILES, AudioMirror
from marvin_hue.controllers import HueController
from marvin_hue.logging_config import get_logger
from marvin_hue.screen_mirror import MIRROR_PROFILES, ScreenMirror
from marvin_hue.services.scene_history import SceneHistoryService

logger = get_logger("mirror")

router = APIRouter(tags=["Mirror"])

templates = Jinja2Templates(directory="web/templates")

_SCREEN_PROFILES = frozenset(MIRROR_PROFILES.keys())
_AUDIO_PROFILES = frozenset(AUDIO_MIRROR_PROFILES.keys())


def _active_mode(screen: ScreenMirror, audio: AudioMirror) -> str | None:
    if audio.is_running():
        return "audio"
    if screen.is_running():
        return "screen"
    return None


def _unified_status(screen: ScreenMirror, audio: AudioMirror) -> dict[str, Any]:
    """Status unificado com mode, running e spectrum (se audio)."""
    mode = _active_mode(screen, audio)
    if mode == "audio":
        status = audio.get_status()
        status["mode"] = "audio"
        return status
    status = screen.get_status()
    status["mode"] = "screen" if mode == "screen" else None
    # Spectrum zerado quando não há audio
    status.setdefault("bass", 0.0)
    status.setdefault("mid", 0.0)
    status.setdefault("treble", 0.0)
    return status


def _stop_if_running(mirror: ScreenMirror | AudioMirror) -> None:
    if mirror.is_running():
        mirror.stop()


@router.get("/mirror", response_class=HTMLResponse)
async def mirror_page(request: Request):
    """Página de espelhamento (tela e música)."""
    return templates.TemplateResponse(
        request, "mirror.html", {"active": "espelhamento"}
    )


@router.post("/mirror/start")
async def start_mirror(
    request: MirrorStartRequest,
    screen_mirror: ScreenMirror = Depends(get_screen_mirror),
    audio_mirror: AudioMirror = Depends(get_audio_mirror),
):
    """
    Inicia espelhamento de tela ou áudio.

    ``mode=screen`` (padrão) ou ``mode=audio``. Os dois modos são mutuamente
    exclusivos: iniciar um para o outro automaticamente.
    """
    mode = request.mode or "screen"

    if mode == "audio":
        if request.profile is not None and request.profile not in _AUDIO_PROFILES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Perfil '{request.profile}' inválido para modo audio. "
                    f"Use: {', '.join(sorted(_AUDIO_PROFILES))}"
                ),
            )
        if audio_mirror.is_running():
            raise HTTPException(
                status_code=400, detail="Espelhamento de música já está ativo"
            )
        # Mutual exclusion: para tela se estiver rodando
        _stop_if_running(screen_mirror)
        try:
            audio_mirror.start(
                fps=request.fps,
                brightness=request.brightness,
                profile=request.profile,
            )
            return {
                "message": "Espelhamento de música iniciado",
                "status": _unified_status(screen_mirror, audio_mirror),
            }
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:
            logger.exception(f"Error starting audio mirror: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Erro ao iniciar espelhamento de música: {str(e)}",
            ) from e

    # mode == screen
    if request.profile is not None and request.profile not in _SCREEN_PROFILES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Perfil '{request.profile}' inválido para modo screen. "
                f"Use: {', '.join(sorted(_SCREEN_PROFILES))}"
            ),
        )
    if screen_mirror.is_running():
        raise HTTPException(status_code=400, detail="Espelhamento já está ativo")

    _stop_if_running(audio_mirror)
    try:
        screen_mirror.start(
            fps=request.fps,
            brightness=request.brightness,
            profile=request.profile,
        )
        return {
            "message": "Espelhamento iniciado",
            "status": _unified_status(screen_mirror, audio_mirror),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception(f"Error starting mirror: {e}")
        raise HTTPException(
            status_code=500, detail=f"Erro ao iniciar espelhamento: {str(e)}"
        ) from e


@router.post("/mirror/stop")
async def stop_mirror(
    screen_mirror: ScreenMirror = Depends(get_screen_mirror),
    audio_mirror: AudioMirror = Depends(get_audio_mirror),
    hue: HueController = Depends(get_hue_controller),
    history: SceneHistoryService = Depends(get_scene_history_service),
):
    """Para o espelhamento ativo (tela ou música)."""
    mode = _active_mode(screen_mirror, audio_mirror)
    if mode is None:
        raise HTTPException(status_code=400, detail="Espelhamento não está ativo")

    try:
        await history.snapshot(hue, source="mirror_stop", label="before mirror stop")
    except Exception as snap_exc:
        logger.warning(f"Scene snapshot before mirror stop failed: {snap_exc}")

    if mode == "audio":
        audio_mirror.stop()
        return {"message": "Espelhamento de música parado"}

    screen_mirror.stop()
    return {"message": "Espelhamento parado"}


@router.get("/mirror/status")
async def mirror_status(
    screen_mirror: ScreenMirror = Depends(get_screen_mirror),
    audio_mirror: AudioMirror = Depends(get_audio_mirror),
):
    """Status unificado: mode, running, cores e spectrum (bass/mid/treble)."""
    return _unified_status(screen_mirror, audio_mirror)


@router.post("/mirror/settings")
async def update_mirror_settings(
    request: MirrorSettingsRequest,
    screen_mirror: ScreenMirror = Depends(get_screen_mirror),
    audio_mirror: AudioMirror = Depends(get_audio_mirror),
):
    """Atualiza configurações do modo ativo (ou mode explícito)."""
    mode = request.mode or _active_mode(screen_mirror, audio_mirror) or "screen"

    if mode == "audio":
        try:
            if request.profile is not None:
                if request.profile not in _AUDIO_PROFILES:
                    raise ValueError(
                        f"Perfil '{request.profile}' inválido para modo audio"
                    )
                audio_mirror.apply_profile(request.profile)
            if request.fps is not None:
                audio_mirror.fps = request.fps
            if request.brightness is not None:
                audio_mirror.brightness = request.brightness
            if request.smoothing_factor is not None:
                audio_mirror.smoothing_factor = request.smoothing_factor
            if request.transition_time is not None:
                audio_mirror.transition_time = request.transition_time
            if request.energy_gain is not None:
                audio_mirror.energy_gain = request.energy_gain
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {
            "message": "Configurações de áudio atualizadas",
            "status": _unified_status(screen_mirror, audio_mirror),
        }

    try:
        if request.profile is not None:
            if request.profile not in _SCREEN_PROFILES:
                raise ValueError(
                    f"Perfil '{request.profile}' inválido para modo screen"
                )
            screen_mirror.apply_profile(request.profile)
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
        "status": _unified_status(screen_mirror, audio_mirror),
    }


@router.get("/mirror/profiles")
async def list_mirror_profiles():
    """Lista perfis de tela e de áudio."""
    return {
        "profiles": MIRROR_PROFILES,
        "audio_profiles": AUDIO_MIRROR_PROFILES,
    }


@router.post("/mirror/profile")
async def set_mirror_profile(
    request: MirrorProfileRequest,
    screen_mirror: ScreenMirror = Depends(get_screen_mirror),
    audio_mirror: AudioMirror = Depends(get_audio_mirror),
):
    """Aplica um perfil nomeado sem reiniciar o loop."""
    mode = request.mode
    if mode is None:
        if request.profile in _AUDIO_PROFILES:
            mode = "audio"
        else:
            mode = "screen"

    try:
        if mode == "audio":
            if request.profile not in _AUDIO_PROFILES:
                raise ValueError(
                    f"Perfil '{request.profile}' inválido para modo audio"
                )
            audio_mirror.apply_profile(request.profile)
        else:
            if request.profile not in _SCREEN_PROFILES:
                raise ValueError(
                    f"Perfil '{request.profile}' inválido para modo screen"
                )
            screen_mirror.apply_profile(request.profile)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return {
        "message": f"Perfil '{request.profile}' aplicado",
        "status": _unified_status(screen_mirror, audio_mirror),
    }
