# Home Features Bundle Implementation Plan

> **For Agents:** Implement this plan task-by-task following the structure below; review between tasks via jarvis-default-codereview. Prefer **one phase per agent** (or sequential within a phase). Phases A → B are sequential foundation; C–E can run in parallel after A; F and G need A; H needs C (+ existing registry); I needs endpoints from earlier phases.

**Goal:** Wire the existing SQLite lights registry into runtime safety/enablement, then add home-friendly features (API key, groups, undo, schedules, mirror profiles, chat-by-room, import/export, health, unified nav) without Postgres, multi-bridge, or native mobile.

**Architecture:** Keep the ports-and-adapters style already used for lights (`domain/` → `persistence/` → `services/` → `api/routes/`). Extend schema via numbered aiosqlite migrations (no Alembic). Eye safety and `enabled_for_app` become a **sync in-process cache** refreshed from SQLite on startup and after registry mutations, so `HueController` / `ScreenMirror` / chat middleware stay sync and free of chat↔controller cycles. New features (groups, scene history, schedules) live in the same app DB (`.res/marvin_hue.sqlite`). Optional `settings.api_key` middleware protects `/api/*` only when non-empty so local HTML UI keeps working. Schedules run via an asyncio loop started in FastAPI lifespan. UI stays Jinja2 + Bootstrap breadcrumbs via a shared partial.

**Tech Stack:**
- Python 3.10+ (project: `>=3.10`; runtime often 3.13)
- FastAPI + uvicorn + Jinja2 + Bootstrap 5 (existing)
- aiosqlite (existing; **no** Alembic/SQLAlchemy/Postgres)
- phue + mss + Pillow (existing)
- pytest + pytest-asyncio + httpx (existing)
- stdlib only for ZIP (`zipfile`) and scheduling tick loop

**Out of scope (do not implement):**
- Postgres, multi-bridge, multi-user OAuth, native mobile
- Migrating `setups.json` / `light_positions.json` into SQL as primary store (export may include them as files)
- Hard-delete of Hue physical lights
- Alembic

**Existing anchors (do not reinvent):**
| Concern | Path |
|---------|------|
| Eye safety (hardcoded map) | `marvin_hue/eye_safety.py` |
| Controller chokepoint | `marvin_hue/controllers.py` (`set_light_color`, `set_brightness`, `apply_light_config`) |
| Registry domain | `marvin_hue/domain/lights.py` |
| Schema v1 + `init_db` | `marvin_hue/persistence/schema.py` (`CURRENT_SCHEMA_VERSION = 1`) |
| Light repo | `marvin_hue/persistence/light_repository.py` |
| Light service | `marvin_hue/services/light_registry.py` |
| DI | `marvin_hue/api/dependencies.py` |
| Lifespan | `app.py` |
| Settings (`api_key`, `app_db_path`) | `marvin_hue/config.py` |
| Mirror | `marvin_hue/screen_mirror.py`, `marvin_hue/api/routes/mirror.py` |
| Chat tools | `marvin_hue/chat/tools/light_tools.py` |
| Chat eye middleware | `marvin_hue/chat/middleware/eye_safety.py` |
| Live light status API | `GET /api/lights/status` in `marvin_hue/api/routes/status.py` |
| Registry CRUD API | `marvin_hue/api/routes/lights.py` (`/api/lights*`) |
| Apply config | `POST /apply` in `marvin_hue/api/routes/configurations.py` |
| Templates | `web/templates/*.html` |
| DB file | `.res/marvin_hue.sqlite` |

**Global Prerequisites:**
- Environment: Linux, project root `/run/media/marvinbraga/dados-linux/marvin/my_phillips_hue`
- Tools: `uv`, `git`, pytest via `uv run`
- Access: Hue bridge **not** required for unit/API tests (mock `HueController`); bridge only for manual smoke
- Constraints: DRY/YAGNI/TDD; do not break existing registry tests; keep chat checkpointer DB isolated from app DB

**Verification before starting:**
```bash
cd /run/media/marvinbraga/dados-linux/marvin/my_phillips_hue
python --version   # Expected: Python 3.10+
uv --version       # Expected: uv 0.x
uv run pytest tests/test_controller_eye_safety.py tests/test_api_lights_registry.py tests/test_persistence_schema.py -q --no-cov
# Expected: all PASSED
```

**Target schema version after full plan:** `CURRENT_SCHEMA_VERSION = 4`
| Version | Tables / changes |
|---------|------------------|
| 1 (exists) | `lights`, `schema_version` |
| 2 | `light_groups`, `light_group_members` |
| 3 | `scene_snapshots` |
| 4 | `schedules` |

**Parallel execution map:**
```
Phase A (registry runtime) ──► Phase B (api_key)
         │
         ├──► Phase C (groups)  ──┐
         ├──► Phase D (undo)    ──┼──► Phase H (import/export) ──► Phase I (health+nav)
         ├──► Phase E (schedules)─┘
         ├──► Phase F (mirror)
         └──► Phase G (chat tools)
```

---

## Phase A — Wire registry into runtime (eye safety + enabled_for_app)

**Why first:** Every later feature that touches lights must honor the same chokepoint.

### Task A1: Runtime eye-safety + enablement cache module

**Files:**
- Modify: `marvin_hue/eye_safety.py`
- Test: `tests/test_eye_safety_runtime.py` (create)

**Prerequisites:**
- Files must exist: `marvin_hue/eye_safety.py`

