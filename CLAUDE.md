# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Marvin Hue is a Python 3.11+ Philips Hue lighting console. You apply JSON scene setups, manage a SQLite catalog (lights, groups, schedules, history), mirror screen or audio onto lights, and talk to a LangGraph chat agent.

Package version is **0.1.0**. The FastAPI app still reports **2.0.0** — do not invent a version bump.

Tooling is **uv**, not Poetry.

## Commands

```bash
# Install
uv sync
uv sync --extra dev

# CLI (JSON setups via LightSetupsManager)
uv run python main.py

# FastAPI (port 5081)
uv run python app.py
uv run uvicorn app:app --reload --port 5081

# Tests (writes htmlcov/)
uv run pytest
```

Do not quote a coverage percentage. After `uv run pytest`, open `htmlcov/index.html`.

## Configuration

Copy `.env.example` to `.env` and set `BRIDGE_IP`.

Chat providers: `openai` | `anthropic` | `xai` | `groq`. There is **no Ollama** provider.

`CHAT_REQUIRE_APPROVAL` (default `false`) makes the agent stop for human approval before actions that persist or take over: `create_config`, `save_current_config`, `create_schedule`, `set_schedule_enabled`, `start_mirror` (policy in `marvin_hue/chat/hitl.py`; reversible mutations stay ungated). Each decision must carry the request `id`. The Chat screen shows an Aprovar/Rejeitar card; API clients get `approval_required` and answer with `POST /api/chat/resume`. Interrupts raised inside subagents (`task` tool) propagate to the orchestrator and resume from there.

`API_KEY` (optional) protects only `/api/*`. HTML pages, `/static/*`, `/apply`, `/configurations`, `/mirror/*`, `/positions*`, and WebSockets stay open for LAN UI.

HTML pages send `Content-Security-Policy: img-src 'self' data:` and chat markdown forbids images (DOMPurify), so model output cannot exfiltrate data through image URLs.

The chat is a full-privilege channel (lights, scenes, schedules, mirror). `WS /ws/chat` rejects cross-origin browser connections (`Origin` must match `Host`; close code 1008); clients without `Origin` are accepted.

## Architecture

Modular monolith in `marvin_hue/`. Composition root is the FastAPI lifespan in `app.py` (port **5081**). `marvin_hue/api/dependencies.py` is a process-wide service locator.

### Core package (`marvin_hue/`)

