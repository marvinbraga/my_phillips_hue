"""
Mirror Routes
Endpoints para espelhamento de tela e de música/áudio (mutuamente exclusivos)
e Hue Entertainment (pair / areas / status).
"""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from marvin_hue.api.dependencies import (
    get_audio_mirror,
    get_entertainment_client,
    get_mirror_control_service,
    get_screen_mirror,
    set_entertainment_client,
)
from marvin_hue.api.models import (
    EntertainmentPairRequest,
    MirrorProfileRequest,
    MirrorSettingsRequest,
    MirrorStartRequest,
)
from marvin_hue.audio_mirror import (
    ALL_AUDIO_PROFILES,
    AUDIO_INTENSITY_PROFILES,
    AUDIO_MIRROR_PROFILES,
    AudioMirror,
)
from marvin_hue.config import settings
from marvin_hue.entertainment.client import EntertainmentClient
from marvin_hue.entertainment.credentials import (
    load_entertainment_credentials,
    save_entertainment_credentials,
)
from marvin_hue.logging_config import get_logger
from marvin_hue.screen_mirror import MIRROR_PROFILES, ScreenMirror
from marvin_hue.services.mirror_control import (
    MirrorAlreadyActiveError,
    MirrorConfigNotFoundError,
    MirrorControlService,
    MirrorNotActiveError,
    MirrorValidationError,
    active_mode,
    entertainment_ready,
    safe_transport,
)

logger = get_logger("mirror")

router = APIRouter(tags=["Mirror"])

templates = Jinja2Templates(directory="web/templates")

_SCREEN_PROFILES = frozenset(MIRROR_PROFILES.keys())
_AUDIO_PROFILES = frozenset(ALL_AUDIO_PROFILES.keys())


def _raise_mirror_http(
    exc: Exception, *, mode: str | None = None, action: str = "iniciar"
) -> NoReturn:
    """Map use-case errors to HTTPException (never leaks from the service)."""
    if isinstance(exc, (MirrorAlreadyActiveError, MirrorNotActiveError)):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, (MirrorValidationError, ValueError)):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, MirrorConfigNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, RuntimeError):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    label = "espelhamento de música" if mode == "audio" else "espelhamento"
    logger.exception(f"Error in {label}: {exc}")
    raise HTTPException(
        status_code=500, detail=f"Erro ao {action} {label}: {str(exc)}"
    ) from exc


@router.get("/mirror", response_class=HTMLResponse)
async def mirror_page(request: Request):
    """Página de espelhamento (tela e música)."""
    return templates.TemplateResponse(
        request, "mirror.html", {"active": "espelhamento"}
    )


@router.post("/mirror/start")
async def start_mirror(
    request: MirrorStartRequest,
    svc: MirrorControlService = Depends(get_mirror_control_service),
) -> dict[str, Any]:
    """
    Inicia espelhamento de tela ou áudio.

    ``mode=screen`` (padrão) ou ``mode=audio``. Os dois modos são mutuamente
    exclusivos: iniciar um para o outro automaticamente.
    """
    mode = request.mode or "screen"
    try:
        return await svc.start(
            mode,
            profile=request.profile,
            fps=request.fps,
            brightness=request.brightness,
            area_id=request.area_id,
            transport_preference=request.transport_preference,
            config_name=request.config_name,
        )
    except (
        MirrorAlreadyActiveError,
        MirrorNotActiveError,
        MirrorValidationError,
        MirrorConfigNotFoundError,
        RuntimeError,
        ValueError,
    ) as exc:
        _raise_mirror_http(exc, mode=mode)
    except Exception as exc:
        _raise_mirror_http(exc, mode=mode)


@router.post("/mirror/stop")
async def stop_mirror(
    svc: MirrorControlService = Depends(get_mirror_control_service),
) -> dict[str, Any]:
    """Para o espelhamento ativo (tela ou música)."""
    try:
        return await svc.stop()
    except MirrorNotActiveError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/mirror/status")
async def mirror_status(
    svc: MirrorControlService = Depends(get_mirror_control_service),
) -> dict[str, Any]:
    """Status unificado: mode, running, cores e spectrum (bass/mid/treble)."""
    return svc.unified_status()


@router.post("/mirror/settings")
async def update_mirror_settings(
    request: MirrorSettingsRequest,
    svc: MirrorControlService = Depends(get_mirror_control_service),
) -> dict[str, Any]:
    """Atualiza configurações do modo ativo (ou mode explícito)."""
    try:
        return await svc.apply_settings(
            mode=request.mode,
            profile=request.profile,
            fps=request.fps,
            brightness=request.brightness,
            saturation_boost=request.saturation_boost,
            smoothing_factor=request.smoothing_factor,
            transition_time=request.transition_time,
            energy_gain=request.energy_gain,
            entertainment_area_id=request.entertainment_area_id,
            transport_preference=request.transport_preference,
            config_name=request.config_name,
            config_name_provided="config_name" in request.model_fields_set,
        )
    except (
        MirrorAlreadyActiveError,
        MirrorNotActiveError,
        MirrorValidationError,
        MirrorConfigNotFoundError,
        RuntimeError,
        ValueError,
    ) as exc:
        _raise_mirror_http(exc, mode=request.mode, action="atualizar")
    except Exception as exc:
        _raise_mirror_http(exc, mode=request.mode, action="atualizar")


