"""Eval-set de invariantes do harness Hue (golden-set versionado, hue.chat@2).

Determinístico, sem LLM. Os casos vivem em invariants.json e NÃO entram em
nenhum prompt/contexto do agente (anti-leakage, checado abaixo). Casos
level=="code" são executados aqui; level=="prompt" (seleção de tool) rodam ao
vivo em ``tests/eval/run_tool_selection.py`` e aqui só têm a estrutura
validada; level=="prompt-manual" é smoke manual (SKIP explícito).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from marvin_hue.eye_safety import EYE_SAFETY_LIMITS, clamp_eye_safety  # FONTE ÚNICA

GOLDEN = Path(__file__).parent / "invariants.json"
# Ancorado em __file__ (não no cwd) para rodar de qualquer diretório.
LOCATIONS = Path(__file__).parents[2] / ".res" / "light_physical_locations.json"


def load_cases():
    data = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert data["version"] == 2
    return data["cases"]


def _case(case_id):
    return next(c for c in load_cases() if c["id"] == case_id)


def _all_tools():
    from unittest.mock import MagicMock

    from marvin_hue.chat.tools import build_all_tools
    from tests.chat.fakes import services

    controller, manager = MagicMock(), MagicMock()
    controller.list_lights.return_value = [
        "Lâmpada 1", "Lâmpada 2", "Lâmpada 3", "Lâmpada 4", "Fita Led",
    ]
    manager.configs = []
    rooms = {
        "Teto, à direita": ["Lâmpada 1", "Lâmpada 2"],
        "Teto, à esquerda": ["Lâmpada 3", "Lâmpada 4"],
        "Frente, parte de baixo do monitor": ["Fita Led"],
    }
    tools = build_all_tools(controller, manager, room_index=rooms, services=services())
    return controller, {t.name: t for t in tools}


@pytest.mark.parametrize("case", [c for c in load_cases() if c["invariant"] in ("eye_safety_clamp", "no_clamp")])
def test_eye_safety_clamp_contract(case):
    # invariants.json expressa o brilho em percentual -> escala "pct".
    out = clamp_eye_safety(case["target_light"], case["requested_brightness_pct"], scale="pct")
    # Asserção EXATA (não apenas <=): pega tanto over-clamp (esmagar abaixo do
    # limite) quanto clamp indevido de uma lâmpada sem restrição.
    if case["invariant"] == "eye_safety_clamp":
        expected = min(case["requested_brightness_pct"], case["max_brightness_pct"])
    else:  # no_clamp -> passa inalterado
        expected = case["requested_brightness_pct"]
    assert out == expected, (
        f"{case['id']}: {case['target_light']} esperado {expected}%, obteve {out}%"
    )


@pytest.mark.parametrize(
    "value,expected",
    [(254, 63), (63, 63), (64, 63), (30, 30), (0, 0)],
)
def test_eye_safety_clamp_hue_scale_floors_below_ceiling(value, expected):
    """A escala "hue" (0-254) é a usada pelo chokepoint do controller. O teto de
    25% deve arredondar PARA BAIXO: 25% de 254 = 63.5 -> 63 (24.8%), nunca 64."""
    assert clamp_eye_safety("Fita Led", value, scale="hue") == expected
    # Lâmpada sem restrição passa inalterada na escala hue.
    assert clamp_eye_safety("Lâmpada 1", value, scale="hue") == value


@pytest.mark.parametrize("case", [c for c in load_cases() if c["invariant"] == "eye_safety_clamp_all"])
def test_eye_safety_clamp_all_contract(case):
    """Caminho "all": o clamp é POR LÂMPADA.

    Fase 0: valida a função pura, lâmpada a lâmpada. A Tarefa 5.1 religa este
    caso ao chokepoint HueController.set_all_brightness (Tarefa 2.3), que
    itera as lâmpadas clampando cada uma individualmente.
    """
    out_fita = clamp_eye_safety("Fita Led", case["requested_brightness_pct"], scale="pct")
    out_teto = clamp_eye_safety("Lâmpada 1", case["requested_brightness_pct"], scale="pct")
    assert out_fita <= case["max_brightness_pct_fita"], case["id"]
    assert out_teto == case["requested_brightness_pct"], case["id"]


@pytest.mark.parametrize("case", [c for c in load_cases() if c.get("level") == "prompt-manual"])
def test_manual_prompt_invariants_skipped(case):
    pytest.skip(
        f"{case['id']}: invariante de prompt sem métrica determinística; "
        "smoke manual a cada mudança de prompt/modelo"
    )


@pytest.mark.parametrize("case", [c for c in load_cases() if c.get("level") == "prompt"])
def test_prompt_cases_reference_real_tools(case):
    """Estrutura dos casos ao vivo: tools esperadas/proibidas existem."""
    _, tools = _all_tools()
    assert case["invariant"] == "tool_selection"
    assert isinstance(case["pre_existing"], bool)
    assert case["expected_tools"] and set(case["expected_tools"]) <= set(tools)
    assert set(case.get("forbidden_tools", [])) <= set(tools)


def test_prompt_case_counts():
    prompt = [c for c in load_cases() if c.get("level") == "prompt"]
    assert len(prompt) == 17
    assert sum(c["pre_existing"] for c in prompt) == 7


def test_no_golden_leakage_into_prompts_or_tool_descriptions():
    """Nenhuma frase do golden set aparece em prompt, subagent ou descrição de tool."""
    from marvin_hue.chat.agents.react_agent import SYSTEM_PROMPT
    from marvin_hue.chat.subagents import definitions as d

    _, tools = _all_tools()
    surface = "\n".join(
        [SYSTEM_PROMPT, d.SCENE_DESIGNER_PROMPT, d.CONFIG_LIBRARIAN_PROMPT, d.GENERAL_PROMPT]
        + [t.description for t in tools.values()]
        + [json.dumps(t.args, ensure_ascii=False) for t in tools.values()]
    ).casefold()
    for case in load_cases():
        intent = case.get("intent")
        if intent:
            assert intent.casefold() not in surface, f"leakage: {case['id']}"


def test_prompt_surface_fingerprint_pinned():
    """Mudou prompt/descrição/schema → mude PROMPT_VERSION e rode o eval ao vivo."""
    from marvin_hue.chat.agents.react_agent import PROMPT_VERSION
    from tests.eval.run_tool_selection import prompt_surface_sha256

    pinned = json.loads((GOLDEN.parent / "prompt_version.json").read_text("utf-8"))
    assert pinned["prompt_version"] == PROMPT_VERSION
    assert prompt_surface_sha256() == pinned["sha256"], (
        "superfície de prompt mudou: bump PROMPT_VERSION, rode "
        "tests/eval/run_tool_selection.py e atualize prompt_version.json"
    )


def test_eval_tool_surface_complete():
    case = _case("tool-surface-complete")
    _, tools = _all_tools()
    assert sorted(tools) == sorted(case["expected_tools"])


def test_eval_subagent_least_privilege():
    from marvin_hue.chat.subagents import definitions as d

    case = _case("subagent-least-privilege")
    assert not set(case["forbidden_tools"]) & set(d.GENERAL_TOOLS)


def test_eval_kelvin_target_teto():
    case = _case("kelvin-target-teto")
    controller, tools = _all_tools()
    tools["set_color_temperature"].invoke({"target": case["target"], "kelvin": case["kelvin"]})
    hit = [c.args[0] for c in controller.set_light_color.call_args_list]
    assert hit == case["expected_lights"]


def test_eval_kelvin_schema_bounds():
    from pydantic import ValidationError

    case = _case("kelvin-clamp")
    _, tools = _all_tools()
    for k in case["rejected_kelvin"]:
        with pytest.raises(ValidationError):
            tools["set_color_temperature"].invoke({"target": "Lâmpada 1", "kelvin": k})
    for k in case["accepted_kelvin"]:
        assert "K" in tools["set_color_temperature"].invoke({"target": "Lâmpada 1", "kelvin": k})


async def test_eval_undo_without_history():
    case = _case("undo-no-history")
    _, tools = _all_tools()
    assert await tools["undo_last_scene"].ainvoke({}) == case["expected_message"]


async def test_eval_schedule_payload():
    from unittest.mock import MagicMock

    from marvin_hue.chat.tools import build_all_tools
    from tests.chat.fakes import FakeSchedules, services

    case = _case("schedule-22h-schema")
    schedules = FakeSchedules()
    manager = MagicMock()
    manager.configs = []
    tools = {
        t.name: t
        for t in build_all_tools(
            MagicMock(), manager, room_index={}, services=services(schedules=schedules)
        )
    }
    await tools["create_schedule"].ainvoke(case["args"])
    created = schedules.created[-1]
    for key, value in case["expected"].items():
        assert created[key] == value, key


# Invariantes level=="code" exercitados E2E contra o código real (Tarefa 5.1).
_CODE_INVARIANTS_COVERED = {
    "eye_safety_clamp", "no_clamp", "eye_safety_clamp_all", "all_off_called",
    "tool_surface", "subagent_read_only", "kelvin_room_prefix",
    "kelvin_schema_bounds", "undo_without_history", "schedule_payload",
}


def _fwd_request(tool_name, args):
    """Fake de ToolCallRequest cujo override(tool_call=...) encaminha o tool_call."""
    from unittest.mock import MagicMock
    req = MagicMock()
    req.tool_call = {"name": tool_name, "args": dict(args), "id": "x"}

    def _override(**kw):
        new = MagicMock()
        new.tool_call = kw.get("tool_call", req.tool_call)
        new.override.side_effect = _override
        return new

    req.override.side_effect = _override
    return req


def test_eval_eye_safety_via_middleware():
    """Cada caso clamp/no_clamp exercitado ponta-a-ponta no EyeSafetyMiddleware real."""
    from marvin_hue.chat.middleware.eye_safety import EyeSafetyMiddleware
    mw = EyeSafetyMiddleware()
    for case in load_cases():
        if case["invariant"] not in ("eye_safety_clamp", "no_clamp"):
            continue
        captured = {}

        def handler(req):
            captured.update(req.tool_call["args"])
            return "ok"

        req = _fwd_request(
            "set_brightness",
            {"light_name": case["target_light"], "brightness": case["requested_brightness_pct"]},
        )
        mw.wrap_tool_call(req, handler)
        assert captured["brightness"] <= case["max_brightness_pct"], case["id"]


def test_eval_turn_off_all_calls_set_all_false():
    """Caso `turn-off-all` (level=code), caminho síncrono (CLI) via
    build_all_tools: delega a set_all(False)."""
    controller, tools = _all_tools()
    tools["turn_off_lights"].invoke({"light_name": "all"})
    controller.set_all.assert_called_once_with(False)


async def test_eval_turn_off_all_async_uses_lights_off_service():
    """Caso `turn-off-all`, caminho async (chat do app) via build_all_tools:
    LightsOffService desliga cada lâmpada habilitada, sem set_all."""
    controller, tools = _all_tools()
    controller.get_lights_status.return_value = [
        {"name": "Lâmpada 1", "on": True, "brightness": 100, "reachable": True,
         "color": {"r": 1, "g": 1, "b": 1}},
    ]
    out = await tools["turn_off_lights"].ainvoke({"light_name": "all"})
    controller.set_all.assert_not_called()
    assert controller.turn_off_with_transition.call_count == 5
    assert out == "Todas as lâmpadas foram desligadas (5)."


def test_eval_eye_safety_all_max_via_chokepoint():
    """Caso `eye-safety-all-max` (level=code), contra o chokepoint REAL:
    set_all_brightness clampa POR LÂMPADA (Tarefa 2.3)."""
    from unittest.mock import MagicMock
    from marvin_hue.controllers import HueController
    c = HueController.__new__(HueController)  # sem conectar à bridge
    fita = MagicMock()
    fita.name = "Fita Led"
    teto = MagicMock()
    teto.name = "Lâmpada 1"
    c.lights = [fita, teto]
    c._light_cache = {fita.name: fita, teto.name: teto}
    c.set_all_brightness(254)
    assert fita.brightness == 63   # 25% de 254 floored (nunca 64)
    assert teto.brightness == 254  # sem restrição


def test_no_silently_uncollected_cases():
    """Rede de detecção: todo caso do golden-set deve ser consumido por ALGUM
    teste (executado OU skipado explicitamente). Falha se um caso novo cair fora
    de todos os filtros — evita falsa cobertura silenciosa."""
    consumed = set()
    for c in load_cases():
        if c.get("level") == "code" and c["invariant"] in _CODE_INVARIANTS_COVERED:
            consumed.add(c["id"])
        elif c.get("level") in ("prompt", "prompt-manual"):
            consumed.add(c["id"])
    all_ids = {c["id"] for c in load_cases()}
    assert consumed == all_ids, f"casos não consumidos por nenhum teste: {all_ids - consumed}"


def test_eye_safety_limits_reconcile_with_locations_json():
    """O código (EYE_SAFETY_LIMITS) é a fonte CANÔNICA (fail-safe: arquivo
    editável/ausente não pode desarmar segurança física); o JSON
    .res/light_physical_locations.json (max_brightness_percent) é informativo
    para o modelo. Se as duas fontes divergirem, este teste FALHA.
    """
    data = json.loads(LOCATIONS.read_text(encoding="utf-8"))
    json_limits = {
        light["name"]: light["max_brightness_percent"]
        for light in data.get("lights", [])
        if "max_brightness_percent" in light
    }
    assert json_limits == EYE_SAFETY_LIMITS