**Step 1: Write the failing tests**
```python
# tests/test_eye_safety_runtime.py
from marvin_hue import eye_safety as es


def setup_function():
    es.clear_runtime_policy()


def test_fallback_hardcoded_when_no_runtime():
    assert es.eye_safety_limit_pct("Fita Led") == 25
    assert es.eye_safety_limit_pct("Lâmpada 1") is None


def test_runtime_overrides_and_adds_limits():
    es.set_runtime_policy(
        limits_pct={"Fita Led": 10, "Hue Iris": 40},
        disabled_names=set(),
    )
    assert es.eye_safety_limit_pct("Fita Led") == 10
    assert es.eye_safety_limit_pct("Hue Iris") == 40
    assert es.clamp_eye_safety("Fita Led", 100, scale="pct") == 10
    assert es.clamp_eye_safety("Fita Led", 254, scale="hue") == int((10 / 100) * 254)


def test_runtime_none_limit_falls_back_to_hardcoded():
    # name present with None → fall back to hardcoded if any
    es.set_runtime_policy(limits_pct={"Fita Led": None}, disabled_names=set())
    assert es.eye_safety_limit_pct("Fita Led") == 25


def test_enabled_for_app_defaults_true():
    assert es.is_enabled_for_app("anything") is True
    es.set_runtime_policy(limits_pct={}, disabled_names={"Hue Play 1"})
    assert es.is_enabled_for_app("Hue Play 1") is False
    assert es.is_enabled_for_app("Hue Play 2") is True


def test_clear_runtime_policy_restores_defaults():
    es.set_runtime_policy(limits_pct={"X": 5}, disabled_names={"Y"})
    es.clear_runtime_policy()
    assert es.eye_safety_limit_pct("X") is None
    assert es.is_enabled_for_app("Y") is True
```

**Step 2: Run test to verify it fails**
```bash
uv run pytest tests/test_eye_safety_runtime.py -v --no-cov
```
Expected:
```
FAILED ... AttributeError / ImportError for set_runtime_policy / is_enabled_for_app
```

**Step 3: Write minimal implementation**

Replace `marvin_hue/eye_safety.py` with:
```python
"""Invariante de segurança ocular — fonte única de verdade (produção).

Hardcoded EYE_SAFETY_LIMITS remains the offline fallback.
Runtime policy (from SQLite lights registry) may override limits and
mark lights as disabled for app features (enabled_for_app=False).
"""
from __future__ import annotations

# Limite por lâmpada, em PERCENTUAL (0-100). Fallback when registry silent.
EYE_SAFETY_LIMITS: dict[str, int] = {"Fita Led": 25, "Led cima": 25}

# Runtime overlays (name -> pct or None meaning "no extra row limit")
_runtime_limits_pct: dict[str, int | None] | None = None
_runtime_disabled: set[str] | None = None


def set_runtime_policy(
    *,
    limits_pct: dict[str, int | None],
    disabled_names: set[str],
) -> None:
    """Install policy from registry (sync cache). Call from async layer after load."""
    global _runtime_limits_pct, _runtime_disabled
    _runtime_limits_pct = dict(limits_pct)
    _runtime_disabled = set(disabled_names)


def clear_runtime_policy() -> None:
    """Clear runtime overlays (tests / shutdown)."""
    global _runtime_limits_pct, _runtime_disabled
    _runtime_limits_pct = None
    _runtime_disabled = None


def is_enabled_for_app(light_name: str) -> bool:
    """False only when registry marks the light disabled."""
    if _runtime_disabled is None:
        return True
    return light_name not in _runtime_disabled


def eye_safety_limit_pct(light_name: str) -> int | None:
    """Limite percentual da lâmpada, ou None se não houver restrição."""
    if _runtime_limits_pct is not None and light_name in _runtime_limits_pct:
        runtime = _runtime_limits_pct[light_name]
        if runtime is not None:
            return runtime
        # Explicit null in DB → fall back to hardcoded for that name
    return EYE_SAFETY_LIMITS.get(light_name)


def clamp_eye_safety(light_name: str, value: int, scale: str = "pct") -> int:
    """Clampa `value` ao limite da lâmpada na escala indicada."""
    limit_pct = eye_safety_limit_pct(light_name)
    if limit_pct is None:
        return value
    if scale == "pct":
        return min(value, limit_pct)
    if scale == "hue":
        hue_limit = int((limit_pct / 100) * 254)
        return min(value, hue_limit)
    raise ValueError(f"escala desconhecida: {scale!r}")
```

**Step 4: Verify tests pass**
```bash
uv run pytest tests/test_eye_safety_runtime.py tests/test_controller_eye_safety.py -v --no-cov
```
Expected: all PASSED (existing controller tests still use hardcoded fallback).

**Step 5: Commit**

Use `jarvis-default-commit` skill to stage and commit changes.

**If Task Fails:**
1. Import cycle → keep policy only in `eye_safety.py` (no imports from services)
2. Existing eye-safety tests fail → ensure fallback still returns 25 for Fita Led / Led cima

---

### Task A2: Refresh policy from LightRegistryService

**Files:**
- Modify: `marvin_hue/services/light_registry.py`
- Test: `tests/test_light_registry_policy_refresh.py` (create)

**Prerequisites:**
- Task A1 complete
- `LightRegistryService.list_lights` exists

**Step 1: Write the failing test**
```python
# tests/test_light_registry_policy_refresh.py
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from marvin_hue import eye_safety as es
from marvin_hue.domain.lights import RegisteredLight
from marvin_hue.services.light_registry import LightRegistryService


@pytest.fixture(autouse=True)
def _clear_policy():
    es.clear_runtime_policy()
    yield
    es.clear_runtime_policy()


@pytest.mark.asyncio
async def test_refresh_runtime_policy_from_registry():
    now = datetime.now(timezone.utc)
    lights = [
        RegisteredLight(
            id="1",
            name="Fita Led",
            eye_safety_limit_pct=15,
            enabled_for_app=True,
            created_at=now,
            updated_at=now,
        ),
        RegisteredLight(
            id="2",
            name="Hue Play 1",
            eye_safety_limit_pct=None,
            enabled_for_app=False,
            created_at=now,
            updated_at=now,
        ),
    ]
    repo = AsyncMock()
    repo.list_all = AsyncMock(return_value=lights)
    svc = LightRegistryService(repo)
    await svc.refresh_runtime_policy()
    assert es.eye_safety_limit_pct("Fita Led") == 15
    assert es.is_enabled_for_app("Hue Play 1") is False
    assert es.is_enabled_for_app("Fita Led") is True
```

**Step 2: Run to verify fail**
```bash
uv run pytest tests/test_light_registry_policy_refresh.py -v --no-cov
```
Expected: `AttributeError: ... refresh_runtime_policy`

**Step 3: Implement**

Add to `LightRegistryService` in `marvin_hue/services/light_registry.py`:
```python
    async def refresh_runtime_policy(self) -> None:
        """Push active registry eye limits + disabled names into eye_safety cache."""
        from marvin_hue.eye_safety import set_runtime_policy

        lights = await self._repo.list_all(include_deleted=False)
        limits: dict[str, int | None] = {}
        disabled: set[str] = set()
        for light in lights:
            limits[light.name] = light.eye_safety_limit_pct
            if not light.enabled_for_app:
                disabled.add(light.name)
        set_runtime_policy(limits_pct=limits, disabled_names=disabled)
```

