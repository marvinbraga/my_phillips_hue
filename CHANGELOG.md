# Changelog

Notable changes to Marvin Hue. Package version is **0.1.0**; the FastAPI app still reports **2.0.0**.

## Unreleased

### Wave 0

- `POST /apply` maps `ApplyResult` to HTTP **200** (all lights applied), **207** (partial), or **500** (all attempted lights failed).
- `duration_minutes` stays on the apply request for compatibility and is **ignored**. It is not a restore timer.
- `GET /api/health` includes `schedules.runner_alive` from `ScheduleRunner`.
- Screen and audio mirroring start, stop, and report status through `MirrorControlService`.

### Wave 1

- Canonical lighting themes live in `.res/setups.json` (~69) and load through `LightSetupsManager`, including the CLI.
- Docs match the running app: **uv** (not Poetry), Python **≥3.11**, chat providers `openai` | `anthropic` | `xai` | `groq` (no Ollama), **nine** lights including `Lâmpada 3`.
- GitHub Actions CI on pull requests and on push to `master`/`main` runs `pytest` and `ruff`.

### Wave 2–3

Follow-up work in this band is catalog identity and splitting large modules. UUID-canonical lights, a single `ApplyConfigService`, and `app.state` DI are **not** claimed here. Routing scenes through `LightOutputPort` and breaking up god modules remain later work.
