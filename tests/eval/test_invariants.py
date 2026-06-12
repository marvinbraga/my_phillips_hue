"""Eval-set de invariantes do harness Hue (golden-set versionado).

Determinístico, sem LLM. Os casos vivem em invariants.json e NÃO entram em
nenhum prompt/contexto do agente (anti-leakage). Casos level=="code" são
executados; casos level=="prompt" são SKIPADOS explicitamente (não são
verificáveis deterministicamente sem LLM).
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
    assert data["version"] == 1
    return data["cases"]


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


@pytest.mark.parametrize("case", [c for c in load_cases() if c.get("level") == "prompt"])
def test_prompt_level_invariants_skipped(case):
    pytest.skip(
        f"{case['id']}: invariante de prompt — não verificável deterministicamente "
        "sem LLM; coberto por smoke manual a cada mudança de prompt/modelo"
    )


# Invariantes level=="code" exercitados E2E contra o código real (Tarefa 5.1).
_CODE_INVARIANTS_COVERED = {
    "eye_safety_clamp", "no_clamp", "eye_safety_clamp_all", "all_off_called",
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
    """Caso `turn-off-all` (level=code): a tool com "all" delega a set_all(False)
    — sem iteração direta sobre controller.lights."""
    from unittest.mock import MagicMock
    from marvin_hue.chat.tools.light_tools import build_light_tools
    controller, manager = MagicMock(), MagicMock()
    manager.configs = []
    tools = {t.name: t for t in build_light_tools(controller, manager)}
    tools["turn_off_lights"].invoke({"light_name": "all"})
    controller.set_all.assert_called_once_with(False)


def test_eval_eye_safety_all_max_via_chokepoint():
    """Caso `eye-safety-all-max` (level=code), contra o chokepoint REAL:
    set_all_brightness clampa POR LÂMPADA (Tarefa 2.3)."""
    from unittest.mock import MagicMock
    from marvin_hue.controllers import HueController
    c = HueController.__new__(HueController)  # sem conectar à bridge
    fita = MagicMock(); fita.name = "Fita Led"
    teto = MagicMock(); teto.name = "Lâmpada 1"
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
        elif c.get("level") == "prompt":
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