Also call `await self.refresh_runtime_policy()` at the end of `create_light`, `update_light`, `soft_delete` (or whatever delete method is named), and `refresh_and_sync` / sync method — after successful mutations. Read the existing method names in the file and hook each public mutator.

**Step 4: Verify**
```bash
uv run pytest tests/test_light_registry_policy_refresh.py tests/test_light_registry_service.py -v --no-cov
```
Expected: PASSED

**Step 5: Commit** via `jarvis-default-commit`.

**If Task Fails:**
1. Method name for sync differs → grep `async def` in `light_registry.py` and hook those
2. Soft-deleted lights still in policy → ensure `include_deleted=False`

---

### Task A3: HueController skips disabled lights

**Files:**
- Modify: `marvin_hue/controllers.py`
- Test: `tests/test_controller_enabled_for_app.py` (create)

**Prerequisites:** Task A1

**Step 1: Failing tests**
```python
# tests/test_controller_enabled_for_app.py
from unittest.mock import MagicMock

from marvin_hue import eye_safety as es
from marvin_hue.basics import LightConfig, LightSetting
from marvin_hue.colors import Color
from marvin_hue.controllers import HueController


def _make_controller():
    c = HueController.__new__(HueController)
    play = MagicMock()
    play.name = "Hue Play 1"
    play.brightness = 0
    c.lights = [play]
    c._light_cache = {play.name: play}
    return c, play


def setup_function():
    es.clear_runtime_policy()


def teardown_function():
    es.clear_runtime_policy()


def test_set_light_color_skips_disabled():
    c, play = _make_controller()
    es.set_runtime_policy(limits_pct={}, disabled_names={"Hue Play 1"})
    with __import__("pytest").raises(ValueError, match="desabilitada"):
        c.set_light_color("Hue Play 1", Color(255, 0, 0, 200))
    assert play.brightness == 0


def test_apply_config_skips_disabled_without_raising():
    c, play = _make_controller()
    es.set_runtime_policy(limits_pct={}, disabled_names={"Hue Play 1"})
    cfg = LightConfig(
        name="x",
        settings=[LightSetting("Hue Play 1", Color(1, 2, 3, 200))],
        description="d",
    )
    c.apply_light_config(cfg)
    assert play.brightness == 0


def test_set_brightness_skips_disabled():
    c, play = _make_controller()
    es.set_runtime_policy(limits_pct={}, disabled_names={"Hue Play 1"})
    assert c.set_brightness("Hue Play 1", 200) is False
```

**Step 2: Run fail**
```bash
uv run pytest tests/test_controller_enabled_for_app.py -v --no-cov
```

**Step 3: Implement**

In `marvin_hue/controllers.py`:
- Import `is_enabled_for_app` from `marvin_hue.eye_safety`
- At start of `set_light_color`, after name lookup success:
  ```python
  if not is_enabled_for_app(light_name):
      raise ValueError(f"Lâmpada '{light_name}' desabilitada no app (enabled_for_app=false)")
  ```
- In `apply_light_config` loop, skip settings where `not is_enabled_for_app(setting.light_name)` (log debug/warning)
- In `set_brightness` / `turn_on` / `turn_off`: return False if disabled
- In `set_all` / `set_all_brightness`: only touch lights where `is_enabled_for_app(light.name)`

**Step 4: Verify**
```bash
uv run pytest tests/test_controller_enabled_for_app.py tests/test_controller_eye_safety.py tests/test_controllers.py -v --no-cov
```

**Step 5: Commit**

---

### Task A4: ScreenMirror respects enabled_for_app

**Files:**
- Modify: `marvin_hue/screen_mirror.py` (`load_light_positions` or loop that applies colors)
- Test: `tests/test_screen_mirror_enabled.py` (create)

**Prerequisites:** Task A1

**Step 1: Failing test**
```python
# tests/test_screen_mirror_enabled.py
import json
from pathlib import Path
from unittest.mock import MagicMock

from marvin_hue import eye_safety as es
from marvin_hue.screen_mirror import ScreenMirror


def test_load_positions_filters_disabled(tmp_path: Path):
    es.clear_runtime_policy()
    es.set_runtime_policy(limits_pct={}, disabled_names={"Hue Play 1"})
    path = tmp_path / "pos.json"
    path.write_text(
        json.dumps(
            {
                "lights": [
                    {"name": "Hue Play 1", "position": "left", "enabled": True},
                    {"name": "Hue Play 2", "position": "right", "enabled": True},
                ]
            }
        ),
        encoding="utf-8",
    )
    mirror = ScreenMirror(MagicMock(), str(path))
    lights = mirror.load_light_positions()
    names = {x["name"] for x in lights}
    assert "Hue Play 1" not in names
    assert "Hue Play 2" in names
    es.clear_runtime_policy()
```

**Step 2–4:** Filter in `load_light_positions` after JSON load:
```python
from marvin_hue.eye_safety import is_enabled_for_app
# ...
if light.get("enabled") and light.get("position") != "none" and is_enabled_for_app(light["name"]):
```

```bash
uv run pytest tests/test_screen_mirror_enabled.py -v --no-cov
```

**Step 5: Commit**

---

### Task A5: Lifespan loads policy on startup

**Files:**
- Modify: `app.py` (after light registry init)
- Test: manual smoke + optional unit not required if service tests cover refresh

**Step 1–3:** After `dependencies.set_light_registry_service(light_registry)`:
```python
await light_registry.refresh_runtime_policy()
logger.info("Eye-safety / enabled_for_app policy loaded from registry")
```

On shutdown, optional: `from marvin_hue.eye_safety import clear_runtime_policy; clear_runtime_policy()`.

**Step 4:**
```bash
uv run pytest tests/test_light_registry_policy_refresh.py tests/test_eye_safety_runtime.py -q --no-cov
```

**Step 5: Commit**

---

### Task A6: Code Review (Phase A)

1. **REQUIRED SUB-SKILL:** Use jarvis-default-codereview — dispatch all reviewers in parallel
2. Handle findings by severity
3. Proceed only when zero Critical/High/Medium remain

