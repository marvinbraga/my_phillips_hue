"""Serviços fake (sem SQLite, sem bridge) para as tools do chat.

Imitam só a API pública que as tools usam: injetados via ``ChatServices``.
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from marvin_hue.apply_result import ApplyResult
from marvin_hue.audio_mirror import ALL_AUDIO_PROFILES
from marvin_hue.domain.groups import GroupNotFoundError, LightGroup
from marvin_hue.domain.scene_history import SceneHistoryNotFoundError
from marvin_hue.domain.schedules import Schedule, ScheduleNotFoundError
from marvin_hue.screen_mirror import MIRROR_PROFILES
from marvin_hue.services.mirror_control import (
    MirrorAlreadyActiveError,
    MirrorNotActiveError,
    MirrorValidationError,
)


class FakeHistory:
    def __init__(
        self,
        *,
        has_snapshot: bool = True,
        fail_snapshot: bool = False,
        events: list[str] | None = None,
        restored_count: int = 2,
    ) -> None:
        self.has_snapshot = has_snapshot
        self.fail_snapshot = fail_snapshot
        self.snapshots: list[dict[str, Any]] = []
        self.restore_calls = 0
        self.events = events if events is not None else []
        self.restored_count = restored_count

    async def snapshot(self, hue: Any, *, source: str, label: str | None = None) -> Any:
        self.events.append("snapshot")
        if self.fail_snapshot:
            raise OSError("disk I/O error")
        self.snapshots.append({"source": source, "label": label})
        return object()

    async def snapshot_status(self, status, *, source: str, label: str | None = None):
        self.snapshots.append({"source": source, "label": label})
        return object()

    async def restore_last(self, hue: Any) -> dict[str, Any]:
        self.restore_calls += 1
        if not self.has_snapshot:
            raise SceneHistoryNotFoundError("No scene snapshot available to restore")
        return {
            "snapshot_id": "s1",
            "source": "apply",
            "label": "before apply x",
            "created_at": "2026-10-21T10:00:00+00:00",
            "restored_lights": ["Lâmpada 1", "Fita Led"][: self.restored_count],
            "restored_count": self.restored_count,
        }


class FakeGroups:
    """``members`` mapeia group_id → nomes das lâmpadas (padrão: Lâmpada 1)."""

    def __init__(
        self,
        groups: list[LightGroup] | None = None,
        *,
        members: dict[str, list[str]] | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.groups = list(groups or [])
        self.members = members or {}
        self.apply_calls: list[tuple[str, str]] = []
        self.fail_apply = False
        self.events = events if events is not None else []

    async def list_groups(self, *, include_deleted: bool = False) -> list[LightGroup]:
        return list(self.groups)

    async def member_names(self, group_id: str) -> list[str]:
        return list(self.members.get(group_id, ["Lâmpada 1"]))

    async def apply_config(self, group_id, config, hue, *, transition_time_secs=0):
        self.events.append("apply")
        if self.fail_apply:
            raise RuntimeError("bridge timeout")
        group = next((g for g in self.groups if g.id == group_id), None)
        if group is None:
            raise GroupNotFoundError(group_id)
        self.apply_calls.append((group_id, config.name))
        names = set(await self.member_names(group_id))
        return {
            "group_id": group.id,
            "group_name": group.name,
            "config_name": config.name,
            "applied_lights": [s.light_name for s in config.settings if s.light_name in names],
            "transition_time_secs": transition_time_secs,
        }


class FakeSchedules:
    def __init__(self, schedules: list[Schedule] | None = None) -> None:
        self.schedules = list(schedules or [])
        self.created: list[dict[str, Any]] = []
        self.updates: list[tuple[str, dict[str, Any]]] = []
        self.fail_list = False

    async def list_schedules(self) -> list[Schedule]:
        if self.fail_list:
            raise OSError("database is locked")
        return list(self.schedules)

    async def create_schedule(self, **kwargs: Any) -> Schedule:
        schedule = Schedule(id=str(uuid4()), **kwargs)  # domain validates
        self.created.append(kwargs)
        self.schedules.append(schedule)
        return schedule

    async def update_schedule(self, schedule_id: str, **kwargs: Any) -> Schedule:
        for i, s in enumerate(self.schedules):
            if s.id == schedule_id:
                self.updates.append((schedule_id, kwargs))
                updated = Schedule(
                    id=s.id,
                    name=s.name,
                    time_hhmm=s.time_hhmm,
                    action_type=s.action_type,
                    enabled=kwargs.get("enabled", s.enabled),
                    days_of_week=s.days_of_week,
                    action_payload=s.action_payload,
                )
                self.schedules[i] = updated
                return updated
        raise ScheduleNotFoundError(schedule_id)


class FakeMirror:
    def __init__(self, *, mode: str | None = None) -> None:
        self.mode = mode
        self.start_calls: list[tuple[str, dict[str, Any]]] = []
        self.stop_calls = 0

    def unified_status(self) -> dict[str, Any]:
        return {
            "running": self.mode is not None,
            "mode": self.mode,
            "fps": 25,
            "active_profile": "cinema" if self.mode == "screen" else None,
            "transport": "rest",
        }

    async def start(self, mode: str = "screen", **kwargs: Any) -> dict[str, Any]:
        self.start_calls.append((mode, kwargs))
        if mode not in {"screen", "audio"}:
            raise MirrorValidationError(f"Modo '{mode}' inválido")
        profile = kwargs.get("profile")
        allowed = ALL_AUDIO_PROFILES if mode == "audio" else MIRROR_PROFILES
        if profile is not None and profile not in allowed:
            raise MirrorValidationError(
                f"Perfil '{profile}' inválido para modo {mode}. "
                f"Use: {', '.join(sorted(allowed))}"
            )
        if self.mode == mode:
            raise MirrorAlreadyActiveError("Espelhamento já está ativo")
        self.mode = mode
        return {"message": "Espelhamento iniciado", "status": self.unified_status()}

    async def stop(self) -> dict[str, Any]:
        self.stop_calls += 1
        if self.mode is None:
            raise MirrorNotActiveError("Espelhamento não está ativo")
        self.mode = None
        return {"message": "Espelhamento parado"}


class FakeLightsOff:
    def __init__(self, result: ApplyResult | None = None, exc: Exception | None = None):
        self.result = result or ApplyResult(applied=("Lâmpada 1", "Fita Led"), failed=())
        self.exc = exc
        self.calls = 0

    async def turn_off_all(self, *, transition_time: float = 0) -> ApplyResult:
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return self.result


class FakeLastApplied:
    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []
        self.clears: list[str] = []

    async def record(self, name: str, *, source: str) -> None:
        self.records.append((name, source))

    async def clear(self, *, source: str) -> None:
        self.clears.append(source)


HEALTH_PAYLOAD: dict[str, Any] = {
    "bridge": {"connected": True, "bridge_ip": "10.0.0.2", "light_count": 9},
    "lights": {"total": 9, "unreachable": 1, "disabled_in_app": 2},
    "mirror": {"running": False, "fps": None, "profile": None},
    "chat": {"available": True, "reason": None},
    "registry": {"count": 9, "db_path": "x", "last_sync_at": None},
    "schedules": {"enabled_count": 3, "runner_alive": True},
    "timestamp": "2026-10-21T10:00:00+00:00",
}


def services(**providers: Any):
    """ChatServices com providers fixos (None → serviço indisponível)."""
    from marvin_hue.chat.services import ChatServices

    def const(value: Any):
        return lambda: value

    kwargs = {f"{k}_provider": const(v) for k, v in providers.items()}
    defaults = {
        "favorites_provider": const(None),
        "history_provider": const(None),
        "groups_provider": const(None),
        "schedules_provider": const(None),
        "mirror_provider": const(None),
        "health_provider": const(None),
        "last_applied_provider": const(None),
    }
    defaults.update(kwargs)
    return ChatServices(**defaults)


def scripted_model(router):
    """Chat model fake que decide a resposta pelo conteúdo das mensagens.

    O mesmo ``self._llm`` serve orquestrador, subagents e SummarizationMiddleware;
    uma lista fixa de respostas seria consumida fora de ordem (e reciclada).
    ``router(messages) -> AIMessage`` torna o roteiro determinístico.
    """
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    class _Scripted(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            return ChatResult(generations=[ChatGeneration(message=router(messages))])

    return _Scripted(responses=[AIMessage(content="unused")])


# --- HITL: roteiro determinístico do orquestrador real + scene-designer -------

SCENE_DESIGNER_MARKER = "Você é o scene-designer"

START_MIRROR = {"name": "start_mirror", "args": {"mode": "screen"}}
CREATE_SCHEDULE = {
    "name": "create_schedule",
    "args": {"name": "noite", "time_hhmm": "22:00", "action": "power_off"},
}


def create_config_call(name: str) -> tuple[str, dict]:
    return "create_config", {
        "name": name,
        "description": "cena calma",
        "settings": [
            {"light_name": "Lâmpada 1", "red": 10, "green": 20, "blue": 200,
             "brightness_pct": 40},
        ],
    }


def task_call(description: str) -> dict:
    return {
        "name": "task",
        "args": {"description": description, "subagent_type": "scene-designer"},
    }


class HitlRouter:
    """Roteia pelo TEXTO achatado (``message_text``) das mensagens.

    ``rounds``: tool calls do orquestrador por rodada do turno atual (rodada =
    AIMessage com tool_calls desde a última HumanMessage). Esgotadas, ele
    responde ``"fim: <ToolMessages do turno>"``. O subagent é reconhecido
    pelo marcador único do prompt e chama ``sub_call(HumanMessage)``.
    """

    def __init__(self, *rounds: list[dict], sub_call=None):
        self.rounds = rounds
        self.sub_call = sub_call
        self.orch_steps = 0
        self.sub_human_steps = 0

    @staticmethod
    def _system_text(messages) -> str:
        from langchain_core.messages import SystemMessage

        from marvin_hue.chat.messages import message_text

        first = messages[0] if messages else None
        return message_text(first.content) if isinstance(first, SystemMessage) else ""

    def __call__(self, messages):
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        last = messages[-1]
        if SCENE_DESIGNER_MARKER in self._system_text(messages):
            if isinstance(last, HumanMessage):
                self.sub_human_steps += 1
                name, args = self.sub_call(last)
                return AIMessage(
                    content="",
                    tool_calls=[{"name": name, "args": args, "id": f"sub-{last.content}"}],
                )
            return AIMessage(content=f"sub ok: {last.content}")

        self.orch_steps += 1
        humans = [i for i, m in enumerate(messages) if isinstance(m, HumanMessage)]
        turn = messages[humans[-1] + 1:] if humans else list(messages)
        done = sum(1 for m in turn if isinstance(m, AIMessage) and m.tool_calls)
        if done < len(self.rounds):
            calls = [
                {**c, "id": f"t{len(humans)}-r{done}-{i}"}
                for i, c in enumerate(self.rounds[done])
            ]
            return AIMessage(content="", tool_calls=calls)
        texts = [str(m.content) for m in turn if isinstance(m, ToolMessage)]
        return AIMessage(content="fim: " + " | ".join(texts))


def hitl_agent(monkeypatch, controller, manager, router, *, require_approval=True,
               checkpointer=None, **service_overrides):
    """create_hue_agent REAL com o provider trocado pelo modelo roteirizado."""
    import marvin_hue.chat.agents.react_agent as ra
    from marvin_hue.chat import create_hue_agent

    class _FakeProvider:
        model = scripted_model(router)

    monkeypatch.setattr(
        ra.LLMProviderFactory, "create", classmethod(lambda cls, **kw: _FakeProvider())
    )
    service_overrides.setdefault("mirror", FakeMirror())
    return create_hue_agent(
        controller=controller,
        manager=manager,
        require_approval=require_approval,
        services=services(**service_overrides),
        checkpointer=checkpointer,
    )


def decide_all(pending, kind: str = "approve") -> list[dict]:
    """Uma decisão por pedido pendente, com o id obrigatório."""
    return [{"id": r.id, "type": kind} for r in pending.requests]