- **colors.py**: `Color` (RGBA; brightness 0–254)
- **utils.py**: `RGBtoXYAdapter` converts RGB to Hue XY
- **basics.py**: `LightSetting`, `LightConfig`, `LightSetupsManager` (loads `.res/setups.json`)
- **setup_builder.py**: Builds `LightConfig` from JSON dicts
- **controllers.py**: `HueController` (phue REST)
- **apply_result.py**: Per-light `ApplyResult` (`applied` / `failed`)
- **screen_mirror.py** / **audio_mirror.py**: Capture loops
- **services/mirror_control.py**: `MirrorControlService` (start/stop screen or audio)
- **services/schedule_runner.py**: `ScheduleRunner` (`GET /api/health` reports `schedules.runner_alive`)
- **domain/**, **persistence/**, **services/**: Catalog (lights, groups, schedules, scene history)
- **output/**: `LightOutputPort` (REST or Entertainment DTLS)
- **entertainment/**: Hue Entertainment client and credentials
- **chat/**: LangGraph agent, providers, tools, middleware
- **api/**: Routes, models, websockets, API-key middleware

Canonical setups: **`.res/setups.json`** (~69 themes) via `LightSetupsManager`. Do **not** add a class in `setups.py`.

### Entry points

- **main.py**: CLI applies JSON setups via `LightSetupsManager`
- **app.py**: FastAPI app (version string `2.0.0`) on port 5081

Web screens: Controle, Lâmpadas, Grupos, Agendamentos, Posicionamento, Espelhamento, Saúde, Chat.

### Routes

**Pages**

| Path | Screen |
|------|--------|
| `GET /` | Controle |
| `GET /lights` | Lâmpadas |
| `GET /groups` | Grupos |
| `GET /schedules` | Agendamentos |
| `GET /positions-config` | Posicionamento |
| `GET /mirror` | Espelhamento |
| `GET /health` | Saúde |
| `GET /chat` | Chat |

**Scenes and positions (no API key)**

- `GET /configurations` (`?include_settings=true` adds per-light `color` + eye-safety-clamped `preview`)
- `GET /configurations/favorites`, `PUT /configurations/favorites/{name}`, `DELETE /configurations/favorites/{name}` — favorites stored in SQLite (`scene_favorites`, schema v5); orphans hidden, kept
- `GET /configurations/last-applied` — `{name, source, applied_at}` of the last scene applied with ≥1 light (`last_applied_scene`, schema v6; source `apply` / `group` / `schedule` / `chat`); all `null` when never set, orphaned, or cleared (`POST /lights/off`, undo restoring ≥1 light, whole-house schedule `power_off`, mirror start). Recording/clearing is best-effort inside `LastAppliedSceneService` (`marvin_hue/services/last_applied_scene.py` owns ports, provider and source constants). Controle pre-selects it without preview
- `DELETE /configurations/{name:path}` — removes every entry with that exact name from `setups.json` (`LightSetupsManager.remove_config`, atomic save) → **200** `{name, deleted: true}`, **404** unknown, **500** write failed (in-memory list restored). Registered after the favorites routes so `/configurations/favorites/{name}` still wins. Favorites / last-applied become orphans (hidden); `apply_config` schedules naming it fail at run time (`400` on manual run, `error` on tick). Controle: "Excluir configuração" acts on the selected scene after a confirmation modal
- `POST /apply` — `ApplyResult` → HTTP **200** (all ok), **207** (partial), **500** (all failed). `duration_minutes` is accepted and **ignored** (not a restore timer)
- `POST /lights/off` — snapshot (for undo) + turn off every enabled light; `ApplyResult` → 200 / 207 / 500
- `GET /positions`, `POST /positions`, `POST /positions/reset`

**Mirror (no API key)** — `MirrorControlService`

- `POST /mirror/start`, `POST /mirror/stop`, `GET /mirror/status`, `POST /mirror/settings`
- `GET /mirror/profiles`, `POST /mirror/profile`
- `GET /mirror/entertainment/status`, `POST /mirror/entertainment/pair`, `GET /mirror/entertainment/areas`

**`/api/*` (requires `API_KEY` when that env var is set)**

- `GET /api/bridge/status`, `GET /api/lights/status`
- `GET /api/health` — includes `schedules.runner_alive`
- Lights registry, groups, schedules, history, backup
- Chat: `GET /api/chat/status`, `POST /api/chat/message`, `POST /api/chat/resume`, `GET /api/chat/pending`, `POST /api/chat/clear`, `POST /api/chat/configure`

**WebSockets (no API key)**

- `WS /ws/mirror`
- `WS /ws/chat` — actions `message`, `resume`, `pending`, `clear`; frames `typing`, `response`, `approval_required`, `error`, `cleared`

### Screen mirroring

1. Map each light to a screen region on **Posicionamento** (`/positions-config`).
2. Start mirroring on **Espelhamento** (`/mirror`).
3. Lights update at the configured FPS (default **25** on start; named profiles `cinema` / `fps` / `ambient` change this).
4. `/ws/mirror` pushes unified status (~12 FPS for screen, ~25 FPS for audio).

Positions in `.res/light_positions.json`: `left`, `right`, `top`, `bottom`, `top-left`, `top-right`, `bottom-left`, `bottom-right`, `center`, `ambient`, `none`.

### Data flow (scenes)

1. You pick a setup name (web, CLI, or `POST /apply`).
2. `LightSetupsManager.get_config()` loads it from `.res/setups.json`.
3. `HueController.apply_light_config()` converts RGB → XY and writes the bridge.
4. The HTTP response is an `ApplyResult` mapped to 200 / 207 / 500.

### Light names

Nine lights: `Lâmpada 1`, `Lâmpada 2`, `Lâmpada 3`, `Lâmpada 4`, `Hue Iris`, `Hue Play 1`, `Hue Play 2`, `Fita Led`, `Led cima`. Names must match the Hue bridge exactly.

## Adding lighting configurations

1. Add an object to `.res/setups.json` (`name`, `description`, `settings` with `light_name` + RGBA, brightness 0–254).
2. Restart the app, or use `--reload` in development.
3. Apply it from Controle, the CLI, or `POST /apply`.

Do not add a Python class in `setups.py` or an enum in `factories.py`.

## Dependencies

- **FastAPI** + **uvicorn**: Web
- **phue**: Hue REST
- **mss** + **Pillow**: Screen capture
- **aiosqlite** + **loguru**: Catalog DB and logging
- **LangChain** / **LangGraph**: Chat
- **hue-entertainment**: Optional DTLS stream