---

## Phase B — Optional API_KEY middleware

### Task B1: Middleware module + unit tests

**Files:**
- Create: `marvin_hue/api/middleware/__init__.py`
- Create: `marvin_hue/api/middleware/api_key.py`
- Test: `tests/test_api_key_middleware.py`

**Prerequisites:** none (can start after A if same agent; independent of A for code)

**Design:**
- If `settings.api_key` is `None` or `""` → middleware is no-op (all requests pass)
- If set → require header `X-API-Key: <key>` **or** `Authorization: Bearer <key>` for paths starting with `/api/`
- **Exempt always:** `/docs`, `/openapi.json`, `/redoc`, `/static/*`, HTML pages (`/`, `/mirror`, `/lights`, `/chat`, `/positions-config`, future HTML)
- **Protect:** `/api/*`, `/apply`, `/configurations`, `/mirror/start`, `/mirror/stop`, `/mirror/status`, `/mirror/settings`, `/positions` (JSON APIs). Practical rule: protect if path starts with `/api/` **OR** path is in a small set of non-`/api` JSON endpoints used by the UI with fetch.

**Better UX for local UI when key is set:** document that the browser UI must send the key (store in `sessionStorage` via a small prompt) OR keep HTML free and only lock machine-to-machine `/api/*`. **Decision for this plan (YAGNI + local UI):** protect only paths starting with `/api/`. Leave page routes and existing non-`/api` JSON (`/apply`, `/configurations`, `/mirror/*`, `/positions`) unprotected unless moved later. Document that LAN UI remains usable; remote clients using `/api/*` need the key.

**Step 1: Tests**
```python
# tests/test_api_key_middleware.py
from fastapi import FastAPI
from fastapi.testclient import TestClient

from marvin_hue.api.middleware.api_key import ApiKeyMiddleware


def _app(key: str | None):
    app = FastAPI()
    app.add_middleware(ApiKeyMiddleware, api_key=key)

    @app.get("/api/secret")
    def secret():
        return {"ok": True}

    @app.get("/")
    def index():
        return {"page": True}

    return app


def test_no_key_configured_allows_all():
    client = TestClient(_app(None))
    assert client.get("/api/secret").status_code == 200
    client = TestClient(_app(""))
    assert client.get("/api/secret").status_code == 200


def test_key_required_for_api():
    client = TestClient(_app("s3cret"))
    assert client.get("/api/secret").status_code == 401
    assert client.get("/api/secret", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/api/secret", headers={"X-API-Key": "s3cret"}).status_code == 200
    assert client.get(
        "/api/secret", headers={"Authorization": "Bearer s3cret"}
    ).status_code == 200


def test_html_routes_open_when_key_set():
    client = TestClient(_app("s3cret"))
    assert client.get("/").status_code == 200
```

**Step 2:** fail → implement

**Step 3: Implementation**
```python
# marvin_hue/api/middleware/__init__.py
from marvin_hue.api.middleware.api_key import ApiKeyMiddleware

__all__ = ["ApiKeyMiddleware"]
```

```python
# marvin_hue/api/middleware/api_key.py
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class ApiKeyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, api_key: str | None = None) -> None:
        super().__init__(app)
        self._api_key = (api_key or "").strip() or None

    async def dispatch(self, request: Request, call_next) -> Response:
        if self._api_key is None:
            return await call_next(request)
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)
        provided = request.headers.get("X-API-Key")
        if not provided:
            auth = request.headers.get("Authorization", "")
            if auth.lower().startswith("bearer "):
                provided = auth[7:].strip()
        if provided != self._api_key:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
            )
        return await call_next(request)
```

**Step 4:**
```bash
uv run pytest tests/test_api_key_middleware.py -v --no-cov
```

**Step 5: Commit**

---

### Task B2: Wire middleware in app.py + docs

**Files:**
- Modify: `app.py` (add middleware after CORS; note order: last added = outermost)
- Modify: `docs/CONFIGURATION.md` and/or `docs/API.md` — short section on `API_KEY` / `api_key`
- Modify: `.env.example` if present (add `# API_KEY=` commented)

**Implementation snippet for `app.py`:**
```python
from marvin_hue.api.middleware.api_key import ApiKeyMiddleware

# After CORSMiddleware:
app.add_middleware(ApiKeyMiddleware, api_key=settings.api_key)
```

Document:
- Empty/unset `API_KEY` → no auth
- Set `API_KEY=...` → clients must send `X-API-Key` for `/api/*`
- HTML UI pages remain open on LAN

**Verify:**
```bash
uv run pytest tests/test_api_key_middleware.py tests/test_api.py -q --no-cov
```

**Commit**

---

### Task B3: Code Review (Phase B)

jarvis-default-codereview; fix Critical/High/Medium.

---

## Phase C — Light groups (room/name groups)

### Task C1: Schema migration v2 — groups tables

**Files:**
- Modify: `marvin_hue/persistence/schema.py`
- Test: `tests/test_persistence_schema.py` (extend) or `tests/test_schema_groups.py`

**SQL (migration 2):**
```sql
CREATE TABLE IF NOT EXISTS light_groups (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    room TEXT,
    notes TEXT,
    deleted_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_light_groups_name_active
    ON light_groups(name) WHERE deleted_at IS NULL;
CREATE TABLE IF NOT EXISTS light_group_members (
    group_id TEXT NOT NULL,
    light_id TEXT NOT NULL,
    PRIMARY KEY (group_id, light_id),
    FOREIGN KEY (group_id) REFERENCES light_groups(id),
    FOREIGN KEY (light_id) REFERENCES lights(id)
);
CREATE INDEX IF NOT EXISTS idx_group_members_light ON light_group_members(light_id);
```

Set `CURRENT_SCHEMA_VERSION = 2` and add `_MIGRATIONS[2] = [...]`.

**Test:** open temp DB via `init_db`, assert tables exist and version=2.

```bash
uv run pytest tests/test_persistence_schema.py tests/test_schema_groups.py -v --no-cov
```

**Commit**

---

### Task C2: Domain + repository for groups

**Files:**
- Create: `marvin_hue/domain/groups.py`
- Create: `marvin_hue/persistence/group_repository.py`
- Test: `tests/test_group_repository.py`

