"""Tools de sistema do chat: espelhamento, saúde e temperatura de cor.

- Espelhamento: invólucro de ``MirrorControlService`` (start/stop async; status
  é o ``unified_status`` síncrono, resumido — nunca o dict bruto).
- Saúde: coletor do ``ChatServices`` (mesmos argumentos de ``GET /api/health``).
- Temperatura de cor: Kelvin → RGB (``color_temperature``) e
  ``HueController.set_light_color``, o ponto autoritativo de segurança ocular
  (P8/P13). Tool síncrona: só controller, sem serviço async.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from marvin_hue.chat.services import ChatServices
from marvin_hue.chat.tools._common import (
    logger,
    pct_to_hue,
    service_tool,
    unavailable,
    unexpected_error,
)
from marvin_hue.chat.tools.color_temperature import (
    KELVIN_MAX,
    KELVIN_MIN,
    kelvin_to_rgb,
)
from marvin_hue.chat.tools.rooms import enabled_names, resolve_room_lights
from marvin_hue.colors import Color
from marvin_hue.services.mirror_control import (
    MirrorAlreadyActiveError,
    MirrorControlError,
    MirrorNotActiveError,
)

if TYPE_CHECKING:
    from marvin_hue.controllers import HueController

_MIRROR_LABEL = "Espelhamento"
_HEALTH_LABEL = "Saúde do sistema"
_MODE_LABELS = {"screen": "tela", "audio": "música"}
_DEFAULT_TEMPERATURE_PCT = 80


class _StartMirrorArgs(BaseModel):
    mode: Literal["screen", "audio"] = Field(
        default="screen", description="screen (tela) ou audio (música)"
    )
    profile: str | None = Field(
        default=None,
        max_length=32,
        description="Perfil opcional (tela: cinema, fps, ambient; música: party, chill…)",
    )


class _ColorTemperatureArgs(BaseModel):
    target: str = Field(
        max_length=100, description="Lâmpada, sala/local (ex.: 'teto') ou 'all'"
    )
    kelvin: int = Field(
        ge=KELVIN_MIN, le=KELVIN_MAX, description="2000 (quente) a 6500 K (fria)"
    )
    brightness_pct: int | None = Field(
        default=None, ge=0, le=100, description="Brilho 0-100% (padrão 80)"
    )


def _mirror_summary(status: Mapping[str, Any]) -> str:
    if not status.get("running"):
        return "Espelhamento inativo."
    parts = [f"modo {_MODE_LABELS.get(str(status.get('mode')), status.get('mode') or '?')}"]
    if status.get("fps") is not None:
        parts.append(f"{status['fps']} FPS")
    profile = status.get("active_profile") or status.get("profile")
    if profile:
        parts.append(f"perfil {profile}")
    if isinstance(status.get("transport"), str):
        parts.append(f"transporte {status['transport']}")
    return "Espelhamento ativo: " + ", ".join(parts) + "."


def _health_summary(payload: Mapping[str, Any]) -> str:
    bridge = payload.get("bridge") or {}
    lights = payload.get("lights") or {}
    mirror = payload.get("mirror") or {}
    chat = payload.get("chat") or {}
    schedules = payload.get("schedules") or {}
    if bridge.get("connected"):
        bridge_line = (
            f"conectada ({bridge.get('bridge_ip', '?')}, "
            f"{bridge.get('light_count', 0)} lâmpadas)"
        )
    else:
        bridge_line = f"desconectada ({bridge.get('error', 'sem resposta')})"
    mirror_line = "ativo" if mirror.get("running") else "parado"
    if mirror.get("running"):
        details: list[str] = []
        mode_label = _MODE_LABELS.get(str(mirror.get("mode")))
        if mode_label:
            details.append(mode_label)
        if mirror.get("fps") is not None:
            details.append(f"{mirror['fps']} FPS")
        if details:
            mirror_line += f" ({', '.join(details)})"
    chat_line = "disponível" if chat.get("available") else (
        f"indisponível ({chat.get('reason') or 'sem motivo'})"
    )
    runner = "rodando" if schedules.get("runner_alive") else "parado"
    return "\n".join(
        [
            "Saúde do sistema:",
            f"- Bridge: {bridge_line}",
            f"- Lâmpadas: {lights.get('total', 0)} no total, "
            f"{lights.get('unreachable', 0)} inacessível(eis), "
            f"{lights.get('disabled_in_app', 0)} desabilitada(s) no app",
            f"- Espelhamento: {mirror_line}",
            f"- Chat: {chat_line}",
            f"- Agendamentos: {schedules.get('enabled_count', 0)} ativo(s), "
            f"runner {runner}",
        ]
    )


def build_system_tools(
    controller: "HueController",
    services: ChatServices,
    *,
    rooms: Mapping[str, Sequence[str]] | None = None,
) -> list[BaseTool]:
    """Tools de espelhamento, saúde e temperatura de cor."""
    rooms_map: Mapping[str, Sequence[str]] = rooms if rooms is not None else {}

    # ----- espelhamento -----
    def _get_mirror_status() -> str:
        svc = services.mirror()
        if svc is None:
            return unavailable(_MIRROR_LABEL)
        try:
            return _mirror_summary(svc.unified_status())
        except Exception as e:  # noqa: BLE001
            return unexpected_error("consultar o espelhamento", e)

    async def _start_mirror(mode: str = "screen", profile: str | None = None) -> str:
        svc = services.mirror()
        if svc is None:
            return unavailable(_MIRROR_LABEL)
        try:
            # Perfil validado pelo serviço (tela e música têm conjuntos próprios).
            result = await svc.start(mode, profile=profile)
        except MirrorAlreadyActiveError:
            return f"O espelhamento de {_MODE_LABELS.get(mode, mode)} já está ativo."
        except (MirrorControlError, ValueError) as e:  # domínio: perfil/área/config
            return f"Não foi possível iniciar o espelhamento: {e}"
        except Exception as e:  # noqa: BLE001
            return unexpected_error("iniciar o espelhamento", e)
        data = result if isinstance(result, dict) else {}
        status = data.get("status")
        summary = f" {_mirror_summary(status)}" if isinstance(status, dict) else ""
        return f"{data.get('message', 'Espelhamento iniciado')}.{summary}"

    async def _stop_mirror() -> str:
        svc = services.mirror()
        if svc is None:
            return unavailable(_MIRROR_LABEL)
        try:
            result = await svc.stop()
        except MirrorNotActiveError:
            return "Nenhum espelhamento ativo."
        except Exception as e:  # noqa: BLE001
            return unexpected_error("parar o espelhamento", e)
        data = result if isinstance(result, dict) else {}
        return f"{data.get('message', 'Espelhamento parado')}."

    # ----- saúde -----
    async def _get_system_health() -> str:
        collect = services.health()
        if collect is None:
            return unavailable(_HEALTH_LABEL)
        try:
            payload = await collect()
        except Exception as e:  # noqa: BLE001
            return unexpected_error("consultar a saúde do sistema", e)
        return _health_summary(payload)

    # ----- temperatura de cor (sync, só controller) -----
    def _resolve_targets(target: str) -> tuple[str, list[str]] | str:
        raw = (target or "").strip()
        try:
            lights = list(controller.list_lights())
        except Exception as e:  # noqa: BLE001
            return unexpected_error("listar lâmpadas", e)
        if raw.lower() == "all":
            return "todas as lâmpadas", enabled_names(lights)
        by_key = {n.casefold(): n for n in lights}
        if raw.casefold() in by_key:
            name = by_key[raw.casefold()]
            return f"'{name}'", [name]
        in_rooms = resolve_room_lights(rooms_map, raw)
        if in_rooms is not None:
            return in_rooms
        return (
            f"Alvo '{target}' não encontrado (nem lâmpada, nem sala). "
            f"Lâmpadas: {', '.join(lights) or 'nenhuma'}."
        )

    def _set_color_temperature(
        target: str, kelvin: int, brightness_pct: int | None = None
    ) -> str:
        resolved = _resolve_targets(target)
        if isinstance(resolved, str):
            return resolved
        label, names = resolved
        if not names:
            return f"Nenhuma lâmpada habilitada em {label}."
        k = kelvin
        r, g, b = kelvin_to_rgb(k)
        pct = _DEFAULT_TEMPERATURE_PCT if brightness_pct is None else brightness_pct
        hue_brightness = pct_to_hue(pct)
        ok: list[str] = []
        failed: list[str] = []
        for name in names:
            try:
                # Controller aplica o teto de segurança ocular e pula desabilitadas.
                controller.set_light_color(name, Color(r, g, b, hue_brightness))
                ok.append(name)
            except ValueError as e:  # domínio: desabilitada/inexistente
                failed.append(f"{name} ({e})")
            except Exception as e:  # noqa: BLE001
                logger.opt(exception=e).warning(f"set_color_temperature {name!r}: {e!r}")
                failed.append(f"{name} (erro inesperado)")
        msg = (
            f"Temperatura {k}K, RGB({r},{g},{b}), brilho {pct}% em {label}: "
            f"{len(ok)} lâmpada(s)."
        )
        if failed:
            msg += f" Falha/skip: {', '.join(failed)}."
        return msg

    def mirror_ready() -> bool:
        return services.mirror() is not None

    return [
        StructuredTool.from_function(
            func=_get_mirror_status,
            name="get_mirror_status",
            description="Resumo do espelhamento de tela ou música (ativo, modo, FPS, perfil).",
        ),
        service_tool(
            name="start_mirror",
            description="Inicia o espelhamento de tela ou de música, com perfil opcional.",
            coroutine=_start_mirror,
            label=_MIRROR_LABEL,
            is_available=mirror_ready,
            args_schema=_StartMirrorArgs,
        ),
        service_tool(
            name="stop_mirror",
            description="Para o espelhamento ativo. Idempotente.",
            coroutine=_stop_mirror,
            label=_MIRROR_LABEL,
            is_available=mirror_ready,
        ),
        StructuredTool.from_function(
            func=_set_color_temperature,
            name="set_color_temperature",
            description=(
                "Luz branca por temperatura (2000 quente a 6500 K fria) em "
                "lâmpada, sala/local (ex.: 'teto') ou 'all'."
            ),
            args_schema=_ColorTemperatureArgs,
        ),
        service_tool(
            name="get_system_health",
            description="Resumo da saúde: bridge, lâmpadas, espelhamento, chat e agendamentos.",
            coroutine=_get_system_health,
            label=_HEALTH_LABEL,
            is_available=lambda: services.health() is not None,
        ),
    ]
