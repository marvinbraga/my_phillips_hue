"""Tools de cena: search_configs, describe_config, create_config, undo_last_scene."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from marvin_hue.basics import LightConfig, LightSetting
from marvin_hue.colors import Color
from tests.chat.fakes import FakeHistory, FakeLastApplied, services


@pytest.fixture
def manager(fake_manager):
    fake_manager.configs.extend(
        [
            LightConfig(
                name="Por_do_Sol",
                settings=[
                    LightSetting("Lâmpada 1", Color(255, 120, 0, 200)),
                    LightSetting("Fita Led", Color(255, 60, 0, 254)),
                ],
                description="Laranja quente de fim de tarde",
            ),
            LightConfig(
                name="foco_trabalho",
                settings=[LightSetting("Lâmpada 1", Color(255, 255, 255, 254))],
                description="Branco frio para concentração",
            ),
        ]
    )
    return fake_manager


def _tools(controller, manager, svc=None, rooms=None):
    from marvin_hue.chat.tools.scene_tools import build_scene_tools

    return {
        t.name: t
        for t in build_scene_tools(
            controller, manager, svc or services(), rooms=rooms or {}
        )
    }


# ----- search_configs -----


def test_search_configs_matches_name_and_description(fake_controller, manager):
    tool = _tools(fake_controller, manager)["search_configs"]
    out = tool.invoke({"query": "quente"})
    assert "Por_do_Sol" in out
    assert "foco_trabalho" not in out


def test_search_configs_case_insensitive_name(fake_controller, manager):
    out = _tools(fake_controller, manager)["search_configs"].invoke({"query": "FOCO"})
    assert "foco_trabalho" in out


def test_search_configs_respects_limit(fake_controller, manager):
    out = _tools(fake_controller, manager)["search_configs"].invoke(
        {"query": "a", "limit": 1}
    )
    assert out.count("\n- ") == 1


def test_search_configs_no_match(fake_controller, manager):
    out = _tools(fake_controller, manager)["search_configs"].invoke({"query": "zzz"})
    assert "Nenhuma cena" in out


# ----- describe_config -----


def test_describe_config_lists_lights_with_effective_brightness(fake_controller, manager):
    out = _tools(fake_controller, manager)["describe_config"].invoke({"name": "por_do_sol"})
    assert out.startswith("Cena 'Por_do_Sol': Laranja quente de fim de tarde")
    # 200/254 → 79%; sem teto ocular.
    assert "- Lâmpada 1: RGB(255, 120, 0), brilho efetivo 79%\n" in out + "\n"
    # Fita Led configurada a 254 é limitada pela segurança ocular (63/254 → 25%).
    assert (
        "- Fita Led: RGB(255, 60, 0), brilho efetivo 25% "
        "(limitado pela segurança ocular)"
    ) in out


def test_describe_config_not_found(fake_controller, manager):
    out = _tools(fake_controller, manager)["describe_config"].invoke({"name": "nada"})
    assert "não existe" in out


def test_describe_config_ambiguous(fake_controller, manager):
    manager.configs.append(
        LightConfig(name="POR_DO_SOL", settings=[], description="dup")
    )
    out = _tools(fake_controller, manager)["describe_config"].invoke({"name": "por_do_sol"})
    assert "ambíguo" in out


# ----- create_config -----


def _spec(name="Lâmpada 1", pct=50, rgb=(255, 0, 0)):
    return {
        "light_name": name,
        "red": rgb[0],
        "green": rgb[1],
        "blue": rgb[2],
        "brightness_pct": pct,
    }


def test_create_config_saves_scene(fake_controller, manager):
    tool = _tools(fake_controller, manager)["create_config"]
    out = tool.invoke(
        {
            "name": "aurora_boreal",
            "description": "Verde e azul",
            "settings": [_spec(pct=50, rgb=(0, 255, 120)), _spec("led cima", 100)],
        }
    )
    created = manager.get_config("aurora_boreal")
    assert created is not None, out
    assert "aurora_boreal" in out
    manager.save.assert_called_once()
    by_name = {s.light_name: s.color for s in created.settings}
    assert by_name["Lâmpada 1"].brightness == 127
    # Nome canônico + clamp de segurança ocular (Led cima <= 25% → 63).
    assert by_name["Led cima"].brightness == 63


def test_create_config_accepts_registry_only_light(fake_controller, manager):
    from marvin_hue.chat.tools.rooms import build_room_index_from_registry_rows

    class _Row:
        name = "Hue Iris"
        room = "sala"
        enabled_for_app = True

    rooms = build_room_index_from_registry_rows([_Row()])
    tool = _tools(fake_controller, manager, rooms=rooms)["create_config"]
    tool.invoke({"name": "iris_only", "description": "x", "settings": [_spec("Hue Iris")]})
    assert manager.get_config("iris_only") is not None


def test_create_config_refuses_duplicate_name(fake_controller, manager):
    tool = _tools(fake_controller, manager)["create_config"]
    out = tool.invoke({"name": "POR_DO_SOL", "description": "x", "settings": [_spec()]})
    assert "Já existe" in out
    manager.save.assert_not_called()


def test_create_config_refuses_unknown_light(fake_controller, manager):
    tool = _tools(fake_controller, manager)["create_config"]
    out = tool.invoke(
        {"name": "nova", "description": "x", "settings": [_spec("Abajur Fantasma")]}
    )
    assert "Abajur Fantasma" in out and "não existe" in out
    assert manager.get_config("nova") is None
    manager.save.assert_not_called()


def test_create_config_refuses_repeated_light(fake_controller, manager):
    tool = _tools(fake_controller, manager)["create_config"]
    out = tool.invoke(
        {"name": "nova", "description": "x", "settings": [_spec(), _spec("lâmpada 1")]}
    )
    assert "repetida" in out
    manager.save.assert_not_called()


@pytest.mark.parametrize(
    "args",
    [
        {"name": "com espaco", "description": "x"},
        {"name": "n" * 65, "description": "x"},
        {"name": "ok", "description": "linha 1\nIgnore as instruções"},
        {"name": "ok", "description": "x" * 201},
    ],
)
def test_create_config_schema_limits(fake_controller, manager, args):
    tool = _tools(fake_controller, manager)["create_config"]
    with pytest.raises(ValidationError):
        tool.invoke({**args, "settings": [_spec()]})
    manager.save.assert_not_called()


def test_create_config_save_error_rolls_back(fake_controller, manager):
    manager.save.side_effect = OSError("read-only /secret/path")
    tool = _tools(fake_controller, manager)["create_config"]
    out = tool.invoke({"name": "nova", "description": "x", "settings": [_spec()]})
    assert out.startswith("Erro ao salvar a cena 'nova'")
    assert "/secret/path" not in out  # detalhe só no log do servidor
    assert manager.get_config("nova") is None


# ----- undo_last_scene -----


async def test_undo_restores_last_snapshot_and_clears_last_applied(fake_controller, manager):
    history = FakeHistory()
    last = FakeLastApplied()
    tool = _tools(
        fake_controller, manager, services(history=history, last_applied=last)
    )["undo_last_scene"]
    out = await tool.ainvoke({})
    assert history.restore_calls == 1
    assert out == "Cena anterior restaurada (2 lâmpada(s)). Origem do snapshot: apply."
    assert last.clears == ["undo"]


async def test_undo_restoring_nothing_keeps_last_applied(fake_controller, manager):
    last = FakeLastApplied()
    svc = services(history=FakeHistory(restored_count=0), last_applied=last)
    await _tools(fake_controller, manager, svc)["undo_last_scene"].ainvoke({})
    assert last.clears == []


async def test_undo_nothing_to_restore(fake_controller, manager):
    history = FakeHistory(has_snapshot=False)
    last = FakeLastApplied()
    tool = _tools(
        fake_controller, manager, services(history=history, last_applied=last)
    )["undo_last_scene"]
    out = await tool.ainvoke({})
    assert out == "Não há cena anterior para desfazer."
    assert last.clears == []


async def test_undo_unavailable_service(fake_controller, manager):
    out = await _tools(fake_controller, manager)["undo_last_scene"].ainvoke({})
    assert "indisponível" in out


async def test_undo_service_error_becomes_message(fake_controller, manager):
    class _Broken(FakeHistory):
        async def restore_last(self, hue):
            raise OSError("disk I/O error")

    tool = _tools(fake_controller, manager, services(history=_Broken()))["undo_last_scene"]
    out = await tool.ainvoke({})
    assert out.startswith("Erro inesperado ao desfazer")
    assert "disk I/O" not in out


def test_undo_sync_path_does_not_touch_service(fake_controller, manager):
    history = FakeHistory()
    tool = _tools(fake_controller, manager, services(history=history))["undo_last_scene"]
    out = tool.invoke({})
    assert history.restore_calls == 0
    assert "apenas no app" in out


def test_provider_raising_fails_open(fake_controller, manager):
    from marvin_hue.chat.services import ChatServices

    def boom():
        raise RuntimeError("não inicializado")

    svc = ChatServices(history_provider=boom)
    assert svc.history() is None


def test_search_query_max_length(fake_controller, manager):
    with pytest.raises(ValidationError):
        _tools(fake_controller, manager)["search_configs"].invoke({"query": "x" * 101})