**Domain:**
```python
# marvin_hue/domain/groups.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

class GroupValidationError(ValueError): ...
class GroupConflictError(GroupValidationError): ...
class GroupNotFoundError(LookupError): ...

@dataclass
class LightGroup:
    id: str
    name: str
    room: Optional[str] = None
    notes: Optional[str] = None
    light_ids: list[str] = field(default_factory=list)
    deleted_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        name = (self.name or "").strip()
        if not name:
            raise GroupValidationError("name must be non-empty")
        self.name = name
```

**Repository Protocol + Sqlite implementation** (mirror `light_repository.py` patterns: shared conn + lock if co-located; prefer **reusing the same aiosqlite connection** from light repo or open second connection on same file with WAL — YAGNI: new `SqliteGroupRepository.open(db_path)` own connection + lock, like lights).

Methods: `list_all`, `get_by_id`, `create`, `update`, `soft_delete`, `set_members(group_id, light_ids: list[str])`, `list_member_light_names(group_id) -> list[str]` (join lights.name).

**Tests:** CRUD on temp file DB after `init_db`.

**Commit**

---

### Task C3: Group service (CRUD + apply on/off/config)

**Files:**
- Create: `marvin_hue/services/group_service.py`
- Test: `tests/test_group_service.py`

**Service responsibilities:**
- CRUD validation
- `apply_config(group_id, config: LightConfig, hue: HueController)` — apply only member light names present in config settings **or** filter config settings to members
- `set_power(group_id, on: bool, hue)` — turn_on/off each member name
- Resolve member **names** via join (registry light id → name)

Apply algorithm:
```python
names = await self._repo.list_member_light_names(group_id)
for name in names:
    if on:
        hue.turn_on(name)
    else:
        hue.turn_off(name)
```
For config: filter `LightConfig.settings` to those with `light_name in names`, then `hue.apply_light_config(filtered)` OR apply full config then re-off non-members — **prefer filter** (YAGNI).

**Commit**

---

### Task C4: API routes + models for groups

**Files:**
- Modify: `marvin_hue/api/models.py` (add Group* models)
- Create: `marvin_hue/api/routes/groups.py`
- Modify: `marvin_hue/api/dependencies.py` (set/get group service)
- Modify: `app.py` (init repo/service, include router)
- Test: `tests/test_api_groups.py`

**API surface:**
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/groups` | List groups |
| POST | `/api/groups` | Create `{name, room?, notes?, light_ids?}` |
| GET | `/api/groups/{group_id}` | Detail + members |
| PATCH | `/api/groups/{group_id}` | Update metadata / replace `light_ids` |
| DELETE | `/api/groups/{group_id}` | Soft-delete |
| POST | `/api/groups/{group_id}/apply` | `{config_name, transition_time_secs?}` |
| POST | `/api/groups/{group_id}/power` | `{on: bool}` |

Wire DI similar to lights. Lifespan: open `SqliteGroupRepository` on same `settings.app_db_path`.

**Commit**

---

### Task C5: Groups UI page

**Files:**
- Create: `web/templates/groups.html`
- Create: `web/static/groups.js`
- Modify: `marvin_hue/api/routes/groups.py` — `GET /groups` HTML
- Mirror style of `lights.html` (Bootstrap, breadcrumb)

**UI minimum:**
- List groups with room badge
- Create form (name, room, multi-select lights from `GET /api/lights`)
- Buttons: Ligar / Desligar / Aplicar config (dropdown of `/configurations`)
- Delete

**Commit**

---

### Task C6: Code Review (Phase C)

---

## Phase D — Scene history + undo

### Task D1: Schema v3 — scene_snapshots

**Files:**
- Modify: `marvin_hue/persistence/schema.py` → version 3
- Test: schema test extension

```sql
CREATE TABLE IF NOT EXISTS scene_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT,
    source TEXT NOT NULL,  -- 'apply' | 'mirror_stop' | 'manual' | 'group_apply'
    payload_json TEXT NOT NULL,  -- list of light status dicts
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scene_snapshots_created ON scene_snapshots(created_at DESC);
```

Keep max history in service (e.g. 30); prune older rows on insert.

**Commit**

---

### Task D2: SceneHistoryService

**Files:**
- Create: `marvin_hue/services/scene_history.py`
- Create: `marvin_hue/persistence/scene_repository.py`
- Test: `tests/test_scene_history.py`

**Methods:**
- `async def snapshot(hue: HueController, *, label: str | None, source: str) -> int` — call `hue.get_lights_status()`, store JSON
- `async def restore_last(hue: HueController) -> dict` — load newest, for each light set on/off + color/brightness via public API
- `async def list_recent(limit: int = 10) -> list[dict]`

**Restore mapping** (use public controller API only):
```python
for item in payload:
    name = item["name"]
    if not item.get("on"):
        hue.turn_off(name)
        continue
    hue.turn_on(name)
    color = item.get("color") or {}
    bri = int(item.get("brightness") or 0)
    hue.set_light_color(name, Color(color.get("r", 0), color.get("g", 0), color.get("b", 0), bri))
```

**Commit**

---

### Task D3: Hook snapshot before apply / mirror stop + API

**Files:**
- Modify: `marvin_hue/api/routes/configurations.py` — before apply, `await scene_history.snapshot(...)`
- Modify: `marvin_hue/api/routes/mirror.py` — on stop, snapshot then stop (or snapshot at start of stop)
- Modify: group apply route (Phase C) similarly
- Create: `marvin_hue/api/routes/history.py`
- Modify: `app.py`, `dependencies.py`
- Test: `tests/test_api_history.py`

**API:**
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/history` | Recent snapshots metadata |
| POST | `/api/history/undo` | Restore last snapshot |
| POST | `/api/history/snapshot` | Manual snapshot |

**Commit**

---

### Task D4: Undo button on main UI

**Files:**
- Modify: `web/templates/index.html` — button "Desfazer última cena"
- Modify: `web/static/index.js` — `POST /api/history/undo`

**Commit**

---

### Task D5: Code Review (Phase D)

---

## Phase E — Schedules

### Task E1: Schema v4 — schedules

**Files:**
- Modify: `marvin_hue/persistence/schema.py` → `CURRENT_SCHEMA_VERSION = 4`

