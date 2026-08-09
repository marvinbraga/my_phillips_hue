"""
Mirror Routes
Endpoints para espelhamento de tela e de música/áudio (mutuamente exclusivos)
e Hue Entertainment (pair / areas / status).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from marvin_hue.api.dependencies import (
    get_audio_mirror,
    get_entertainment_client,
    get_hue_controller,
    get_scene_history_service,
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
from marvin_hue.controllers import HueController
from marvin_hue.entertainment.channel_map import map_lights_to_channels
from marvin_hue.entertainment.client import EntertainmentClient
from marvin_hue.entertainment.credentials import (
    load_entertainment_credentials,
    save_entertainment_credentials,
)
from marvin_hue.logging_config import get_logger
from marvin_hue.output.factory import build_audio_output_port
from marvin_hue.screen_mirror import MIRROR_PROFILES, ScreenMirror
from marvin_hue.services.scene_history import SceneHistoryService

logger = get_logger("mirror")

router = APIRouter(tags=["Mirror"])

templates = Jinja2Templates(directory="web/templates")

_SCREEN_PROFILES = frozenset(MIRROR_PROFILES.keys())
_AUDIO_PROFILES = frozenset(ALL_AUDIO_PROFILES.keys())

# Last transport preference from settings API (applied on next start)
_pending_transport_preference: str = "auto"
_pending_area_id: str | None = None


def _active_mode(screen: ScreenMirror, audio: AudioMirror) -> str | None:
    if audio.is_running():
        return "audio"
    if screen.is_running():
        return "screen"
    return None


def _entertainment_ready(client: EntertainmentClient | None) -> bool:
    return client is not None and client.is_ready


def _safe_transport(mirror: ScreenMirror | AudioMirror) -> str:
    """Best-effort transport name; never return MagicMock/non-str (JSON-safe)."""
    try:
        port = getattr(mirror, "output_port", None)
        t = getattr(port, "transport", None) if port is not None else None
        if t in ("rest", "entertainment"):
            return t  # type: ignore[return-value]
        if isinstance(t, str) and t:
            return t
    except Exception:
        pass
    return "rest"


def _safe_area_id(mirror: ScreenMirror | AudioMirror) -> str | None:
    try:
        area = getattr(mirror, "entertainment_area_id", None)
        if isinstance(area, str):
            return area
    except Exception:
        pass
    return None


def _unified_status(screen: ScreenMirror, audio: AudioMirror) -> dict[str, Any]:
    """Status unificado com mode, running e spectrum (se audio)."""
    mode = _active_mode(screen, audio)
    ent = get_entertainment_client()
    ready = _entertainment_ready(ent)
    if mode == "audio":
        status = audio.get_status()
        if not isinstance(status, dict):
            status = {"running": bool(audio.is_running())}
        status["mode"] = "audio"
        status.setdefault("entertainment_enabled", bool(settings.entertainment_enabled))
        status["entertainment_ready"] = ready
        status.setdefault("transport", _safe_transport(audio))
        if not isinstance(status.get("transport"), str):
            status["transport"] = _safe_transport(audio)
        status.setdefault("entertainment_area_id", _safe_area_id(audio))
        return status
    status = screen.get_status()
    if not isinstance(status, dict):
        status = {"running": bool(screen.is_running())}
    status["mode"] = "screen" if mode == "screen" else None
    status.setdefault("bass", 0.0)
    status.setdefault("mid", 0.0)
    status.setdefault("treble", 0.0)
    status.setdefault("transport", _safe_transport(screen))
    status.setdefault("entertainment_enabled", bool(settings.entertainment_enabled))
    status["entertainment_ready"] = ready
    status.setdefault("entertainment_area_id", _safe_area_id(screen))
    # Ensure transport is a plain string even if mock put something else
    if not isinstance(status.get("transport"), str):
        status["transport"] = _safe_transport(screen)
    return status


def _stop_if_running(mirror: ScreenMirror | AudioMirror) -> None:
    if mirror.is_running():
        mirror.stop()


async def _resolve_area_and_channels(
    client: EntertainmentClient | None,
    *,
    area_id: str | None,
    lights: list[dict[str, Any]] | Any,
) -> tuple[str | None, list]:
    """Return (area_id, mapped_channels) or (None, [])."""
    if client is None or not client.is_ready:
        return None, []
    # Defensive: mocks or bad return types
    if not isinstance(lights, list):
        lights = []
    try:
        areas = await client.list_areas()
    except Exception as e:
        logger.warning(f"list_areas failed: {e}")
        return None, []
    if not areas:
        return None, []

    chosen_id = area_id or _pending_area_id or settings.entertainment_area_id
    area = None
    if chosen_id:
        for a in areas:
            if a.id == chosen_id:
                area = a
                break
    if area is None:
        area = areas[0]
        chosen_id = area.id

    mapped = map_lights_to_channels(area, lights)
    return chosen_id, mapped


async def _build_port_for_mirror(
    hue: HueController,
    client: EntertainmentClient | None,
    *,
    lights: list[dict[str, Any]],
    area_id: str | None,
    transport_preference: str,
    transition_time: int = 0,
):
    pref = (transport_preference or "auto").strip().lower()
    resolved_area, mapped = await _resolve_area_and_channels(
        client, area_id=area_id, lights=lights
    )
    return (
        build_audio_output_port(
            hue,
            entertainment_enabled=settings.entertainment_enabled,
            client=client,
            area_id=resolved_area,
            mapped_channels=mapped or None,
            transition_time=transition_time,
            transport_preference=pref,
        ),
        resolved_area,
    )


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
    hue: HueController = Depends(get_hue_controller),
    ent_client: EntertainmentClient | None = Depends(get_entertainment_client),
):
    """
    Inicia espelhamento de tela ou áudio.

    ``mode=screen`` (padrão) ou ``mode=audio``. Os dois modos são mutuamente
    exclusivos: iniciar um para o outro automaticamente.
    """
    mode = request.mode or "screen"
    transport_pref = (
        request.transport_preference
        or _pending_transport_preference
        or "auto"
    )
    area_id = request.area_id or _pending_area_id or settings.entertainment_area_id

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
        _stop_if_running(screen_mirror)
        try:
            load_pos = getattr(audio_mirror, "load_light_positions", None)
            lights = load_pos() if callable(load_pos) else []
            if not isinstance(lights, list):
                lights = []
            tt = getattr(audio_mirror, "transition_time", 0) or 0
            try:
                transition_time = int(round(float(tt)))
            except (TypeError, ValueError):
                transition_time = 0
            port, resolved_area = await _build_port_for_mirror(
                hue,
                ent_client,
                lights=lights,
                area_id=area_id,
                transport_preference=transport_pref,
                transition_time=transition_time,
            )
            set_port = getattr(audio_mirror, "set_output_port", None)
            if callable(set_port):
                set_port(port)
            try:
                audio_mirror.entertainment_enabled = settings.entertainment_enabled
                audio_mirror.entertainment_area_id = resolved_area
            except Exception:
                pass

            fps = request.fps
            if (
                fps is None
                and port.transport == "entertainment"
                and request.profile is None
            ):
                fps = settings.entertainment_fps

            audio_mirror.start(
                fps=fps,
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
        load_pos = getattr(screen_mirror, "load_light_positions", None)
        lights = load_pos() if callable(load_pos) else []
        if not isinstance(lights, list):
            lights = []
        tt = getattr(screen_mirror, "transition_time", 0) or 0
        try:
            transition_time = int(round(float(tt)))
        except (TypeError, ValueError):
            transition_time = 0
        port, resolved_area = await _build_port_for_mirror(
            hue,
            ent_client,
            lights=lights,
            area_id=area_id,
            transport_preference=transport_pref,
            transition_time=transition_time,
        )
        set_port = getattr(screen_mirror, "set_output_port", None)
        if callable(set_port):
            set_port(port)
        try:
            screen_mirror.entertainment_enabled = settings.entertainment_enabled
            screen_mirror.entertainment_area_id = resolved_area
        except Exception:
            pass

        fps = request.fps
        if (
            fps is None
            and port.transport == "entertainment"
            and request.profile is None
        ):
            fps = settings.entertainment_fps

        screen_mirror.start(
            fps=fps,
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
    global _pending_transport_preference, _pending_area_id

    if request.transport_preference is not None:
        _pending_transport_preference = request.transport_preference
    if request.entertainment_area_id is not None:
        _pending_area_id = request.entertainment_area_id
        for m in (screen_mirror, audio_mirror):
            try:
                m.entertainment_area_id = request.entertainment_area_id
            except Exception:
                pass

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


# ---------------------------------------------------------------------------
# Entertainment API
# ---------------------------------------------------------------------------


@router.get("/mirror/entertainment/status")
async def entertainment_status(
    screen_mirror: ScreenMirror = Depends(get_screen_mirror),
    audio_mirror: AudioMirror = Depends(get_audio_mirror),
    ent_client: EntertainmentClient | None = Depends(get_entertainment_client),
):
    """Status do transporte Entertainment: enabled, ready, streaming, areas."""
    ready = _entertainment_ready(ent_client)
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

    mode = _active_mode(screen_mirror, audio_mirror)
    transport = "rest"
    if mode == "audio":
        transport = _safe_transport(audio_mirror)
    elif mode == "screen":
        transport = _safe_transport(screen_mirror)

    return {
        "enabled": settings.entertainment_enabled,
        "ready": ready,
        "streaming": bool(ent_client and ent_client.is_streaming),
        "active_area_id": ent_client.active_area if ent_client else None,
        "areas": areas_out,
        "transport": transport,
        "default_area_id": settings.entertainment_area_id or _pending_area_id,
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
