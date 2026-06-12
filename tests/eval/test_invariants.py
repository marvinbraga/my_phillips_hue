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
LOCATIONS = Path(".res/light_physical_locations.json")


def load_cases():
    data = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert data["version"] == 1
    return data["cases"]


@pytest.mark.parametrize("case", [c for c in load_cases() if c["invariant"] in ("eye_safety_clamp", "no_clamp")])
def test_eye_safety_clamp_contract(case):
    # invariants.json expressa o brilho em percentual -> escala "pct".
    out = clamp_eye_safety(case["target_light"], case["requested_brightness_pct"], scale="pct")
    assert out <= case["max_brightness_pct"], (
        f"{case['id']}: {case['target_light']} deveria ser limitado a "
        f"{case['max_brightness_pct']}%, obteve {out}%"
    )


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
