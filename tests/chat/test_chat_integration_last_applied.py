"""Integração chat × #14: apply→undo restaura o estado anterior (histórico REAL)."""
from __future__ import annotations

from typing import Any

import pytest

from marvin_hue.apply_result import ApplyResult
from marvin_hue.basics import LightConfig, LightSetting
from marvin_hue.colors import Color
from tests.chat.fakes import FakeLastApplied, services


class _StatefulHue:
    """Controller fake com estado: o que se escreve é o que se lê depois."""

    def __init__(self) -> None:
        self.state: dict[str, dict[str, Any]] = {
            "Lâmpada 1": {"on": True, "brightness": 120, "color": {"r": 10, "g": 20, "b": 30}},
            "Hue Iris": {"on": False, "brightness": 0, "color": {"r": 0, "g": 0, "b": 0}},
        }

    def list_lights(self) -> list[str]:
        return list(self.state)

    def get_lights_status(self) -> list[dict[str, Any]]:
        return [
            {"name": n, "reachable": True, **{k: (dict(v) if isinstance(v, dict) else v)
                                              for k, v in s.items()}}
            for n, s in self.state.items()
        ]

    def turn_on(self, name: str) -> bool:
        self.state[name]["on"] = True
        return True

    def turn_off(self, name: str) -> bool:
        self.state[name]["on"] = False
        return True

    def set_light_color(self, name: str, color: Color) -> None:
        self.state[name].update(
            on=True,
            brightness=color.brightness,
            color={"r": color.red, "g": color.green, "b": color.blue},
        )

    def apply_light_config(self, config: LightConfig, transition_time: float = 0) -> ApplyResult:
        for s in config.settings:
            self.set_light_color(s.light_name, s.color)
        return ApplyResult(applied=tuple(s.light_name for s in config.settings), failed=())


@pytest.fixture
async def history(tmp_path):
    from marvin_hue.persistence.scene_history_repository import SqliteSceneHistoryRepository
    from marvin_hue.persistence.schema import init_db
    from marvin_hue.services.scene_history import SceneHistoryService

    path = str(tmp_path / "h.sqlite")
    await init_db(path)
    svc = SceneHistoryService(await SqliteSceneHistoryRepository.open(path))
    yield svc
    await svc.aclose()


async def test_chat_apply_then_undo_restores_pre_apply_state(fake_manager, history):
    from marvin_hue.chat.tools import build_all_tools

    fake_manager.configs.append(
        LightConfig(
            "festa",
            [
                LightSetting("Lâmpada 1", Color(255, 0, 0, 254)),
                LightSetting("Hue Iris", Color(0, 0, 255, 200)),
            ],
            "Vermelho e azul",
        )
    )
    hue = _StatefulHue()
    before_l1 = dict(hue.state["Lâmpada 1"])
    last = FakeLastApplied()
    tools = {
        t.name: t
        for t in build_all_tools(
            hue, fake_manager, room_index={}, services=services(history=history, last_applied=last)
        )
    }

    applied = await tools["apply_config"].ainvoke({"config_name": "festa"})
    assert "aplicada" in applied
    assert hue.state["Hue Iris"]["on"] is True
    assert last.records == [("festa", "chat")]

    undone = await tools["undo_last_scene"].ainvoke({})
    assert undone.startswith("Cena anterior restaurada (2 lâmpada(s)). Origem do snapshot: chat")
    # Lâmpada ligada volta à cor/brilho anteriores; a que estava apagada volta a apagar.
    assert hue.state["Lâmpada 1"] == before_l1
    assert hue.state["Hue Iris"]["on"] is False
    assert last.clears == ["undo"]
