# Project Rules

> Jarvis Standards apply for generic engineering. This file documents only what is specific to Marvin Hue.
> Generated from legacy project analysis (2026-08-25 Wave 0).

## Tech Stack (Not in Jarvis Standards)

| Technology | Purpose | Notes |
|------------|---------|-------|
| phue | Hue Bridge REST | Sync I/O; always offload with `asyncio.to_thread` |
| hue-entertainment | DTLS Entertainment stream | `run_coro` MUST NOT run on the FastAPI event loop |
| mss + Pillow | Screen capture | Daemon thread in `ScreenMirror` |
| sounddevice + numpy | Audio capture / DSP | Daemon thread in `AudioMirror` |
| aiosqlite | App catalog DB | `.res/marvin_hue.sqlite`; not SQLAlchemy |
| LangChain / LangGraph | Chat agent | Fail-open if keys missing |
| loguru | Logging | `diagnose=False` on file sink |
| Jinja2 + vanilla JS + Bootstrap CDN | UI | Not React/Next.js |

## Non-Standard Directory Structure

| Directory | Purpose | Pattern |
|-----------|---------|---------|
| `marvin_hue/` package root | Legacy lighting core | `colors`, `basics`, `controllers` |
| `marvin_hue/domain/` | Catalog entities | Dataclasses, no I/O |
| `marvin_hue/persistence/` | aiosqlite adapters | Protocol + `Sqlite*` |
| `marvin_hue/services/` | Use cases | Registry, groups, schedules, health |
| `marvin_hue/output/` | Light transport port | REST vs Entertainment |
| `marvin_hue/chat/` | LLM agent | Vertical feature package |
| `web/templates/`, `web/static/` | SSR UI | One JS file per page |
| `.res/` | JSON + SQLite data | setups, positions, locations |

## External Integrations

| Service | Purpose |
|---------|---------|
| Philips Hue Bridge | Physical lights (REST + optional Entertainment) |
| OpenAI / Anthropic / xAI / Groq | Chat providers (optional) |

## Environment Configuration

Canonical source: `marvin_hue/config.py` (`settings` singleton). Bridge IP is required. Optional `API_KEY` protects **`/api/*` only**.

## Domain Terminology

| Term | Definition |
|------|------------|
| Light name | Exact Hue display name; join key across JSON, SQLite, and phue |
| RegisteredLight | SQLite catalog entity (UUID + name) |
| LightConfig | Named scene of `LightSetting`s from `.res/setups.json` |
| ApplyResult | Per-light outcome of applying a scene (applied vs failed) |
| LightOutputPort | Frame sink for mirrors (REST or Entertainment) |
| enabled_for_app | Registry flag; controller skips disabled lights |
| EYE_SAFETY_LIMITS | Hardcoded brightness caps (Fita Led, Led cima) |

## Wave 0 constraints

- Do not introduce SQLAlchemy, Alembic, structlog, or OpenTelemetry.
- Do not add a Facade.
- Do not commit unless asked.
- Package-wide coverage is ~30%; require tests for **changed** behavior, not 85% on the whole package.
- Canonical setups path is JSON + `LightSetupsManager`, not `LightConfigEnum`.
- Physical lights (9): Lâmpada 1–4, Hue Iris, Hue Play 1–2, Fita Led, Led cima.
- Hue Play 1 = left, Hue Play 2 = right (align locations JSON to positions JSON).
- `duration_minutes` on apply is **not** a timer; stop implying it is. Keep the request field for compatibility if needed; do not implement a background restore timer in this wave.
- Mirror stop must use `end_output=False` and `await entertainment.stop_stream()` from the event loop, never `run_coro` on the loop.

## Waves 1–3 constraints

- Canonical setups: `.res/setups.json` + `LightSetupsManager`. Delete class/enum catalogs after CLI migrates.
- Physical writes still use exact Hue **name** as join key (phue). Registry UUID is canonical for catalog/groups; do not rewrite all of `setups.json` to UUIDs.
- No Facade. No SQLAlchemy/OTel/structlog.
- Do not commit unless asked.
- Tests for changed behavior; do not require 85% package-wide.
- Keep `/apply` and `/mirror/*` working (LAN UI). New `/api/apply` and `/api/mirror/*` may be aliases.
- `API_KEY` still only `/api/*` unless adding aliases; document that.
- Chat UI JS belongs in `web/static/chat.js`, not inline in the template.
- Backup must reuse lifespan SQLite repos, not open extra connections.
- Eye-safety: hardcoded map is fallback; seed registry `eye_safety_limit_pct` for Fita Led and Led cima at 25 when NULL.