```sql
CREATE TABLE IF NOT EXISTS schedules (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    -- Local wall-clock time (device TZ): HH:MM 24h
    time_hhmm TEXT NOT NULL,
    -- CSV of weekdays 0=Mon..6=Sun; empty = every day
    days_of_week TEXT NOT NULL DEFAULT '',
    action_type TEXT NOT NULL,  -- 'apply_config' | 'power_on' | 'power_off'
    action_payload_json TEXT NOT NULL DEFAULT '{}',  -- e.g. {"config_name":"...","group_id":null}
    last_run_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

**No external cron library** (YAGNI). Match: current local time `HH:MM` equals `time_hhmm` and weekday allowed; fire at most once per minute per schedule (`last_run_at` date+minute guard).

**Commit**

---

### Task E2: Schedule repository + service + runner

**Files:**
- Create: `marvin_hue/domain/schedules.py`
- Create: `marvin_hue/persistence/schedule_repository.py`
- Create: `marvin_hue/services/schedule_service.py`
- Create: `marvin_hue/services/schedule_runner.py`
- Test: `tests/test_schedule_service.py`, `tests/test_schedule_runner.py`

**Runner:**
```python
# schedule_runner.py
class ScheduleRunner:
    def __init__(self, service: ScheduleService, hue, manager, poll_seconds: float = 15.0):
        self._service = service
        ...
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            ...

    async def _loop(self) -> None:
        while True:
            try:
                await self._service.tick(datetime.now().astimezone())
            except Exception:
                logger.exception("schedule tick failed")
            await asyncio.sleep(self._poll_seconds)
```

`tick` loads enabled schedules, for each matching time+day executes action via `HueController` + `LightSetupsManager` (and optional group service).

**Unit-test `tick` with frozen datetime** and mock hue/manager.

**Commit**

---

### Task E3: Schedules API + UI

**Files:**
- Create: `marvin_hue/api/routes/schedules.py`
- Create: `web/templates/schedules.html`
- Create: `web/static/schedules.js`
- Modify: models, dependencies, app.py lifespan start/stop runner
- Test: `tests/test_api_schedules.py`

**API:**
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/schedules` | List |
| POST | `/api/schedules` | Create |
| PATCH | `/api/schedules/{id}` | Update / enable |
| DELETE | `/api/schedules/{id}` | Delete (hard OK for schedules) |
| POST | `/api/schedules/{id}/run` | Manual run now |

**Lifespan:**
```python
runner = ScheduleRunner(...)
dependencies.set_schedule_runner(runner)
await runner.start()
# shutdown:
await runner.stop()
```

**Commit**

---

### Task E4: Code Review (Phase E)

---

## Phase F — Mirror improvements (profiles + UI)

### Task F1: Mirror profiles constants + apply_profile

**Files:**
- Modify: `marvin_hue/screen_mirror.py`
- Modify: `marvin_hue/api/models.py` (`MirrorStartRequest.profile`, `MirrorSettingsRequest.profile`)
- Modify: `marvin_hue/api/routes/mirror.py`
- Test: `tests/test_mirror_profiles.py`

**Profiles (exact dict):**
```python
MIRROR_PROFILES: dict[str, dict[str, float | int]] = {
    "cinema": {
        "fps": 12,
        "brightness": 160,
        "saturation_boost": 1.1,
        "smoothing_factor": 0.35,
        "transition_time": 2,
    },
    "fps": {  # games / fast motion
        "fps": 30,
        "brightness": 200,
        "saturation_boost": 1.4,
        "smoothing_factor": 0.7,
        "transition_time": 0,
    },
    "ambient": {
        "fps": 8,
        "brightness": 120,
        "saturation_boost": 1.0,
        "smoothing_factor": 0.25,
        "transition_time": 3,
    },
}
```

```python
def apply_profile(self, name: str) -> None:
    if name not in MIRROR_PROFILES:
        raise ValueError(f"Unknown profile: {name}")
    for k, v in MIRROR_PROFILES[name].items():
        setattr(self, k, v)
    self.active_profile = name
```

Extend `get_status()` to include `fps`, `smoothing_factor`, `saturation_boost`, `transition_time`, `active_profile`.

`start(..., profile: str | None = None)` applies profile before run if given.

**Per-light enabled:** already via positions JSON `enabled` + registry `enabled_for_app` from Phase A.

**Commit**

---

### Task F2: Mirror page UI controls

**Files:**
- Modify: `web/templates/mirror.html`
- Modify: `web/static/mirror.js`

**UI:**
- Profile select: Cinema / FPS / Ambiente
- Sliders already present for FPS/brightness if any — ensure smoothing + sat + transition visible
- On profile change → `POST /mirror/settings` with profile or discrete fields
- Start sends selected profile

**Commit**

---

### Task F3: Code Review (Phase F)

---

## Phase G — Chat tools: room + registry policy

### Task G1: build_light_tools accepts optional registry snapshot

**Files:**
- Modify: `marvin_hue/chat/tools/light_tools.py`
- Modify: `marvin_hue/chat/agents/react_agent.py` (and `subagents/definitions.py` if it rebuilds tools)
- Test: `tests/chat/test_light_tools_room.py`

**Design (keep tools sync):**
```python
def build_light_tools(
    controller: HueController,
    manager: LightSetupsManager,
    locations_path: str = _DEFAULT_LOCATIONS_PATH,
    *,
    room_index: dict[str, list[str]] | None = None,
) -> list[BaseTool]:
```

`room_index` maps room label → light names (from registry at agent build time). Refresh on chat reconfigure if easy; else build once at lifespan (document limitation: room changes need agent rebuild — optional hook later).

**New tools:**
1. `list_lights_by_room(room: str = "")` — if room empty, list rooms and counts; else list names in room (filter disabled)
2. `set_room_power(room: str, on: bool)` — turn_on/off each enabled light in room
3. `set_room_brightness(room: str, brightness: int)` — pct 0–100, clamp via controller

**Filter `list_lights` / status tools** to exclude disabled lights (or mark them). Prefer exclude from "available" list.

**Update tool count** in docstring and any characterization tests that assert exact tool count (grep `10 tools` / `len(tools)`).

**Commit**

---

### Task G2: Load room_index in create_hue_agent / lifespan

