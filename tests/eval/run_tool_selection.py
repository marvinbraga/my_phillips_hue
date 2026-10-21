"""Eval ao vivo de seleção de tool (golden set hue.chat@2, casos level=prompt).

NÃO é coletado pelo pytest (custa tokens). Bridge, controller e todos os
serviços são MOCKADOS: nada fala com a bridge real nem com o app em execução.
O manager lê uma CÓPIA temporária de ``.res/setups.json`` (somente leitura).

Uso (na raiz do checkout a avaliar)::

    # branch
    uv run python -m tests.eval.run_tool_selection run --label branch --runs 3 \
        --out docs/evals/tool_selection_branch.json
    # baseline (origin/master em worktree); o runner/golden vêm do branch
    (cd <worktree> && PYTHONPATH=<worktree> uv run --project <repo> python \
        <repo>/tests/eval/run_tool_selection.py run --label baseline ...)
    # relatório
    uv run python -m tests.eval.run_tool_selection report \
        --baseline docs/evals/..._baseline.json --branch docs/evals/..._branch.json \
        --md docs/evals/....md

Critério por execução: passa se alguma tool esperada foi chamada (pelo
orquestrador ou dentro de um subagent), OU se o orquestrador delegou via
``task`` a um subagent cujo subconjunto contém a tool esperada; falha se
alguma tool proibida foi chamada. Score do caso = execuções que passaram / N.
Gate: Δ ≥ 0 no agregado dos intents pré-existentes (branch vs baseline) e
≥ 90% no agregado das tools novas.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

GOLDEN = Path(__file__).with_name("invariants.json")
MODEL = "claude-haiku-5-5"
PROVIDER = "anthropic"
LIGHTS = [
    "Lâmpada 1", "Lâmpada 2", "Lâmpada 3", "Lâmpada 4", "Hue Iris",
    "Hue Play 1", "Hue Play 2", "Fita Led", "Led cima",
]
NEW_TOOL_GATE = 0.90


# ----------------------------------------------------------------- superfície
def _mock_controller() -> MagicMock:
    from marvin_hue.apply_result import ApplyResult

    controller = MagicMock()
    controller.list_lights.return_value = list(LIGHTS)
    controller.get_lights_status.return_value = [
        {
            "name": n,
            "on": i % 2 == 0,
            "brightness": 120,
            "reachable": True,
            "color": {"r": 255, "g": 180, "b": 120},
        }
        for i, n in enumerate(LIGHTS)
    ]
    controller.apply_light_config.side_effect = lambda cfg, *a, **k: ApplyResult(
        applied=tuple(s.light_name for s in cfg.settings), failed=()
    )
    controller.turn_on.return_value = True
    controller.turn_off.return_value = True
    controller.set_brightness.return_value = True
    controller.turn_off_with_transition.return_value = True
    return controller


def _build_tools(controller: Any, manager: Any) -> list[Any]:
    try:
        from marvin_hue.chat.tools import build_all_tools
    except ImportError:  # baseline (antes do #16)
        from marvin_hue.chat.tools import build_light_tools

        return build_light_tools(controller, manager)
    return build_all_tools(controller, manager)


def prompt_surface_sha256() -> str:
    """Hash da superfície vista pelo modelo: prompts + nome/descrição/schema das tools."""
    from marvin_hue.chat.agents.react_agent import SYSTEM_PROMPT
    from marvin_hue.chat.subagents import definitions as d

    manager = MagicMock()
    manager.configs = []
    tools = _build_tools(_mock_controller(), manager)
    parts = [SYSTEM_PROMPT, d.SCENE_DESIGNER_PROMPT, d.CONFIG_LIBRARIAN_PROMPT, d.GENERAL_PROMPT]
    for t in sorted(tools, key=lambda t: t.name):
        parts.append(t.name)
        parts.append(t.description)
        parts.append(json.dumps(t.args, sort_keys=True, ensure_ascii=False))
    for names in (d.SCENE_DESIGNER_TOOLS, d.CONFIG_LIBRARIAN_TOOLS, d.GENERAL_TOOLS):
        parts.append(",".join(names))
    return hashlib.sha256("\n\x1f".join(parts).encode("utf-8")).hexdigest()


def _prompt_version() -> str:
    from marvin_hue.chat.agents import react_agent

    return getattr(react_agent, "PROMPT_VERSION", "hue.chat.prompt@1 (implícito)")


# ----------------------------------------------------------------- serviços fake
def _fake_services() -> Any | None:
    """ChatServices com fakes (só existe a partir do #16)."""
    try:
        from marvin_hue.chat.services import ChatServices
    except ImportError:
        return None
    from marvin_hue.domain.groups import LightGroup
    from marvin_hue.domain.schedules import Schedule
    from tests.chat.fakes import (
        HEALTH_PAYLOAD,
        FakeGroups,
        FakeHistory,
        FakeLastApplied,
        FakeMirror,
        FakeSchedules,
    )

    class _Favorites:
        def __init__(self) -> None:
            self.names: set[str] = set()

        async def list_existing(self) -> list[str]:
            return sorted(self.names)

        async def add(self, name: str) -> None:
            self.names.add(name)

        async def remove(self, name: str) -> None:
            self.names.discard(name)

    async def _health() -> dict[str, Any]:
        return HEALTH_PAYLOAD

    groups = FakeGroups(
        [LightGroup(id="g-sala", name="Sala", light_ids=["a", "b"])],
        members={"g-sala": ["Lâmpada 1", "Lâmpada 2"]},
    )
    schedules = FakeSchedules(
        [Schedule(id="s-1", name="Dormir", time_hhmm="23:00", action_type="power_off")]
    )
    history, mirror, last, favs = FakeHistory(), FakeMirror(), FakeLastApplied(), _Favorites()
    return ChatServices(
        favorites_provider=lambda: favs,
        history_provider=lambda: history,
        groups_provider=lambda: groups,
        schedules_provider=lambda: schedules,
        mirror_provider=lambda: mirror,
        health_provider=lambda: _health,
        last_applied_provider=lambda: last,
    )


# ----------------------------------------------------------------- execução
class _Recorder:
    """Callback: tools chamadas em qualquer nível (orquestrador e subagents) + tokens."""

    def __init__(self) -> None:
        from langchain_core.callbacks import AsyncCallbackHandler

        recorder = self

        class _Handler(AsyncCallbackHandler):
            async def on_tool_start(self, serialized, input_str, **kwargs):  # noqa: ANN001
                recorder.tools.append((serialized or {}).get("name") or kwargs.get("name"))

            async def on_llm_end(self, response, **kwargs):  # noqa: ANN001
                for gens in response.generations:
                    for g in gens:
                        usage = getattr(getattr(g, "message", None), "usage_metadata", None)
                        if usage:
                            recorder.input_tokens += int(usage.get("input_tokens", 0))
                            recorder.output_tokens += int(usage.get("output_tokens", 0))

        self.handler = _Handler()
        self.tools: list[str] = []
        self.input_tokens = 0
        self.output_tokens = 0


def _subsets() -> dict[str, set[str]]:
    from marvin_hue.chat.subagents import definitions as d

    return {
        "scene-designer": set(d.SCENE_DESIGNER_TOOLS),
        "config-librarian": set(d.CONFIG_LIBRARIAN_TOOLS),
        "general-purpose": set(d.GENERAL_TOOLS),
    }


def _orchestrator_tool_calls(messages: list[Any]) -> list[dict[str, Any]]:
    from langchain_core.messages import AIMessage

    calls: list[dict[str, Any]] = []
    for m in messages:
        if isinstance(m, AIMessage):
            calls.extend({"name": c["name"], "args": c.get("args", {})} for c in m.tool_calls)
    return calls


def _score(case: dict[str, Any], tools: list[str], calls: list[dict[str, Any]]) -> tuple[bool, str]:
    expected = set(case["expected_tools"])
    forbidden = set(case.get("forbidden_tools", []))
    hit_forbidden = forbidden & set(tools)
    if hit_forbidden:
        return False, f"proibida: {sorted(hit_forbidden)}"
    if expected & set(tools):
        return True, "tool esperada chamada"
    subsets = _subsets()
    for call in calls:
        if call["name"] == "task":
            sub = str(call["args"].get("subagent_type", ""))
            if expected & subsets.get(sub, set()):
                return True, f"delegou a {sub}"
    return False, "tool esperada não chamada"


async def _run_one(agent: Any, case: dict[str, Any], run: int) -> dict[str, Any]:
    from langchain_core.messages import HumanMessage

    rec = _Recorder()
    session = f"eval-{case['id']}-{run}"
    config = dict(agent._config_for(session))
    config.setdefault("recursion_limit", 25)
    config["callbacks"] = [rec.handler]
    started = time.monotonic()
    error = None
    messages: list[Any] = []
    try:
        result = await agent._agent.ainvoke(
            {"messages": [HumanMessage(content=case["intent"])]}, config=config
        )
        messages = result.get("messages", [])
    except Exception as exc:  # noqa: BLE001 — erro conta como falha do caso
        error = f"{type(exc).__name__}: {exc}"[:300]
    calls = _orchestrator_tool_calls(messages)
    passed, why = _score(case, rec.tools, calls) if error is None else (False, error)
    return {
        "case": case["id"],
        "run": run,
        "passed": passed,
        "reason": why,
        "tools_called": rec.tools,
        "orchestrator_calls": [c["name"] for c in calls],
        "input_tokens": rec.input_tokens,
        "output_tokens": rec.output_tokens,
        "latency_s": round(time.monotonic() - started, 2),
    }


def _make_agent(manager: Any) -> Any:
    from marvin_hue.chat.agents.react_agent import create_hue_agent

    kwargs: dict[str, Any] = {}
    if "services" in inspect.signature(create_hue_agent).parameters:
        kwargs["services"] = _fake_services()
    return create_hue_agent(
        _mock_controller(), manager, provider=PROVIDER, model=MODEL, temperature=0.0, **kwargs
    )


async def _run(label: str, runs: int, concurrency: int, only: set[str] | None) -> dict[str, Any]:
    from marvin_hue.basics import LightSetupsManager

    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    cases = [c for c in golden["cases"] if c.get("level") == "prompt"]
    if only:
        cases = [c for c in cases if c["id"] in only]
    tmp = Path(tempfile.mkdtemp(prefix="hue-eval-"))
    try:
        setups = tmp / "setups.json"
        shutil.copyfile(".res/setups.json", setups)  # cópia: nunca escreve em .res/
        manager = LightSetupsManager(str(setups))
        agent = _make_agent(manager)
        available = set()
        sem = asyncio.Semaphore(concurrency)

        async def guarded(case: dict[str, Any], run: int) -> dict[str, Any]:
            async with sem:
                return await _run_one(agent, case, run)

        names = {t.name for t in _build_tools(_mock_controller(), manager)}
        jobs = []
        for case in cases:
            if set(case["expected_tools"]) & names:
                available.add(case["id"])
                jobs.extend(guarded(case, r) for r in range(runs))
        results = await asyncio.gather(*jobs)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {
        "label": label,
        "golden_set": f"{golden['name']}@{golden['version']}",
        "prompt_version": _prompt_version(),
        "prompt_surface_sha256": prompt_surface_sha256(),
        "model": MODEL,
        "provider": PROVIDER,
        "runs_per_case": runs,
        "cases": {c["id"]: {"pre_existing": c["pre_existing"], "intent": c["intent"],
                            "expected_tools": c["expected_tools"],
                            "applicable": c["id"] in available} for c in cases},
        "results": list(results),
    }


# ----------------------------------------------------------------- relatório
def _rates(data: dict[str, Any]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for cid, meta in data["cases"].items():
        rows = [r for r in data["results"] if r["case"] == cid]
        out[cid] = (sum(r["passed"] for r in rows) / len(rows)) if (meta["applicable"] and rows) else None
    return out


def _tokens(data: dict[str, Any]) -> tuple[int, int]:
    return (
        sum(r["input_tokens"] for r in data["results"]),
        sum(r["output_tokens"] for r in data["results"]),
    )


def build_report(baseline: dict[str, Any], branch: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    base, cur = _rates(baseline), _rates(branch)
    pre = [cid for cid, m in branch["cases"].items() if m["pre_existing"]]
    new = [cid for cid, m in branch["cases"].items() if not m["pre_existing"]]

    def agg(rates: dict[str, float | None], ids: list[str]) -> float | None:
        vals = [rates[i] for i in ids if rates.get(i) is not None]
        return sum(vals) / len(vals) if vals else None

    pre_base, pre_cur, new_cur = agg(base, pre), agg(cur, pre), agg(cur, new)
    pre_ok = pre_base is not None and pre_cur is not None and pre_cur - pre_base >= 0
    new_ok = new_cur is not None and new_cur >= NEW_TOOL_GATE
    verdict = "PASS" if pre_ok and new_ok else "FAIL"
    bi, bo = _tokens(baseline)
    ci, co = _tokens(branch)
    runs_b, runs_c = len(baseline["results"]) or 1, len(branch["results"]) or 1

    def pct(v: float | None) -> str:
        return "n/a" if v is None else f"{v * 100:.0f}%"

    lines = [
        f"# Eval Report — seleção de tool do chat ({branch['golden_set']})",
        "",
        f"Triple (branch): `{branch['prompt_version']}` | `{branch['model']}` | `{branch['golden_set']}`",
        f"Triple (baseline): `{baseline['prompt_version']}` | `{baseline['model']}` | `{baseline['golden_set']}`",
        f"Superfície de prompt (sha256): baseline `{baseline['prompt_surface_sha256'][:12]}`, "
        f"branch `{branch['prompt_surface_sha256'][:12]}`",
        f"N = {branch['runs_per_case']} execuções por caso; bridge e serviços mockados.",
        "",
        "| Caso | Pré-existente | Tools esperadas | Baseline | Branch | Δ |",
        "|---|---|---|---|---|---|",
    ]
    for cid, meta in branch["cases"].items():
        b, c = base.get(cid), cur.get(cid)
        delta = "n/a" if b is None or c is None else f"{(c - b) * 100:+.0f} pp"
        lines.append(
            f"| `{cid}` | {'sim' if meta['pre_existing'] else 'não'} | "
            f"{', '.join(meta['expected_tools'])} | {pct(b)} | {pct(c)} | {delta} |"
        )
    lines += [
        "",
        "| Métrica | Baseline | Branch | Δ | Limite | Status |",
        "|---|---|---|---|---|---|",
        f"| Acerto intents pré-existentes | {pct(pre_base)} | {pct(pre_cur)} | "
        f"{'n/a' if pre_base is None or pre_cur is None else f'{(pre_cur - pre_base) * 100:+.1f} pp'} | Δ ≥ 0 | "
        f"{'OK' if pre_ok else 'FALHOU'} |",
        f"| Acerto tools novas | n/a | {pct(new_cur)} | n/a | ≥ {NEW_TOOL_GATE * 100:.0f}% | "
        f"{'OK' if new_ok else 'FALHOU'} |",
        f"| Tokens de entrada / execução | {bi // runs_b} | {ci // runs_c} | "
        f"{(ci / runs_c - bi / runs_b) / max(bi / runs_b, 1) * 100:+.0f}% | informativo | — |",
        f"| Tokens de saída / execução | {bo // runs_b} | {co // runs_c} | "
        f"{(co / runs_c - bo / runs_b) / max(bo / runs_b, 1) * 100:+.0f}% | informativo | — |",
        "",
        f"**Veredito: {verdict}**",
        "",
        "## Falhas por execução (branch)",
        "",
    ]
    fails = [r for r in branch["results"] if not r["passed"]]
    if not fails:
        lines.append("Nenhuma.")
    for r in fails:
        lines.append(
            f"- `{r['case']}` run {r['run']}: {r['reason']} — chamadas: "
            f"{', '.join(t for t in r['tools_called'] if t) or 'nenhuma'}"
        )
    summary = {
        "verdict": verdict,
        "pre_existing": {"baseline": pre_base, "branch": pre_cur},
        "new_tools": {"branch": new_cur, "gate": NEW_TOOL_GATE},
        "per_case": {cid: {"baseline": base.get(cid), "branch": cur.get(cid)} for cid in branch["cases"]},
        "tokens": {"baseline": {"input": bi, "output": bo}, "branch": {"input": ci, "output": co}},
    }
    return "\n".join(lines) + "\n", summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--label", required=True)
    run.add_argument("--runs", type=int, default=3)
    run.add_argument("--concurrency", type=int, default=4)
    run.add_argument("--only", nargs="*")
    run.add_argument("--out", required=True)
    rep = sub.add_parser("report")
    rep.add_argument("--baseline", required=True)
    rep.add_argument("--branch", required=True)
    rep.add_argument("--md", required=True)
    rep.add_argument("--json", required=True)
    args = parser.parse_args(argv)
    if args.cmd == "run":
        data = asyncio.run(_run(args.label, args.runs, args.concurrency, set(args.only or []) or None))
        Path(args.out).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        rates = _rates(data)
        for cid, rate in rates.items():
            print(f"{cid:24s} {'n/a' if rate is None else f'{rate:.2f}'}")
        return 0
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    branch = json.loads(Path(args.branch).read_text(encoding="utf-8"))
    md, summary = build_report(baseline, branch)
    Path(args.md).write_text(md, encoding="utf-8")
    Path(args.json).write_text(
        json.dumps({**summary, "baseline_run": baseline, "branch_run": branch}, indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    print(md)
    return 0 if summary["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
