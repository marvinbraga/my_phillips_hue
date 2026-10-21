"""Tools de sistema: espelhamento, saúde, temperatura de cor; turn_off_lights('all')."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from marvin_hue.apply_result import ApplyResult
from marvin_hue.services.lights_off import LightsOffBridgeError
from marvin_hue.audio_mirror import ALL_AUDIO_PROFILES
from tests.chat.fakes import (
    HEALTH_PAYLOAD,
    FakeHistory,
    FakeLastApplied,
    FakeLightsOff,
    FakeMirror,
    services,
)


def _tools(controller, svc, rooms=None):
    from marvin_hue.chat.tools.system_tools import build_system_tools

    return {t.name: t for t in build_system_tools(controller, svc, rooms=rooms or {})}


# ----- mirror -----


def test_get_mirror_status_inactive(fake_controller):
    out = _tools(fake_controller, services(mirror=FakeMirror()))["get_mirror_status"].invoke({})
    assert "inativo" in out


def test_get_mirror_status_active_summary(fake_controller):
    out = _tools(fake_controller, services(mirror=FakeMirror(mode="screen")))[
        "get_mirror_status"
    ].invoke({})
    assert out == (
        "Espelhamento ativo: modo tela, 25 FPS, perfil cinema, transporte rest."
    )


def test_get_mirror_status_unavailable(fake_controller):
    out = _tools(fake_controller, services())["get_mirror_status"].invoke({})
    assert "indisponível" in out


async def test_start_mirror_screen_with_profile(fake_controller):
    mirror = FakeMirror()
    out = await _tools(fake_controller, services(mirror=mirror))["start_mirror"].ainvoke(
        {"mode": "screen", "profile": "cinema"}
    )
    assert mirror.start_calls == [("screen", {"profile": "cinema"})]
    assert "iniciado" in out


async def test_start_mirror_unknown_screen_profile_uses_service_message(fake_controller):
    mirror = FakeMirror()
    out = await _tools(fake_controller, services(mirror=mirror))["start_mirror"].ainvoke(
        {"mode": "screen", "profile": "disco"}
    )
    assert mirror.mode is None
    assert out.startswith("Não foi possível iniciar o espelhamento: Perfil 'disco'")
    assert "ambient, cinema, fps" in out


async def test_start_mirror_audio_profile_from_module(fake_controller):
    mirror = FakeMirror()
    profile = sorted(ALL_AUDIO_PROFILES)[0]
    out = await _tools(fake_controller, services(mirror=mirror))["start_mirror"].ainvoke(
        {"mode": "audio", "profile": profile}
    )
    assert mirror.mode == "audio" and "iniciado" in out


async def test_start_mirror_service_validation_error(fake_controller):
    mirror = FakeMirror()
    out = await _tools(fake_controller, services(mirror=mirror))["start_mirror"].ainvoke(
        {"mode": "audio", "profile": "cinema"}
    )
    assert "Perfil 'cinema' inválido para modo audio" in out


async def test_start_mirror_unexpected_error_is_generic(fake_controller):
    class _Broken(FakeMirror):
        async def start(self, mode="screen", **kwargs):
            raise KeyError("internal state /secret")

    out = await _tools(fake_controller, services(mirror=_Broken()))["start_mirror"].ainvoke(
        {"mode": "screen"}
    )
    assert out.startswith("Erro inesperado ao iniciar o espelhamento")
    assert "/secret" not in out


async def test_start_mirror_already_active(fake_controller):
    mirror = FakeMirror(mode="screen")
    out = await _tools(fake_controller, services(mirror=mirror))["start_mirror"].ainvoke(
        {"mode": "screen"}
    )
    assert "já está ativo" in out


async def test_stop_mirror(fake_controller):
    mirror = FakeMirror(mode="audio")
    out = await _tools(fake_controller, services(mirror=mirror))["stop_mirror"].ainvoke({})
    assert mirror.mode is None and "parado" in out


async def test_stop_mirror_idempotent(fake_controller):
    out = await _tools(fake_controller, services(mirror=FakeMirror()))["stop_mirror"].ainvoke({})
    assert "Nenhum espelhamento ativo" in out


async def test_mirror_unavailable(fake_controller):
    tools = _tools(fake_controller, services())
    assert "indisponível" in await tools["start_mirror"].ainvoke({"mode": "screen"})
    assert "indisponível" in await tools["stop_mirror"].ainvoke({})


def test_start_mirror_sync_path_app_only(fake_controller):
    mirror = FakeMirror()
    out = _tools(fake_controller, services(mirror=mirror))["start_mirror"].invoke(
        {"mode": "screen"}
    )
    assert mirror.start_calls == [] and "apenas no app" in out


# ----- health -----


async def test_get_system_health_summary(fake_controller):
    async def collect():
        return HEALTH_PAYLOAD

    out = await _tools(fake_controller, services(health=collect))[
        "get_system_health"
    ].ainvoke({})
    assert out == (
        "Saúde do sistema:\n"
        "- Bridge: conectada (10.0.0.2, 9 lâmpadas)\n"
        "- Lâmpadas: 9 no total, 1 inacessível(eis), 2 desabilitada(s) no app\n"
        "- Espelhamento: parado\n"
        "- Chat: disponível\n"
        "- Agendamentos: 3 ativo(s), runner rodando"
    )


async def test_get_system_health_audio_mirror_running(fake_controller):
    payload = {
        **HEALTH_PAYLOAD,
        "mirror": {"running": True, "mode": "audio", "fps": 30, "profile": None},
    }

    async def collect():
        return payload

    out = await _tools(fake_controller, services(health=collect))[
        "get_system_health"
    ].ainvoke({})
    assert "- Espelhamento: ativo (música, 30 FPS)" in out


async def test_get_system_health_error(fake_controller):
    async def collect():
        raise RuntimeError("boom")

    out = await _tools(fake_controller, services(health=collect))[
        "get_system_health"
    ].ainvoke({})
    assert out.startswith("Erro inesperado ao consultar a saúde do sistema")


async def test_get_system_health_unavailable(fake_controller):
    out = await _tools(fake_controller, services())["get_system_health"].ainvoke({})
    assert "indisponível" in out


# ----- set_color_temperature -----


def test_set_color_temperature_single_light(fake_controller):
    from marvin_hue.chat.tools.color_temperature import kelvin_to_rgb

    out = _tools(fake_controller, services())["set_color_temperature"].invoke(
        {"target": "lâmpada 1", "kelvin": 2700, "brightness_pct": 50}
    )
    fake_controller.set_light_color.assert_called_once()
    name, color = fake_controller.set_light_color.call_args.args
    assert name == "Lâmpada 1"
    assert (color.red, color.green, color.blue) == kelvin_to_rgb(2700)
    assert color.brightness == 127
    assert "2700K" in out


def test_set_color_temperature_all_default_brightness(fake_controller):
    _tools(fake_controller, services())["set_color_temperature"].invoke(
        {"target": "all", "kelvin": 4000}
    )
    calls = fake_controller.set_light_color.call_args_list
    assert [c.args[0] for c in calls] == ["Lâmpada 1", "Fita Led", "Led cima"]
    # Padrão 80% → 203/254 (o controller aplica o teto ocular depois).
    assert {c.args[1].brightness for c in calls} == {203}


def test_set_color_temperature_room(fake_controller):
    rooms = {"quarto": ["Lâmpada 1", "Led cima"]}
    out = _tools(fake_controller, services(), rooms=rooms)["set_color_temperature"].invoke(
        {"target": "Quarto", "kelvin": 3000}
    )
    names = [c.args[0] for c in fake_controller.set_light_color.call_args_list]
    assert names == ["Lâmpada 1", "Led cima"]
    assert "sala 'quarto'" in out


def test_set_color_temperature_teto_hits_both_ceiling_rooms(fake_controller):
    fake_controller.list_lights.return_value = [
        "Lâmpada 1", "Lâmpada 2", "Lâmpada 3", "Lâmpada 4", "Fita Led",
    ]
    rooms = {
        "Teto, à direita": ["Lâmpada 1", "Lâmpada 2"],
        "Teto, à esquerda": ["Lâmpada 3", "Lâmpada 4"],
        "Frente, parte de baixo do monitor": ["Fita Led"],
    }
    out = _tools(fake_controller, services(), rooms=rooms)["set_color_temperature"].invoke(
        {"target": "teto", "kelvin": 2700}
    )
    names = [c.args[0] for c in fake_controller.set_light_color.call_args_list]
    assert names == ["Lâmpada 1", "Lâmpada 2", "Lâmpada 3", "Lâmpada 4"]
    assert "Teto, à direita" in out and "Teto, à esquerda" in out


@pytest.mark.parametrize("kelvin", [1999, 6501, 9000])
def test_set_color_temperature_kelvin_out_of_schema(fake_controller, kelvin):
    with pytest.raises(ValidationError):
        _tools(fake_controller, services())["set_color_temperature"].invoke(
            {"target": "Lâmpada 1", "kelvin": kelvin}
        )


def test_set_color_temperature_unknown_target(fake_controller):
    out = _tools(fake_controller, services())["set_color_temperature"].invoke(
        {"target": "Abajur", "kelvin": 3000}
    )
    assert "não encontrad" in out
    fake_controller.set_light_color.assert_not_called()


def test_set_color_temperature_controller_error(fake_controller):
    fake_controller.set_light_color.side_effect = ValueError("desabilitada")
    out = _tools(fake_controller, services())["set_color_temperature"].invoke(
        {"target": "Lâmpada 1", "kelvin": 3000}
    )
    assert out.endswith("0 lâmpada(s). Falha/skip: Lâmpada 1 (desabilitada).")


def test_set_color_temperature_unexpected_controller_error_is_generic(fake_controller):
    fake_controller.set_light_color.side_effect = OSError("socket /secret")
    out = _tools(fake_controller, services())["set_color_temperature"].invoke(
        {"target": "Lâmpada 1", "kelvin": 3000}
    )
    assert out.endswith("Falha/skip: Lâmpada 1 (erro inesperado).")


# ----- turn_off_lights('all') via LightsOffService (P10) -----


def _light_tools(controller, svc):
    from marvin_hue.chat.tools.light_tools import build_light_tools

    return {t.name: t for t in build_light_tools(controller, None, services=svc)}


async def test_turn_off_all_uses_lights_off_service(fake_controller):
    lights_off = FakeLightsOff()
    tool = _light_tools(fake_controller, services(lights_off=lights_off))["turn_off_lights"]
    out = await tool.ainvoke({"light_name": "all"})
    assert lights_off.calls == 1
    fake_controller.set_all.assert_not_called()
    assert out == "Todas as lâmpadas foram desligadas (2)."


async def test_turn_off_all_partial_failure(fake_controller):
    result = ApplyResult(applied=("Lâmpada 1",), failed=(("Fita Led", "timeout"),))
    tool = _light_tools(fake_controller, services(lights_off=FakeLightsOff(result)))[
        "turn_off_lights"
    ]
    out = await tool.ainvoke({"light_name": "all"})
    assert "Fita Led" in out and "timeout" in out


async def test_turn_off_all_bridge_error(fake_controller):
    lights_off = FakeLightsOff(exc=LightsOffBridgeError("unreachable"))
    tool = _light_tools(fake_controller, services(lights_off=lights_off))["turn_off_lights"]
    out = await tool.ainvoke({"light_name": "all"})
    assert "bridge" in out.lower()


async def test_turn_off_single_light_unchanged(fake_controller):
    lights_off = FakeLightsOff()
    tool = _light_tools(fake_controller, services(lights_off=lights_off))["turn_off_lights"]
    out = await tool.ainvoke({"light_name": "Lâmpada 1"})
    fake_controller.turn_off.assert_called_once_with("Lâmpada 1")
    assert lights_off.calls == 0 and "desligada" in out


def test_turn_off_all_sync_path_keeps_controller(fake_controller):
    lights_off = FakeLightsOff()
    tool = _light_tools(fake_controller, services(lights_off=lights_off))["turn_off_lights"]
    tool.invoke({"light_name": "all"})
    fake_controller.set_all.assert_called_once_with(False)
    assert lights_off.calls == 0


async def test_default_lights_off_snapshots_and_clears_last_applied(fake_controller):
    """Sem provider explícito, ChatServices compõe LightsOffService com
    histórico, espelhamento e última cena — como POST /lights/off."""
    from marvin_hue.chat.services import ChatServices
    from marvin_hue.services.lights_off import LightsOffService

    history, last, mirror = FakeHistory(), FakeLastApplied(), FakeMirror(mode="screen")
    svc = ChatServices(
        history_provider=lambda: history,
        mirror_provider=lambda: mirror,
        last_applied_provider=lambda: last,
    )
    assert isinstance(svc.lights_off(fake_controller), LightsOffService)
    tool = _light_tools(fake_controller, svc)["turn_off_lights"]
    out = await tool.ainvoke({"light_name": "all"})
    assert mirror.mode is None  # espelhamento parado antes
    assert history.snapshots == [
        {"source": "lights_off", "label": "before lights off"}
    ]
    assert last.clears == ["lights_off"]
    assert out == "Todas as lâmpadas foram desligadas (3)."


@pytest.mark.parametrize(
    ("getter", "attr"),
    [
        ("favorites", "_scene_favorites_service"),
        ("history", "_scene_history_service"),
        ("groups", "_group_service"),
        ("schedules", "_schedule_service"),
        ("last_applied", "_last_applied_scene_service"),
    ],
)
def test_default_providers_return_registered_service(getter, attr, monkeypatch):
    from marvin_hue.api import dependencies
    from marvin_hue.chat.services import ChatServices

    sentinel = object()
    monkeypatch.setattr(dependencies, attr, sentinel)
    assert getattr(ChatServices(), getter)() is sentinel


def test_default_mirror_provider_returns_registered_service(monkeypatch):
    from marvin_hue.api import dependencies
    from marvin_hue.chat.services import ChatServices

    sentinel = object()
    monkeypatch.setattr(dependencies, "_screen_mirror", object())
    monkeypatch.setattr(dependencies, "_mirror_control_service", sentinel)
    assert ChatServices().mirror() is sentinel


async def test_default_health_collects_with_route_arguments(monkeypatch):
    from marvin_hue.api import dependencies
    from marvin_hue.chat.services import ChatServices
    from marvin_hue.services import health

    hue, screen, audio, agent, runner, registry, sched = (object() for _ in range(7))
    monkeypatch.setattr(dependencies, "_hue_controller", hue)
    monkeypatch.setattr(dependencies, "_screen_mirror", screen)
    monkeypatch.setattr(dependencies, "_audio_mirror", audio)
    monkeypatch.setattr(dependencies, "_chat_agent", agent)
    monkeypatch.setattr(dependencies, "_chat_unavailable_reason", None)
    monkeypatch.setattr(dependencies, "_schedule_runner", runner)
    monkeypatch.setattr(dependencies, "_light_registry_service", registry)
    monkeypatch.setattr(dependencies, "_schedule_service", sched)
    seen: dict = {}

    async def spy(**kwargs):
        seen.update(kwargs)
        return HEALTH_PAYLOAD

    monkeypatch.setattr(health, "collect_health", spy)
    collect = ChatServices().health()
    assert await collect() is HEALTH_PAYLOAD
    assert seen == {
        "hue": hue,
        "screen_mirror": screen,
        "audio_mirror": audio,
        "chat_agent": agent,
        "chat_reason": None,
        "registry": registry,
        "schedule_runner": runner,
        "schedule_service": sched,
    }


@pytest.mark.parametrize(
    "getter", ["favorites", "history", "groups", "schedules", "mirror", "last_applied"]
)
def test_default_providers_fail_open_without_app(getter, monkeypatch):
    from marvin_hue.api import dependencies
    from marvin_hue.chat.services import ChatServices

    for attr in (
        "_scene_favorites_service",
        "_scene_history_service",
        "_group_service",
        "_schedule_service",
        "_mirror_control_service",
        "_screen_mirror",
        "_last_applied_scene_service",
    ):
        monkeypatch.setattr(dependencies, attr, None)
    assert getattr(ChatServices(), getter)() is None


def test_default_health_fails_open_without_app(monkeypatch):
    from marvin_hue.api import dependencies
    from marvin_hue.chat.services import ChatServices

    monkeypatch.setattr(dependencies, "_hue_controller", None)
    assert ChatServices().health() is None