**Files:**
- Modify: `marvin_hue/chat/agents/react_agent.py` — `create_hue_agent(..., room_index=None)`
- Modify: `app.py` — after registry ready, build room map:
```python
lights = await light_registry.list_lights()
room_index: dict[str, list[str]] = {}
for lt in lights:
    if not lt.enabled_for_app:
        continue
    room = (lt.room or "").strip() or "sem_sala"
    room_index.setdefault(room, []).append(lt.name)
chat_agent = create_hue_agent(..., room_index=room_index)
```
- Chat eye middleware already uses `eye_safety_limit_pct` / `clamp_eye_safety` if Task A1 rewired lookups — update middleware to use `eye_safety_limit_pct(light)` instead of `EYE_SAFETY_LIMITS.get(light)`:

```python
# marvin_hue/chat/middleware/eye_safety.py
from marvin_hue.eye_safety import eye_safety_limit_pct, clamp_eye_safety
# ...
if not isinstance(light, str) or eye_safety_limit_pct(light) is None or field not in args:
```

**Tests:** update `tests/chat/test_eye_safety_middleware.py` if needed; add room tool tests.

```bash
uv run pytest tests/chat/ -q --no-cov
```

**Commit**

---

### Task G3: Code Review (Phase G)

---

## Phase H — Import / export bundle

### Task H1: Bundle service (JSON + ZIP)

**Files:**
- Create: `marvin_hue/services/bundle_io.py`
- Test: `tests/test_bundle_io.py`

**Export contents (ZIP preferred):**
```
manifest.json          # version, exported_at, app_version
lights.json            # registry rows (active)
groups.json            # groups + members
schedules.json         # schedules
setups.json            # copy of settings.setups_file
light_positions.json   # copy of settings.positions_file
```

**Import:**
- Validate manifest version
- Upsert lights/groups/schedules via services (or replace strategy: **merge by name/id**, document choice)
- Write setups/positions files to configured paths (backup `.bak` first)
- Call `refresh_runtime_policy()` after lights import

**Decision:** merge-by-id for lights/groups; schedules replace by id; files overwrite after `.bak`.

**Commit**

---

### Task H2: API + simple UI controls

**Files:**
- Create: `marvin_hue/api/routes/bundle.py`
- Optional: section on `web/templates/lights.html` or new `web/templates/backup.html`
- Test: `tests/test_api_bundle.py` (temp ZIP roundtrip with TestClient + tmp DB)