@router.get("/mirror/profiles")
async def list_mirror_profiles():
    """Lista perfis de tela e de áudio (inclui intensity aliases)."""
    return {
        "profiles": MIRROR_PROFILES,
        "audio_profiles": AUDIO_MIRROR_PROFILES,
        "audio_intensity_profiles": AUDIO_INTENSITY_PROFILES,
    }


@router.post("/mirror/profile")
async def set_mirror_profile(
    request: MirrorProfileRequest,
    screen_mirror: ScreenMirror = Depends(get_screen_mirror),
    audio_mirror: AudioMirror = Depends(get_audio_mirror),
    svc: MirrorControlService = Depends(get_mirror_control_service),
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
        "status": svc.unified_status(),
    }


# ---------------------------------------------------------------------------
# Entertainment API
# ---------------------------------------------------------------------------


@router.get("/mirror/entertainment/status")
async def entertainment_status(
    screen_mirror: ScreenMirror = Depends(get_screen_mirror),
    audio_mirror: AudioMirror = Depends(get_audio_mirror),
    ent_client: EntertainmentClient | None = Depends(get_entertainment_client),
    svc: MirrorControlService = Depends(get_mirror_control_service),
):
    """Status do transporte Entertainment: enabled, ready, streaming, areas."""
    ready = entertainment_ready(ent_client)
    areas_out: list[dict[str, Any]] = []
    if ready and ent_client is not None:
        try:
            areas = await ent_client.list_areas()
            areas_out = [
                {
                    "id": a.id,
                    "name": a.name,
                    "channel_count": len(a.channels),
                }
                for a in areas
            ]
        except Exception as e:
            logger.warning(f"entertainment status list_areas: {e}")

    mode = active_mode(screen_mirror, audio_mirror)
    transport = "rest"
    if mode == "audio":
        transport = safe_transport(audio_mirror)
    elif mode == "screen":
        transport = safe_transport(screen_mirror)

    return {
        "enabled": settings.entertainment_enabled,
        "ready": ready,
        "streaming": bool(ent_client and ent_client.is_streaming),
        "active_area_id": ent_client.active_area if ent_client else None,
        "areas": areas_out,
        "transport": transport,
        "default_area_id": settings.entertainment_area_id or svc.pending_area_id,
        "fps_default": settings.entertainment_fps,
    }


@router.post("/mirror/entertainment/pair")
async def pair_entertainment(
    body: EntertainmentPairRequest | None = None,
    ent_client: EntertainmentClient | None = Depends(get_entertainment_client),
):
    """
    Pair with the Hue bridge (press the link button first).

    Saves credentials to ENTERTAINMENT_CREDS_FILE. Never logs full keys.
    """
    if ent_client is None:
        # Construct a temporary client for pairing
        ent_client = EntertainmentClient(host=settings.bridge_ip, credentials=None)
        set_entertainment_client(ent_client)

    device_type = (body.device_type if body else None) or "marvin_hue#entertainment"
    try:
        creds = await ent_client.pair(device_type=device_type)
    except TimeoutError as e:
        raise HTTPException(
            status_code=408,
            detail=(
                "Pairing timeout — pressione o botão da bridge e tente novamente. "
                f"{e}"
            ),
        ) from e
    except Exception as e:
        logger.exception(f"Entertainment pair failed: {e}")
        raise HTTPException(
            status_code=502, detail=f"Falha no pairing Entertainment: {e}"
        ) from e

    save_entertainment_credentials(
        settings.entertainment_creds_file,
        username=creds.username,
        clientkey=creds.clientkey,
    )
    # Reload into client in case env later overrides
    reloaded = load_entertainment_credentials(
        settings.entertainment_creds_file,
        settings.hue_app_key,
        settings.hue_client_key,
    )
    if reloaded is not None:
        ent_client.credentials = reloaded
    set_entertainment_client(ent_client)

    suffix = creds.username[-4:] if len(creds.username) >= 4 else "****"
    return {
        "ok": True,
        "username_suffix": suffix,
        "creds_file": settings.entertainment_creds_file,
        "message": (
            "Pairing OK. Defina ENTERTAINMENT_ENABLED=true e reinicie "
            "se ainda estiver desabilitado."
        ),
    }


@router.get("/mirror/entertainment/areas")
async def list_entertainment_areas(
    ent_client: EntertainmentClient | None = Depends(get_entertainment_client),
):
    """Lista entertainment areas (vazio se unpaired / sem creds)."""
    if ent_client is None or not ent_client.is_ready:
        return {"areas": [], "ready": False}
    try:
        areas = await ent_client.list_areas()
    except Exception as e:
        logger.warning(f"list entertainment areas failed: {e}")
        raise HTTPException(
            status_code=502, detail=f"Não foi possível listar áreas: {e}"
        ) from e
    return {
        "ready": True,
        "areas": [
            {
                "id": a.id,
                "name": a.name,
                "channel_count": len(a.channels),
                "channels": [
                    {
                        "channel_id": c.channel_id,
                        "name": c.name,
                        "service_id": c.service_id,
                    }
                    for c in a.channels
                ],
            }
            for a in areas
        ],
    }
