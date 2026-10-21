"""Tools de automação do chat: grupos e agendamentos.

Invólucros finos sobre ``GroupService`` e ``ScheduleService`` (async,
aiosqlite). Grupo e agendamento são identificados pelo nome, sem diferenciar
maiúsculas, ou pelo id (P3). Ações de agendamento expostas: ``apply_config``,
``power_on`` e ``power_off`` (P4). Erros viram mensagem, nunca exceção.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from marvin_hue.basics import LightSetupsManager
from marvin_hue.chat.services import ChatServices
from marvin_hue.chat.tools._common import (
    SINGLE_LINE,
    resolve_by_name,
    resolve_scene,
    service_tool,
    unavailable,
    unexpected_error,
)
from marvin_hue.domain.groups import GroupNotFoundError
from marvin_hue.domain.schedules import ScheduleNotFoundError, ScheduleValidationError
from marvin_hue.logging_config import get_logger

if TYPE_CHECKING:
    from marvin_hue.controllers import HueController

logger = get_logger("chat.automation_tools")

_GROUPS_LABEL = "Grupos"
_SCHEDULES_LABEL = "Agendamentos"
_WEEKDAYS = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")
_ACTION_LABELS = {
    "apply_config": "aplicar cena",
    "power_on": "ligar tudo",
    "power_off": "desligar tudo",
    "apply_group": "aplicar cena em grupo",
}


class _ApplyGroupArgs(BaseModel):
    group: str = Field(max_length=100, description="Nome ou id do grupo")
    config_name: str = Field(max_length=100, description="Nome da cena a aplicar")


class _CreateScheduleArgs(BaseModel):
    name: str = Field(
        min_length=1, max_length=100, pattern=SINGLE_LINE, description="Nome do agendamento"
    )
    time_hhmm: str = Field(description="Horário local HH:MM (24h)")
    action: Literal["apply_config", "power_on", "power_off"] = Field(
        description="apply_config (exige config_name), power_on ou power_off"
    )
    config_name: str | None = Field(
        default=None, max_length=100, description="Cena (só apply_config)"
    )
    days: list[Annotated[int, Field(ge=0, le=6)]] = Field(
        default_factory=list,
        description="0=segunda … 6=domingo; vazio = todo dia",
    )
    enabled: bool = Field(
        default=False,
        description="Criar já ativo? Só True se o usuário pedir explicitamente",
    )


class _SetScheduleEnabledArgs(BaseModel):
    schedule: str = Field(max_length=100, description="Nome ou id do agendamento")
    enabled: bool = Field(description="True para ativar, False para desativar")


def _days_label(csv: str) -> str:
    if not csv:
        return "todo dia"
    return ",".join(_WEEKDAYS[int(d)] for d in csv.split(",") if d.strip().isdigit())


def build_automation_tools(
    controller: "HueController",
    manager: LightSetupsManager,
    services: ChatServices,
) -> list[BaseTool]:
    """Tools de grupos e agendamentos (todas async com fallback síncrono)."""

    # ----- grupos -----
    async def _list_groups() -> str:
        svc = services.groups()
        if svc is None:
            return unavailable(_GROUPS_LABEL)
        try:
            groups = await svc.list_groups()
        except Exception as e:  # noqa: BLE001
            return unexpected_error("listar grupos", e)
        if not groups:
            return "Nenhum grupo cadastrado."
        lines = ["Grupos:"]
        for g in groups:
            room = f", sala {g.room}" if g.room else ""
            lines.append(f"- {g.name}: {len(g.light_ids)} lâmpada(s){room}")
        return "\n".join(lines)

    async def _apply_config_to_group(group: str, config_name: str) -> str:
        svc = services.groups()
        if svc is None:
            return unavailable(_GROUPS_LABEL)
        scene, error = resolve_scene(manager, config_name)
        if scene is None:
            return error or ""
        config = manager.get_config(scene)
        try:
            groups = await svc.list_groups()
        except Exception as e:  # noqa: BLE001
            return unexpected_error("listar grupos", e)
        target, error = resolve_by_name(
            groups, group, kind="grupo", id_of=lambda g: g.id, name_of=lambda g: g.name
        )
        if target is None:
            return error or ""
        try:
            members = set(await svc.member_names(target.id))
        except GroupNotFoundError:
            return f"Grupo '{group}' não encontrado."
        except Exception as e:  # noqa: BLE001
            return unexpected_error("ler as lâmpadas do grupo", e)
        # Sem interseção cena∩grupo não há o que aplicar: nem snapshot, nem apply.
        if not any(s.light_name in members for s in config.settings):
            return (
                f"Nenhuma lâmpada da cena '{scene}' pertence ao grupo '{target.name}'. "
                "Nada foi alterado."
            )
        await _snapshot_fail_open(f"before apply {scene}")
        try:
            result = await svc.apply_config(target.id, config, controller)
        except GroupNotFoundError:
            return f"Grupo '{group}' não encontrado."
        except Exception as e:  # noqa: BLE001
            return unexpected_error("aplicar a cena no grupo", e)
        applied = result.get("applied_lights") or []
        if not applied:
            return (
                f"Nenhuma lâmpada da cena '{scene}' pertence ao grupo '{target.name}'."
            )
        return (
            f"Cena '{scene}' aplicada ao grupo '{target.name}' "
            f"(lâmpadas: {', '.join(applied)})."
        )

    async def _snapshot_fail_open(label: str) -> None:
        # Como routes/groups.py: snapshot antes, para o Desfazer funcionar (P2).
        history = services.history()
        if history is None:
            return
        try:
            await history.snapshot(controller, source="group_apply", label=label)
        except Exception as e:  # noqa: BLE001 — fail-open: aplica mesmo assim
            logger.warning(f"Chat group apply snapshot failed: {e}")

    # ----- agendamentos -----
    async def _list_schedules() -> str:
        svc = services.schedules()
        if svc is None:
            return unavailable(_SCHEDULES_LABEL)
        try:
            schedules = await svc.list_schedules()
        except Exception as e:  # noqa: BLE001
            return unexpected_error("listar agendamentos", e)
        if not schedules:
            return "Nenhum agendamento cadastrado."
        lines = ["Agendamentos:"]
        for s in schedules:
            action = _ACTION_LABELS.get(s.action_type, s.action_type)
            scene = s.action_payload.get("config_name")
            if scene:
                action += f" '{scene}'"
            state = "ativo" if s.enabled else "desativado"
            lines.append(
                f"- {s.name}: {s.time_hhmm} ({_days_label(s.days_of_week)}), "
                f"{action}, {state}"
            )
        return "\n".join(lines)

    async def _create_schedule(
        name: str,
        time_hhmm: str,
        action: str,
        config_name: str | None = None,
        days: list[int] | None = None,
        enabled: bool = False,
    ) -> str:
        svc = services.schedules()
        if svc is None:
            return unavailable(_SCHEDULES_LABEL)
        payload: dict[str, str] = {}
        if action == "apply_config":
            if not config_name:
                return "Informe config_name para a ação apply_config."
            scene, error = resolve_scene(manager, config_name)
            if scene is None:
                return error or ""
            payload = {"config_name": scene}
        days_csv = ",".join(str(d) for d in sorted(set(days or [])))
        try:
            created = await svc.create_schedule(
                name=name,
                time_hhmm=time_hhmm,
                action_type=action,
                enabled=enabled,
                days_of_week=days_csv,
                action_payload=payload,
            )
        except ScheduleValidationError as e:
            return f"Agendamento inválido: {e}"
        except Exception as e:  # noqa: BLE001
            return unexpected_error("criar agendamento", e)
        state = "ativo" if created.enabled else "desativado"
        return (
            f"Agendamento '{created.name}' criado: {created.time_hhmm} "
            f"({_days_label(created.days_of_week)}), "
            f"{_ACTION_LABELS.get(action, action)}, {state}."
        )

    async def _set_schedule_enabled(schedule: str, enabled: bool) -> str:
        svc = services.schedules()
        if svc is None:
            return unavailable(_SCHEDULES_LABEL)
        try:
            schedules = await svc.list_schedules()
        except Exception as e:  # noqa: BLE001
            return unexpected_error("listar agendamentos", e)
        target, error = resolve_by_name(
            schedules,
            schedule,
            kind="agendamento",
            id_of=lambda s: s.id,
            name_of=lambda s: s.name,
        )
        if target is None:
            return error or ""
        word = "ativado" if enabled else "desativado"
        if target.enabled == enabled:
            return f"O agendamento '{target.name}' já estava {word}."
        try:
            await svc.update_schedule(target.id, enabled=enabled)
        except ScheduleNotFoundError:
            return f"Agendamento '{schedule}' não encontrado."
        except Exception as e:  # noqa: BLE001
            return unexpected_error("alterar agendamento", e)
        return f"Agendamento '{target.name}' {word}."

    def groups_ready() -> bool:
        return services.groups() is not None

    def schedules_ready() -> bool:
        return services.schedules() is not None

    return [
        service_tool(
            name="list_groups",
            description="Lista os grupos de lâmpadas cadastrados (grupos não são salas).",
            coroutine=_list_groups,
            label=_GROUPS_LABEL,
            is_available=groups_ready,
        ),
        service_tool(
            name="apply_config_to_group",
            description=(
                "Aplica uma cena só às lâmpadas de um grupo (nome ou id); "
                "para a cena inteira use apply_config."
            ),
            coroutine=_apply_config_to_group,
            label=_GROUPS_LABEL,
            is_available=groups_ready,
            args_schema=_ApplyGroupArgs,
        ),
        service_tool(
            name="list_schedules",
            description="Lista os agendamentos com horário, dias, ação e estado.",
            coroutine=_list_schedules,
            label=_SCHEDULES_LABEL,
            is_available=schedules_ready,
        ),
        service_tool(
            name="create_schedule",
            description=(
                "Cria agendamento (0=seg … 6=dom). Nasce desativado; só use "
                "enabled=True se o usuário pedir para ativar."
            ),
            coroutine=_create_schedule,
            label=_SCHEDULES_LABEL,
            is_available=schedules_ready,
            args_schema=_CreateScheduleArgs,
        ),
        service_tool(
            name="set_schedule_enabled",
            description="Ativa ou desativa um agendamento (nome ou id).",
            coroutine=_set_schedule_enabled,
            label=_SCHEDULES_LABEL,
            is_available=schedules_ready,
            args_schema=_SetScheduleEnabledArgs,
        ),
    ]