**API:**
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/export` | Download ZIP |
| POST | `/api/import` | Upload ZIP (`multipart/form-data`) |

Use `StreamingResponse` / `FileResponse` for export.

Protect under `/api/` so API key applies when set.

**Commit**

---

### Task H3: Code Review (Phase H)

---

## Phase I — Health dashboard + unified nav

### Task I1: Health aggregation API

**Files:**
- Create: `marvin_hue/services/health.py` (optional thin helper)
- Create or modify: `marvin_hue/api/routes/health.py`
- Test: `tests/test_api_health.py`

**GET `/api/health` response shape:**
```json
{
  "bridge": {"connected": true, "bridge_ip": "...", "light_count": 9},
  "lights": {"total": 9, "unreachable": 1, "disabled_in_app": 0},
  "mirror": {"running": false, "fps": 10, "profile": null},
  "chat": {"available": true, "reason": null},
  "registry": {"db_path": ".res/marvin_hue.sqlite", "last_sync_at": null},
  "schedules": {"enabled_count": 0, "runner_alive": true}
}
```

Sources:
- Bridge: same as `bridge_status`
- Unreachable: count from `hue.get_lights_status()` where `reachable is False`
- Mirror: `screen_mirror.get_status()`
- Chat: `get_chat_agent() is not None` + `get_chat_unavailable_reason()`
- last_sync: store timestamp on `LightRegistryService.refresh_and_sync` success (add `last_sync_at` attr)

**Also:** `GET /health` HTML page.

**Commit**

---

### Task I2: Shared nav partial

**Files:**
- Create: `web/templates/partials/nav.html`
- Modify: `web/templates/index.html`, `lights.html`, `mirror.html`, `positions.html`, `chat.html`, plus new pages (`groups.html`, `schedules.html`, `health.html`)

**Partial content (Jinja):**
```html
{# web/templates/partials/nav.html #}
{# expects optional `active` in context: controle|chat|lampadas|grupos|posicoes|espelhamento|agendamentos|saude #}
<nav aria-label="breadcrumb" class="mb-3">
  <ol class="breadcrumb">
    <li class="breadcrumb-item {% if active == 'controle' %}active{% endif %}">
      {% if active != 'controle' %}<a href="/">Controle</a>{% else %}Controle{% endif %}
    </li>
    <li class="breadcrumb-item {% if active == 'chat' %}active{% endif %}">
      {% if active != 'chat' %}<a href="/chat">Chat</a>{% else %}Chat{% endif %}
    </li>
    <li class="breadcrumb-item {% if active == 'lampadas' %}active{% endif %}">
      {% if active != 'lampadas' %}<a href="/lights">Lâmpadas</a>{% else %}Lâmpadas{% endif %}
    </li>
    <li class="breadcrumb-item {% if active == 'grupos' %}active{% endif %}">
      {% if active != 'grupos' %}<a href="/groups">Grupos</a>{% else %}Grupos{% endif %}
    </li>
    <li class="breadcrumb-item {% if active == 'posicoes' %}active{% endif %}">
      {% if active != 'posicoes' %}<a href="/positions-config">Posicionamento</a>{% else %}Posicionamento{% endif %}
    </li>
    <li class="breadcrumb-item {% if active == 'espelhamento' %}active{% endif %}">
      {% if active != 'espelhamento' %}<a href="/mirror">Espelhamento</a>{% else %}Espelhamento{% endif %}
    </li>
    <li class="breadcrumb-item {% if active == 'agendamentos' %}active{% endif %}">
      {% if active != 'agendamentos' %}<a href="/schedules">Agendamentos</a>{% else %}Agendamentos{% endif %}
    </li>
    <li class="breadcrumb-item {% if active == 'saude' %}active{% endif %}">
      {% if active != 'saude' %}<a href="/health">Saúde</a>{% else %}Saúde{% endif %}
    </li>
  </ol>
</nav>
```

Each page: `{% include "partials/nav.html" %}` with `TemplateResponse(..., {"active": "lampadas"})`.

For `app.py` index route and route modules that render templates, pass `active=`.

**Commit**

---

### Task I3: Health HTML page

**Files:**
- Create: `web/templates/health.html`
- Create: `web/static/health.js` (poll `/api/health` every 5s)
- Wire `GET /health` in `health.py` router

**Commit**

---

### Task I4: Final integration tests + docs

**Files:**
- Modify: `docs/API.md` — document new endpoints
- Modify: `docs/ARCHITECTURE.md` — brief note on runtime policy + new modules
- Modify: `CHANGELOG.md` if project maintains it
- Test: `tests/test_api_health.py` + full smoke:

```bash
uv run pytest tests/ -q --no-cov -x
# Expected: all PASSED (or only pre-existing failures documented)
```

**Commit**

---

### Task I5: Final Code Review (Phase I + cross-cutting)

jarvis-default-codereview on all new modules; fix Critical/High/Medium.

---

## Dependency graph (task IDs)

| Task | Depends on | Parallel with |
|------|------------|---------------|
| A1–A6 | — | — (foundation) |
| B1–B3 | — (soft: after A if single agent) | C, D start after A |
| C1–C6 | A5 (lifespan pattern) | D, E, F, G |
| D1–D5 | A3 (controller status) | C, E, F, G |
| E1–E4 | A3 | C, D, F, G |
| F1–F3 | A4 | C, D, E, G |
| G1–G3 | A1, A5 | C, D, E, F |
| H1–H3 | C4 (groups export), registry | after C (schedules optional) |
| I1–I5 | B, C, D, E, F APIs ideally | last |

---

## File checklist (created by end of plan)

```
marvin_hue/api/middleware/__init__.py
marvin_hue/api/middleware/api_key.py
marvin_hue/api/routes/groups.py
marvin_hue/api/routes/history.py
marvin_hue/api/routes/schedules.py
marvin_hue/api/routes/bundle.py
marvin_hue/api/routes/health.py
marvin_hue/domain/groups.py
marvin_hue/domain/schedules.py
marvin_hue/persistence/group_repository.py
marvin_hue/persistence/scene_repository.py
marvin_hue/persistence/schedule_repository.py
marvin_hue/services/group_service.py
marvin_hue/services/scene_history.py
marvin_hue/services/schedule_service.py
marvin_hue/services/schedule_runner.py
marvin_hue/services/bundle_io.py
marvin_hue/services/health.py          # optional
web/templates/partials/nav.html
web/templates/groups.html
web/templates/schedules.html
web/templates/health.html
web/static/groups.js
web/static/schedules.js
web/static/health.js
tests/test_eye_safety_runtime.py
tests/test_light_registry_policy_refresh.py
tests/test_controller_enabled_for_app.py
tests/test_screen_mirror_enabled.py
tests/test_api_key_middleware.py
tests/test_group_repository.py
tests/test_group_service.py
tests/test_api_groups.py
tests/test_scene_history.py
tests/test_api_history.py
tests/test_schedule_service.py
tests/test_schedule_runner.py
tests/test_api_schedules.py
tests/test_mirror_profiles.py
tests/chat/test_light_tools_room.py
tests/test_bundle_io.py
tests/test_api_bundle.py
tests/test_api_health.py
```

**Modified (expected):**
```
marvin_hue/eye_safety.py
marvin_hue/controllers.py
marvin_hue/screen_mirror.py
marvin_hue/services/light_registry.py
marvin_hue/persistence/schema.py
marvin_hue/api/dependencies.py
marvin_hue/api/models.py
marvin_hue/api/routes/configurations.py
marvin_hue/api/routes/mirror.py
marvin_hue/chat/tools/light_tools.py
marvin_hue/chat/middleware/eye_safety.py
marvin_hue/chat/agents/react_agent.py
marvin_hue/chat/subagents/definitions.py
app.py
web/templates/*.html (nav include)
docs/API.md
docs/CONFIGURATION.md
docs/ARCHITECTURE.md
```

---

## Success criteria (acceptance)

1. Registry `eye_safety_limit_pct` and `enabled_for_app` affect controller, mirror, and chat without restart after mutation (refresh on write + startup).
2. With empty `API_KEY`, all routes work as today; with key set, `/api/*` returns 401 without header; HTML pages still load.
3. Groups CRUD + apply config / power works via API and `/groups` UI.
4. After apply config, Undo restores previous brightness/on/color snapshot.
5. Enabled schedule fires within ~poll interval of local `HH:MM` on allowed weekdays.
6. Mirror profiles cinema/fps/ambient change FPS/smoothing/etc.; UI can select them.
7. Chat can list/control by room and ignores disabled lights; eye safety uses registry limits.
8. Export ZIP re-imports on clean DB recovering lights/groups (+ files).
9. `/health` shows bridge, unreachable count, mirror, chat, last sync.
10. All pages share the same nav links (Controle, Chat, Lâmpadas, Grupos, Posicionamento, Espelhamento, Agendamentos, Saúde).
11. `uv run pytest tests/ -q --no-cov` green for new + existing related suites.
12. Still aiosqlite only; no Postgres/Alembic.

---

## Risk notes for implementers

- **Do not** import `services` or `chat` from `controllers.py` / `eye_safety.py` (dependency direction).
- **Schema:** always bump `CURRENT_SCHEMA_VERSION` and add migration; never edit applied v1 SQL in place for existing installs.
- **Tests:** use temp SQLite paths; never point tests at `.res/marvin_hue.sqlite`.
- **phue I/O:** keep bridge calls off the event loop via `run_in_executor` in routes (existing pattern).
- **Schedule double-fire:** guard with `last_run_at` minute key.
- **API key vs UI:** only `/api/*` is protected; non-`/api` JSON endpoints remain open by design for local UI—document this explicitly.

---

## Suggested agent batches

| Batch | Tasks | Agent focus |
|-------|-------|-------------|
| 1 | A1–A6 | Runtime policy wiring |
| 2 | B1–B3 | API key middleware |
| 3a | C1–C6 | Groups |
| 3b | D1–D5 | Scene undo |
| 3c | E1–E4 | Schedules |
| 3d | F1–F3 | Mirror profiles |
| 3e | G1–G3 | Chat room tools |
| 4 | H1–H3 | Import/export (after C) |
| 5 | I1–I5 | Health + nav + docs |

Batches 3a–3e may run as parallel subagents after Batch 1 completes.
