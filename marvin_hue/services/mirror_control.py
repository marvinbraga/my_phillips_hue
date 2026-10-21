"""Screen/audio mirror start, stop, settings, and unified status.

Focused use case (not a subsystem Facade). Entertainment pairing stays in the
HTTP routes. ``run_coro`` is never used; DTLS start/stop is awaited on the
FastAPI loop.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from marvin_hue.audio_mirror import ALL_AUDIO_PROFILES, AudioMirror
from marvin_hue.basics import LightSetupsManager
from marvin_hue.config import settings
from marvin_hue.controllers import HueController
from marvin_hue.entertainment.channel_map import map_lights_to_channels
from marvin_hue.entertainment.client import EntertainmentClient
from marvin_hue.logging_config import get_logger
from marvin_hue.output.factory import build_audio_output_port
from marvin_hue.screen_mirror import MIRROR_PROFILES, ScreenMirror
from marvin_hue.services.last_applied_scene import (
    SOURCE_MIRROR,
    LastAppliedProvider,
    resolve_last_applied,
)
from marvin_hue.services.scene_history import SceneHistoryService

logger = get_logger("services.mirror_control")

_SCREEN_PROFILES = frozenset(MIRROR_PROFILES.keys())
_AUDIO_PROFILES = frozenset(ALL_AUDIO_PROFILES.keys())

GetScreen = Callable[[], ScreenMirror]
GetAudio = Callable[[], AudioMirror]
GetHue = Callable[[], HueController]
GetManager = Callable[[], LightSetupsManager]
GetEntertainment = Callable[[], EntertainmentClient | None]
GetHistory = Callable[[], SceneHistoryService | None]


class MirrorControlError(Exception):
    """Base error for mirror start/stop/settings."""


class MirrorAlreadyActiveError(MirrorControlError):
    """Requested mode is already running."""


class MirrorNotActiveError(MirrorControlError):
    """Stop requested but no mirror is running."""


class MirrorValidationError(MirrorControlError, ValueError):
    """Invalid profile, mode, or settings."""


class MirrorConfigNotFoundError(MirrorControlError, LookupError):
    """Named LightConfig not found."""


def active_mode(screen: ScreenMirror, audio: AudioMirror) -> str | None:
    if audio.is_running():
        return "audio"
    if screen.is_running():
        return "screen"
    return None


def entertainment_ready(client: EntertainmentClient | None) -> bool:
    return client is not None and client.is_ready


def safe_transport(mirror: ScreenMirror | AudioMirror) -> str:
    """Best-effort transport name; never return MagicMock/non-str (JSON-safe)."""
    try:
        port = getattr(mirror, "output_port", None)
        t = getattr(port, "transport", None) if port is not None else None
        if t in ("rest", "entertainment"):
            return str(t)
        if isinstance(t, str) and t:
            return t
    except Exception:
        pass
    return "rest"


def safe_area_id(mirror: ScreenMirror | AudioMirror) -> str | None:
    try:
        area = getattr(mirror, "entertainment_area_id", None)
        if isinstance(area, str):
            return area
    except Exception:
        pass
    return None


def _stop_mirror(mirror: ScreenMirror | AudioMirror) -> None:
    """Stop a mirror without ``end_session`` (avoids ``run_coro`` on the loop)."""
    try:
        mirror.stop(end_output=False)
    except TypeError:
        mirror.stop()


def _load_lights(mirror: ScreenMirror | AudioMirror) -> list[dict[str, Any]]:
    load_pos = getattr(mirror, "load_light_positions", None)
    lights = load_pos() if callable(load_pos) else []
    if not isinstance(lights, list):
        return []
    return lights


def _transition_time(mirror: ScreenMirror | AudioMirror) -> int:
    tt = getattr(mirror, "transition_time", 0) or 0
    try:
        return int(round(float(tt)))
    except (TypeError, ValueError):
        return 0


async def _resolve_area_and_channels(
    client: EntertainmentClient | None,
    *,
    area_id: str | None,
    lights: list[dict[str, Any]] | Any,
) -> tuple[str | None, list[Any]]:
    if client is None or not client.is_ready:
        return None, []
    if not isinstance(lights, list):
        lights = []
    try:
        areas = await client.list_areas()
    except Exception as exc:
        logger.warning(f"list_areas failed: {exc}")
        return None, []
    if not areas:
        return None, []

    chosen_id = area_id
    area = None
    if chosen_id:
        for candidate in areas:
            if candidate.id == chosen_id:
                area = candidate
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
) -> tuple[Any, str | None, list[Any]]:
    pref = (transport_preference or "auto").strip().lower()
    resolved_area, mapped = await _resolve_area_and_channels(
        client, area_id=area_id, lights=lights
    )
    if mapped:
        logger.info(
            f"Entertainment channel map: area={resolved_area} mapped={len(mapped)}"
        )
    else:
        logger.warning("Entertainment channel map empty — will use REST unless forced")
    port = build_audio_output_port(
        hue,
        entertainment_enabled=settings.entertainment_enabled,
        client=client,
        area_id=resolved_area,
        mapped_channels=mapped or None,
        transition_time=transition_time,
        transport_preference=pref,
    )
    return port, resolved_area, mapped


async def _ensure_entertainment_started(
    port: Any,
    client: EntertainmentClient | None,
    area_id: str | None,
    hue: HueController,
    *,
    transition_time: int = 0,
) -> Any:
    """Await DTLS stream start from the FastAPI event loop (never ``run_coro``)."""
    from marvin_hue.output.fallback import FallbackOutputPort
    from marvin_hue.output.rest_adapter import RestPhueAdapter

    uses_ent = port.transport == "entertainment" or isinstance(port, FallbackOutputPort)
    if not uses_ent or client is None or not area_id:
        return port

    try:
        await client.start_stream(area_id)
        logger.info(f"Entertainment stream pre-started area={area_id}")
        return port
    except Exception as exc:
        logger.warning(f"Entertainment start failed, using REST: {exc}")
        try:
            if client.is_streaming:
                await client.stop_stream()
        except Exception:
            pass
        return RestPhueAdapter(hue, transition_time=transition_time)


async def _await_stop_stream(client: EntertainmentClient) -> None:
    stop_fn = getattr(client, "stop_stream", None)
    if not callable(stop_fn):
        return
    try:
        result = stop_fn()
        if hasattr(result, "__await__"):
            await result
    except Exception as exc:
        logger.warning(f"Entertainment stop_stream: {exc}")


class MirrorControlService:
    """Start/stop/settings/status for mutually exclusive screen and audio mirrors."""

    def __init__(
        self,
        *,
        get_screen: GetScreen,
        get_audio: GetAudio,
        get_hue: GetHue,
        get_manager: GetManager,
        get_entertainment: GetEntertainment,
        get_history: GetHistory | None = None,
        get_last_applied: LastAppliedProvider | None = None,
    ) -> None:
        self._get_screen = get_screen
        self._get_audio = get_audio
        self._get_hue = get_hue
        self._get_manager = get_manager
        self._get_entertainment = get_entertainment
        self._get_history = get_history
        self._get_last_applied = get_last_applied
        self._pending_transport_preference: str = "auto"
        self._pending_area_id: str | None = None

    @property
    def pending_transport_preference(self) -> str:
        return self._pending_transport_preference

    @property
    def pending_area_id(self) -> str | None:
        return self._pending_area_id

    def unified_status(self) -> dict[str, Any]:
        screen = self._get_screen()
        audio = self._get_audio()
        mode = active_mode(screen, audio)
        ent = self._get_entertainment()
        ready = entertainment_ready(ent)
        if mode == "audio":
            status = audio.get_status()
            if not isinstance(status, dict):
                status = {"running": bool(audio.is_running())}
            status["mode"] = "audio"
            status.setdefault("bass", 0.0)
            status.setdefault("mid", 0.0)
            status.setdefault("treble", 0.0)
            status.setdefault("beat", 0.0)
            status.setdefault("spectrum", [])
            status.setdefault(
                "entertainment_enabled", bool(settings.entertainment_enabled)
            )
            status["entertainment_ready"] = ready
            status.setdefault("transport", safe_transport(audio))
            if not isinstance(status.get("transport"), str):
                status["transport"] = safe_transport(audio)
            status.setdefault("entertainment_area_id", safe_area_id(audio))
            return status
        status = screen.get_status()
        if not isinstance(status, dict):
            status = {"running": bool(screen.is_running())}
        status["mode"] = "screen" if mode == "screen" else None
        status.setdefault("bass", 0.0)
        status.setdefault("mid", 0.0)
        status.setdefault("treble", 0.0)
        status.setdefault("beat", 0.0)
        status.setdefault("spectrum", [])
        status.setdefault("transport", safe_transport(screen))
        status.setdefault(
            "entertainment_enabled", bool(settings.entertainment_enabled)
        )
        status["entertainment_ready"] = ready
        status.setdefault("entertainment_area_id", safe_area_id(screen))
        if not isinstance(status.get("transport"), str):
            status["transport"] = safe_transport(screen)
        return status

    async def start(self, mode: str = "screen", **kwargs: Any) -> dict[str, Any]:
        resolved = (mode or "screen").strip().lower()
        if resolved == "audio":
            result = await self._start_audio(**kwargs)
        elif resolved == "screen":
            result = await self._start_screen(**kwargs)
        else:
            raise MirrorValidationError(f"Modo '{mode}' inválido")
        # The capture loop now drives the lights: they leave the last scene
        last_applied = resolve_last_applied(self._get_last_applied)
        if last_applied is not None:
            await last_applied.clear(source=SOURCE_MIRROR)
        return result

    async def stop(self) -> dict[str, Any]:
        screen = self._get_screen()
        audio = self._get_audio()
        mode = active_mode(screen, audio)
        if mode is None:
            raise MirrorNotActiveError("Espelhamento não está ativo")

        await self._snapshot_before_stop()
        _stop_mirror(audio)
        _stop_mirror(screen)

        client = self._get_entertainment()
        if client is not None:
            await _await_stop_stream(client)

        if mode == "audio":
            return {"message": "Espelhamento de música parado"}
        return {"message": "Espelhamento parado"}

    async def apply_settings(
        self,
        *,
        mode: Optional[str] = None,
        profile: Optional[str] = None,
        fps: Optional[int] = None,
        brightness: Optional[int] = None,
        saturation_boost: Optional[float] = None,
        smoothing_factor: Optional[float] = None,
        transition_time: Optional[float] = None,
        energy_gain: Optional[float] = None,
        entertainment_area_id: Optional[str] = None,
        transport_preference: Optional[str] = None,
        config_name: Optional[str] = None,
        config_name_provided: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del kwargs
        screen = self._get_screen()
        audio = self._get_audio()

        if transport_preference is not None:
            self._pending_transport_preference = transport_preference
        if entertainment_area_id is not None:
            self._pending_area_id = entertainment_area_id
            for mirror in (screen, audio):
                try:
                    mirror.entertainment_area_id = entertainment_area_id
                except Exception:
                    pass

        target = mode or active_mode(screen, audio) or "screen"
        if target == "audio":
            self._apply_audio_settings(
                audio,
                profile=profile,
                fps=fps,
                brightness=brightness,
                smoothing_factor=smoothing_factor,
                transition_time=transition_time,
                energy_gain=energy_gain,
                config_name=config_name,
                config_name_provided=config_name_provided,
            )
            return {
                "message": "Configurações de áudio atualizadas",
                "status": self.unified_status(),
            }

        self._apply_screen_settings(
            screen,
            profile=profile,
            fps=fps,
            brightness=brightness,
            saturation_boost=saturation_boost,
            smoothing_factor=smoothing_factor,
            transition_time=transition_time,
        )
        return {
            "message": "Configurações atualizadas",
            "status": self.unified_status(),
        }

    async def _start_audio(self, **kwargs: Any) -> dict[str, Any]:
        profile = kwargs.get("profile")
        fps = kwargs.get("fps")
        brightness = kwargs.get("brightness")
        config_name = kwargs.get("config_name")
        self._validate_profile(profile, audio=True)

        screen = self._get_screen()
        audio = self._get_audio()
        if audio.is_running():
            raise MirrorAlreadyActiveError("Espelhamento de música já está ativo")
        if screen.is_running():
            _stop_mirror(screen)

        if config_name:
            cfg = self._get_manager().get_config(config_name)
            if cfg is None:
                raise MirrorConfigNotFoundError(
                    f"Configuração '{config_name}' não encontrada"
                )
            audio.set_light_config(cfg)
        else:
            audio.set_light_config(None)

        port = await self._prepare_output_port(
            audio,
            transport_preference=kwargs.get("transport_preference"),
            area_id=kwargs.get("area_id"),
        )
        fps = self._fps_for_start(fps, port, profile)
        audio.start(fps=fps, brightness=brightness, profile=profile)
        return {
            "message": "Espelhamento de música iniciado",
            "status": self.unified_status(),
        }

    async def _start_screen(self, **kwargs: Any) -> dict[str, Any]:
        profile = kwargs.get("profile")
        fps = kwargs.get("fps")
        brightness = kwargs.get("brightness")
        self._validate_profile(profile, audio=False)

        screen = self._get_screen()
        audio = self._get_audio()
        if screen.is_running():
            raise MirrorAlreadyActiveError("Espelhamento já está ativo")
        if audio.is_running():
            _stop_mirror(audio)

        port = await self._prepare_output_port(
            screen,
            transport_preference=kwargs.get("transport_preference"),
            area_id=kwargs.get("area_id"),
        )
        fps = self._fps_for_start(fps, port, profile)
        screen.start(fps=fps, brightness=brightness, profile=profile)
        return {
            "message": "Espelhamento iniciado",
            "status": self.unified_status(),
        }

    async def _prepare_output_port(
        self,
        mirror: ScreenMirror | AudioMirror,
        *,
        transport_preference: str | None,
        area_id: str | None,
    ) -> Any:
        transport_pref = (
            transport_preference or self._pending_transport_preference or "auto"
        )
        resolved_area_in = (
            area_id or self._pending_area_id or settings.entertainment_area_id
        )
        hue = self._get_hue()
        ent_client = self._get_entertainment()
        lights = _load_lights(mirror)
        transition_time = _transition_time(mirror)
        try:
            port, resolved_area, _mapped = await _build_port_for_mirror(
                hue,
                ent_client,
                lights=lights,
                area_id=resolved_area_in,
                transport_preference=transport_pref,
                transition_time=transition_time,
            )
        except ValueError as exc:
            raise MirrorValidationError(str(exc)) from exc
        port = await _ensure_entertainment_started(
            port,
            ent_client,
            resolved_area,
            hue,
            transition_time=transition_time,
        )
        set_port = getattr(mirror, "set_output_port", None)
        if callable(set_port):
            set_port(port)
        try:
            mirror.entertainment_enabled = settings.entertainment_enabled
            mirror.entertainment_area_id = resolved_area
        except Exception:
            pass
        return port

    async def _snapshot_before_stop(self) -> None:
        if self._get_history is None:
            return
        try:
            history = self._get_history()
        except RuntimeError:
            return
        if history is None:
            return
        try:
            await history.snapshot(
                self._get_hue(),
                source="mirror_stop",
                label="before mirror stop",
            )
        except Exception as snap_exc:
            logger.warning(f"Scene snapshot before mirror stop failed: {snap_exc}")

    def _validate_profile(self, profile: str | None, *, audio: bool) -> None:
        if profile is None:
            return
        allowed = _AUDIO_PROFILES if audio else _SCREEN_PROFILES
        kind = "audio" if audio else "screen"
        if profile not in allowed:
            raise MirrorValidationError(
                f"Perfil '{profile}' inválido para modo {kind}. "
                f"Use: {', '.join(sorted(allowed))}"
            )

    def _fps_for_start(self, fps: Any, port: Any, profile: str | None) -> Any:
        if (
            fps is None
            and getattr(port, "transport", None) == "entertainment"
            and profile is None
        ):
            return settings.entertainment_fps
        return fps

    def _apply_audio_settings(
        self,
        audio: AudioMirror,
        *,
        profile: str | None,
        fps: int | None,
        brightness: int | None,
        smoothing_factor: float | None,
        transition_time: float | None,
        energy_gain: float | None,
        config_name: str | None,
        config_name_provided: bool,
    ) -> None:
        if profile is not None:
            if profile not in _AUDIO_PROFILES:
                raise MirrorValidationError(
                    f"Perfil '{profile}' inválido para modo audio"
                )
            audio.apply_profile(profile)
        if fps is not None:
            audio.fps = fps
        if brightness is not None:
            audio.brightness = brightness
        if smoothing_factor is not None:
            audio.smoothing_factor = smoothing_factor
        if transition_time is not None:
            audio.transition_time = transition_time
        if energy_gain is not None:
            audio.energy_gain = energy_gain
        if config_name_provided:
            if config_name:
                cfg = self._get_manager().get_config(config_name)
                if cfg is None:
                    raise MirrorConfigNotFoundError(
                        f"Configuração '{config_name}' não encontrada"
                    )
                audio.set_light_config(cfg)
            else:
                audio.set_light_config(None)

    def _apply_screen_settings(
        self,
        screen: ScreenMirror,
        *,
        profile: str | None,
        fps: int | None,
        brightness: int | None,
        saturation_boost: float | None,
        smoothing_factor: float | None,
        transition_time: float | None,
    ) -> None:
        if profile is not None:
            if profile not in _SCREEN_PROFILES:
                raise MirrorValidationError(
                    f"Perfil '{profile}' inválido para modo screen"
                )
            screen.apply_profile(profile)
        if fps is not None:
            screen.fps = fps
        if brightness is not None:
            screen.brightness = brightness
        if saturation_boost is not None:
            screen.saturation_boost = saturation_boost
        if smoothing_factor is not None:
            screen.smoothing_factor = smoothing_factor
        if transition_time is not None:
            screen.transition_time = transition_time
