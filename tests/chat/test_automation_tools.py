"""Tools de grupos e agendamentos (P2, P3, P4)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from marvin_hue.domain.groups import LightGroup
from marvin_hue.domain.schedules import Schedule
from tests.chat.fakes import FakeGroups, FakeHistory, FakeSchedules, services


def _tools(controller, manager, svc):
    from marvin_hue.chat.tools.automation_tools import build_automation_tools

    return {t.name: t for t in build_automation_tools(controller, manager, svc)}


@pytest.fixture
def groups():
    return FakeGroups(
        [
            LightGroup(id="g-1", name="Sala", room="sala", light_ids=["a", "b"]),
            LightGroup(id="g-2", name="Escritório", light_ids=["c"]),
        ]
    )


def _schedule(sid, name, enabled=True, action="power_off", payload=None):
    return Schedule(
        id=sid,
        name=name,
        time_hhmm="22:30",
        action_type=action,
        enabled=enabled,
        days_of_week="0,1,2,3,4",
        action_payload=payload or {},
    )


@pytest.fixture
def schedules():
    return FakeSchedules(
        [
            _schedule("s-1", "Dormir"),
            _schedule(
                "s-2", "Acordar", enabled=False, action="apply_config",
                payload={"config_name": "noite_relaxante"},
            ),
        ]
    )


# ----- list_groups -----


async def test_list_groups(fake_controller, fake_manager, groups):
    out = await _tools(fake_controller, fake_manager, services(groups=groups))[
        "list_groups"
    ].ainvoke({})
    assert out == (
        "Grupos:\n- Sala: 2 lâmpada(s), sala sala\n- Escritório: 1 lâmpada(s)"
    )


async def test_list_groups_service_error_is_generic(fake_controller, fake_manager):
    class _Broken(FakeGroups):
        async def list_groups(self, *, include_deleted=False):
            raise OSError("database is locked at /secret")

    out = await _tools(fake_controller, fake_manager, services(groups=_Broken()))[
        "list_groups"
    ].ainvoke({})
    assert out.startswith("Erro inesperado ao listar grupos")
    assert "/secret" not in out


async def test_list_groups_empty(fake_controller, fake_manager):
    out = await _tools(fake_controller, fake_manager, services(groups=FakeGroups()))[
        "list_groups"
    ].ainvoke({})
    assert "Nenhum grupo" in out


async def test_list_groups_unavailable(fake_controller, fake_manager):
    out = await _tools(fake_controller, fake_manager, services())["list_groups"].ainvoke({})
    assert "indisponível" in out


def test_list_groups_sync_path_app_only(fake_controller, fake_manager, groups):
    out = _tools(fake_controller, fake_manager, services(groups=groups))[
        "list_groups"
    ].invoke({})
    assert "apenas no app" in out


# ----- apply_config_to_group -----


async def test_apply_config_to_group_snapshots_first(fake_controller, fake_manager):
    events: list[str] = []
    groups = FakeGroups([LightGroup(id="g-1", name="Sala")], events=events)
    history = FakeHistory(events=events)
    tool = _tools(fake_controller, fake_manager, services(groups=groups, history=history))[
        "apply_config_to_group"
    ]
    out = await tool.ainvoke({"group": "sala", "config_name": "noite_relaxante"})
    assert events == ["snapshot", "apply"]
    assert groups.apply_calls == [("g-1", "noite_relaxante")]
    assert history.snapshots == [
        {"source": "group_apply", "label": "before apply noite_relaxante"}
    ]
    assert out == (
        "Cena 'noite_relaxante' aplicada ao grupo 'Sala' (lâmpadas: Lâmpada 1)."
    )


async def test_apply_config_to_group_no_overlap_skips_everything(fake_controller, fake_manager):
    events: list[str] = []
    groups = FakeGroups(
        [LightGroup(id="g-1", name="Sala")], members={"g-1": ["Hue Iris"]}, events=events
    )
    history = FakeHistory(events=events)
    tool = _tools(fake_controller, fake_manager, services(groups=groups, history=history))[
        "apply_config_to_group"
    ]
    out = await tool.ainvoke({"group": "Sala", "config_name": "noite_relaxante"})
    assert events == []
    assert "Nenhuma lâmpada da cena 'noite_relaxante' pertence ao grupo 'Sala'" in out


async def test_apply_config_to_group_by_id(fake_controller, fake_manager, groups):
    tool = _tools(fake_controller, fake_manager, services(groups=groups))[
        "apply_config_to_group"
    ]
    await tool.ainvoke({"group": "g-2", "config_name": "noite_relaxante"})
    assert groups.apply_calls == [("g-2", "noite_relaxante")]


async def test_apply_config_to_group_snapshot_failure_is_fail_open(
    fake_controller, fake_manager, groups
):
    history = FakeHistory(fail_snapshot=True)
    tool = _tools(fake_controller, fake_manager, services(groups=groups, history=history))[
        "apply_config_to_group"
    ]
    await tool.ainvoke({"group": "Sala", "config_name": "noite_relaxante"})
    assert groups.apply_calls == [("g-1", "noite_relaxante")]


async def test_apply_config_to_group_unknown_group(fake_controller, fake_manager, groups):
    tool = _tools(fake_controller, fake_manager, services(groups=groups))[
        "apply_config_to_group"
    ]
    out = await tool.ainvoke({"group": "Cozinha", "config_name": "noite_relaxante"})
    assert "não encontrado" in out and "Sala" in out
    assert groups.apply_calls == []


async def test_apply_config_to_group_ambiguous(fake_controller, fake_manager):
    groups = FakeGroups(
        [LightGroup(id="g-1", name="Sala"), LightGroup(id="g-9", name="SALA")]
    )
    tool = _tools(fake_controller, fake_manager, services(groups=groups))[
        "apply_config_to_group"
    ]
    out = await tool.ainvoke({"group": "sala", "config_name": "noite_relaxante"})
    assert "ambíguo" in out
    assert groups.apply_calls == []


async def test_apply_config_to_group_unknown_scene(fake_controller, fake_manager, groups):
    history = FakeHistory()
    tool = _tools(fake_controller, fake_manager, services(groups=groups, history=history))[
        "apply_config_to_group"
    ]
    out = await tool.ainvoke({"group": "Sala", "config_name": "nada"})
    assert "não existe" in out
    assert groups.apply_calls == [] and history.snapshots == []


async def test_apply_config_to_group_service_error(fake_controller, fake_manager, groups):
    groups.fail_apply = True
    tool = _tools(fake_controller, fake_manager, services(groups=groups))[
        "apply_config_to_group"
    ]
    out = await tool.ainvoke({"group": "Sala", "config_name": "noite_relaxante"})
    assert out.startswith("Erro inesperado ao aplicar a cena no grupo")
    assert "bridge timeout" not in out


# ----- list_schedules -----


async def test_list_schedules(fake_controller, fake_manager, schedules):
    out = await _tools(fake_controller, fake_manager, services(schedules=schedules))[
        "list_schedules"
    ].ainvoke({})
    assert "Dormir" in out and "22:30" in out and "Acordar" in out
    assert "noite_relaxante" in out and "desativado" in out


async def test_list_schedules_service_error(fake_controller, fake_manager, schedules):
    schedules.fail_list = True
    out = await _tools(fake_controller, fake_manager, services(schedules=schedules))[
        "list_schedules"
    ].ainvoke({})
    assert out.startswith("Erro inesperado ao listar agendamentos")


# ----- create_schedule -----


async def test_create_schedule_apply_config(fake_controller, fake_manager, schedules):
    tool = _tools(fake_controller, fake_manager, services(schedules=schedules))[
        "create_schedule"
    ]
    out = await tool.ainvoke(
        {
            "name": "Relaxar",
            "time_hhmm": "21:00",
            "action": "apply_config",
            "config_name": "NOITE_relaxante",
            "days": [5, 6],
            "enabled": False,
        }
    )
    created = schedules.created[-1]
    assert created["action_type"] == "apply_config"
    assert created["action_payload"] == {"config_name": "noite_relaxante"}
    assert created["days_of_week"] == "5,6"
    assert created["enabled"] is False
    assert "Relaxar" in out and "21:00" in out


async def test_create_schedule_defaults_to_disabled(fake_controller, fake_manager, schedules):
    tool = _tools(fake_controller, fake_manager, services(schedules=schedules))[
        "create_schedule"
    ]
    out = await tool.ainvoke({"name": "Apagar", "time_hhmm": "23:00", "action": "power_off"})
    created = schedules.created[-1]
    assert created["action_payload"] == {} and created["days_of_week"] == ""
    assert created["enabled"] is False
    assert out == (
        "Agendamento 'Apagar' criado: 23:00 (todo dia), desligar tudo, desativado."
    )


async def test_create_schedule_apply_config_requires_scene(
    fake_controller, fake_manager, schedules
):
    tool = _tools(fake_controller, fake_manager, services(schedules=schedules))[
        "create_schedule"
    ]
    out = await tool.ainvoke({"name": "X", "time_hhmm": "21:00", "action": "apply_config"})
    assert "config_name" in out
    out = await tool.ainvoke(
        {"name": "X", "time_hhmm": "21:00", "action": "apply_config", "config_name": "nada"}
    )
    assert "não existe" in out
    assert schedules.created == []


async def test_create_schedule_invalid_time_becomes_message(
    fake_controller, fake_manager, schedules
):
    tool = _tools(fake_controller, fake_manager, services(schedules=schedules))[
        "create_schedule"
    ]
    out = await tool.ainvoke({"name": "X", "time_hhmm": "25:99", "action": "power_on"})
    assert "inválid" in out.lower()
    assert schedules.created == []


def test_create_schedule_rejects_bad_action_and_days(fake_controller, fake_manager, schedules):
    tool = _tools(fake_controller, fake_manager, services(schedules=schedules))[
        "create_schedule"
    ]
    with pytest.raises(ValidationError):
        tool.invoke({"name": "X", "time_hhmm": "21:00", "action": "apply_group"})
    with pytest.raises(ValidationError):
        tool.invoke({"name": "X", "time_hhmm": "21:00", "action": "power_on", "days": [7]})
    with pytest.raises(ValidationError):
        tool.invoke({"name": "n" * 101, "time_hhmm": "21:00", "action": "power_on"})
    with pytest.raises(ValidationError):
        tool.invoke({"name": "a\nb", "time_hhmm": "21:00", "action": "power_on"})


# ----- set_schedule_enabled -----


async def test_set_schedule_enabled(fake_controller, fake_manager, schedules):
    tool = _tools(fake_controller, fake_manager, services(schedules=schedules))[
        "set_schedule_enabled"
    ]
    out = await tool.ainvoke({"schedule": "acordar", "enabled": True})
    assert schedules.updates == [("s-2", {"enabled": True})]
    assert out == "Agendamento 'Acordar' ativado."


async def test_set_schedule_enabled_idempotent(fake_controller, fake_manager, schedules):
    tool = _tools(fake_controller, fake_manager, services(schedules=schedules))[
        "set_schedule_enabled"
    ]
    out = await tool.ainvoke({"schedule": "Dormir", "enabled": True})
    assert schedules.updates == []
    assert out == "O agendamento 'Dormir' já estava ativado."


async def test_set_schedule_enabled_not_found(fake_controller, fake_manager, schedules):
    tool = _tools(fake_controller, fake_manager, services(schedules=schedules))[
        "set_schedule_enabled"
    ]
    out = await tool.ainvoke({"schedule": "Almoço", "enabled": False})
    assert "não encontrado" in out and "Dormir" in out


async def test_set_schedule_enabled_ambiguous(fake_controller, fake_manager):
    schedules = FakeSchedules([_schedule("s-1", "Noite"), _schedule("s-2", "noite")])
    tool = _tools(fake_controller, fake_manager, services(schedules=schedules))[
        "set_schedule_enabled"
    ]
    out = await tool.ainvoke({"schedule": "NOITE", "enabled": False})
    assert "ambíguo" in out and "s-1" in out and "s-2" in out
    assert schedules.updates == []


async def test_schedules_unavailable(fake_controller, fake_manager):
    tools = _tools(fake_controller, fake_manager, services())
    for name, args in [
        ("list_schedules", {}),
        ("create_schedule", {"name": "X", "time_hhmm": "21:00", "action": "power_on"}),
        ("set_schedule_enabled", {"schedule": "X", "enabled": True}),
    ]:
        assert "indisponível" in await tools[name].ainvoke(args), name


async def test_create_schedule_unexpected_error_is_generic(fake_controller, fake_manager):
    class _Broken(FakeSchedules):
        async def create_schedule(self, **kwargs):
            raise OSError("disk full at /secret")

    tool = _tools(fake_controller, fake_manager, services(schedules=_Broken()))[
        "create_schedule"
    ]
    out = await tool.ainvoke({"name": "X", "time_hhmm": "21:00", "action": "power_on"})
    assert out.startswith("Erro inesperado ao criar agendamento")
    assert "/secret" not in out


async def test_set_schedule_enabled_update_error_is_generic(
    fake_controller, fake_manager, schedules
):
    async def boom(schedule_id, **kwargs):
        raise OSError("locked")

    schedules.update_schedule = boom
    tool = _tools(fake_controller, fake_manager, services(schedules=schedules))[
        "set_schedule_enabled"
    ]
    out = await tool.ainvoke({"schedule": "Acordar", "enabled": True})
    assert out.startswith("Erro inesperado ao alterar agendamento")


async def test_create_schedule_description_requires_explicit_enable(
    fake_controller, fake_manager, schedules
):
    tool = _tools(fake_controller, fake_manager, services(schedules=schedules))[
        "create_schedule"
    ]
    assert "desativado" in tool.description
