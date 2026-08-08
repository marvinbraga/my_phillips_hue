# SQLite Lights Registry CRUD Implementation Plan

> **For Agents:** Implement this plan task-by-task following the structure below; review between tasks via jarvis-default-codereview.

**Goal:** Add an app-owned SQLite catalog for lamp/light registration (CRUD + soft-delete + optional bridge sync), separate from Hue live state and from the LangGraph chat checkpointer DB.

**Architecture:** Introduce a thin ports-and-adapters slice: domain entity + repository Protocol, SQLite adapter with versioned schema init (no Alembic), service for CRUD/sync, and a new FastAPI router under `/api/lights` that does **not** replace existing live-status endpoints (`GET /api/lights/status` stays as-is). Bridge (via `HueController`) remains source of truth for physical devices; SQLite owns app metadata (nickname, room, notes, eye-safety limit, enabled-for-app, optional bridge id, soft-delete). Sync identity prefers stable `bridge_light_id` (phue `uniqueid` when available, else `light_id`), with name as fallback. Soft-delete is safe-by-default: sync never auto-reactivates deleted rows unless `reactivate_deleted=true`. Shared aiosqlite connection is serialized with `asyncio.Lock`. v1 does **not** migrate `setups.json` or `light_positions.json`.

**Tech Stack:**
- Python 3.10+ (project requires `>=3.10`; tests run under 3.12/3.13)
- FastAPI + uvicorn (existing)
- **aiosqlite** `>=0.20.0` as **direct** dependency (already transitive via `langgraph-checkpoint-sqlite` / lock has `0.22.1`)
- **No SQLAlchemy / Alembic** in v1 — single-table personal app; maintainable schema via `schema_version` + ordered migrations
- pytest + pytest-asyncio + httpx (existing dev deps)
- pydantic v2 + pydantic-settings (existing)

**Migration strategy (justification):** One catalog table + soft-delete. Alembic would be ceremony for a single personal SQLite file. Use `init_db(path)` that opens aiosqlite, creates `schema_version`, and applies numbered SQL migrations in order. When multi-table complexity appears later, Alembic can be introduced without rewriting the domain.

**Database path:** `.res/marvin_hue.sqlite` (setting `app_db_path` / env `APP_DB_PATH`). **Never** put lights tables in `.res/chat_memory.sqlite`. Settings must refuse `app_db_path` that resolves equal to `chat_checkpoint_db` or uses basename `chat_memory.sqlite`.

**Security (v1):** Same as the rest of the app — no API_KEY enforcement yet; assume LAN/trusted network. Optional follow-up: wire `settings.api_key` middleware for `/api/lights*`. Do not invent auth in this plan.

**API surface (v1):**
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/lights` | List registry (`?include_deleted=true` optional) |
| GET | `/api/lights/{light_id}` | Get one by UUID |
| POST | `/api/lights` | Create manual catalog entry |
| PATCH | `/api/lights/{light_id}` | Update metadata (`null` clears nullable fields) |
| DELETE | `/api/lights/{light_id}` | Soft-delete (catalog only; no Hue delete) |
| POST | `/api/lights/sync` | Upsert from bridge inventory (`?reactivate_deleted=false`) |

**Out of scope v1:** UI redesign, setups/positions migration, multi-user auth, Postgres, hard-delete on Hue bridge, changing `EYE_SAFETY_LIMITS` runtime source (store limit in DB for later; clamping still uses code map until a future task).

**Isolation note:** Working tree may have unrelated WIP (chat/api). Do **not** refactor chat, checkpointer, or positions JSON. New files only + minimal wiring in `config.py`, `dependencies.py`, `app.py`, `.gitignore`, docs, `pyproject.toml`.

## Validation amendments (2026-08-08)

Incorporated from plan validation so this document is **READY** (no open design forks):

1. **Sync identity:** match by `bridge_light_id` first (stable Hue `uniqueid` preferred over volatile `light_id`), then name; never raw unmapped IntegrityError 500.
2. **Soft-delete default:** sync does **not** auto-reactivate; optional `reactivate_deleted=true` on sync only.
3. **Lookups:** `get_by_name` / `get_by_bridge_light_id` always `ORDER BY deleted_at IS NULL DESC, updated_at DESC LIMIT 1`.
4. **PATCH:** uniform `_UNSET` sentinel for all optional update fields; route uses `model_dump(exclude_unset=True)`; explicit JSON `null` clears nullable fields.
5. **SQLite concurrency:** one long-lived connection + `asyncio.Lock`; optional `PRAGMA journal_mode=WAL` on init.
6. **Routes:** `status.router` before lights router; static paths (`/api/lights`, `/api/lights/sync`) before `/{light_id}`; regression tests for `/status` and `/sync`.
7. **DI/conftest:** single `asyncio.run` bootstrap recipe (no `get_event_loop` / no flaky anyio forks).
8. **Sync API:** only `refresh_and_sync(...)`; never `svc._bridge` from routes; bridge failure → 503 generic detail (no `str(exc)` leakage on 5xx).
9. **Duplicate active name:** HTTP **409 Conflict**.
10. **APP_DB_PATH:** normalize/validate; reject collision with chat DB and `chat_memory.sqlite` basename.

**Global Prerequisites:**
- Environment: Linux, Python 3.10+, project root `/run/media/marvinbraga/dados-linux/marvin/my_phillips_hue`
- Tools: `uv`, `git`, pytest via `uv run`
- Access: No Hue bridge required for unit/API tests (mock controller); real bridge only for manual smoke

**Verification before starting:**
```bash
cd /run/media/marvinbraga/dados-linux/marvin/my_phillips_hue
python --version   # Expected: Python 3.10+ (often 3.12 or 3.13)
uv --version       # Expected: uv 0.x
git status         # Expected: may show unrelated WIP — do not reset; only stage files from this plan
uv run pytest tests/test_config.py tests/test_api.py -q --no-cov  # Expected: existing tests pass (or only pre-existing failures)
```

**Package layout (new modules):**
```
marvin_hue/
  domain/
    __init__.py
    lights.py              # RegisteredLight entity + domain errors
  persistence/
    __init__.py
    schema.py              # versioned SQL migrations + init_db
    light_repository.py    # Protocol + SqliteLightRegistryRepository
  services/
    __init__.py
    light_registry.py      # LightRegistryService (CRUD + sync)
  api/
    routes/
      lights.py            # REST router
```

**Field mapping (bridge → catalog):**

| Catalog field | Source on phue light object | Notes |
|---------------|----------------------------|-------|
| `name` | `light.name` | Display / setup match name |
| `bridge_light_id` | `str(light.uniqueid)` if truthy, else `str(light.light_id)` if present | Prefer **stable** `uniqueid`; `light_id` is bridge-local and can renumber |

**Sync algorithm (authoritative):**
1. Prefer **active** match by `bridge_light_id` (`get_by_bridge_light_id(..., include_deleted=False)`).
2. Else prefer **active** match by `name`.
3. If active match: update `name` / `bridge_light_id` as needed (rename-on-bridge does not duplicate).
4. If no active match: look up soft-deleted by `bridge_light_id` then by `name` (`include_deleted=True` path via ordered getters).
   - If soft-deleted found and `reactivate_deleted=true`: clear `deleted_at`, update fields, count `updated`.
   - If soft-deleted found and `reactivate_deleted=false`: **skip** (do not revive, do not create for that inventory item).
5. If nothing matched: `create` new active row.
6. IntegrityError on unique active name → `LightValidationError` / API 409 (never raw 500).

---

## Phase 0 — Dependency, domain, persistence

### Task 1: Add aiosqlite direct dependency and app DB settings

**Files:**
- Modify: `pyproject.toml` (dependencies list)
- Modify: `marvin_hue/config.py` (add `app_db_path` + validators)
- Modify: `.gitignore` (ignore app sqlite files)
- Modify: `.env.example` (document `APP_DB_PATH`)
- Test: `tests/test_config.py` (default + env override + collision rejection)

**Prerequisites:**
- Files must exist: `pyproject.toml`, `marvin_hue/config.py`, `.gitignore`, `tests/test_config.py`
- Environment: none beyond project root

**Step 1: Write the failing test**

Append to `tests/test_config.py`. Extend `isolate_env_vars` env list with `"APP_DB_PATH"` and `"CHAT_CHECKPOINT_DB"`.

```python
class TestAppDbPathSettings:
    """App-owned SQLite path (lights registry) — separate from chat_memory.sqlite."""

    def test_default_app_db_path(self):
        settings = create_test_settings(bridge_ip="192.168.1.100")
        assert settings.app_db_path == ".res/marvin_hue.sqlite"

    def test_app_db_path_from_env(self, monkeypatch):
        monkeypatch.setenv("APP_DB_PATH", "/tmp/custom_marvin.sqlite")
        settings = create_test_settings(bridge_ip="192.168.1.100")
        assert settings.app_db_path == "/tmp/custom_marvin.sqlite"

    def test_app_db_path_distinct_from_chat_checkpoint_db(self):
        settings = create_test_settings(bridge_ip="192.168.1.100")
        assert settings.app_db_path != settings.chat_checkpoint_db
        assert "chat_memory" not in settings.app_db_path

    def test_app_db_path_rejects_same_as_chat_db(self):
        with pytest.raises(ValidationError):
            create_test_settings(
                bridge_ip="192.168.1.100",
                app_db_path=".res/chat_memory.sqlite",
                chat_checkpoint_db=".res/chat_memory.sqlite",
            )

    def test_app_db_path_rejects_chat_memory_basename(self):
        with pytest.raises(ValidationError):
            create_test_settings(
                bridge_ip="192.168.1.100",
                app_db_path="/tmp/chat_memory.sqlite",
            )
```

**Step 2: Run test to verify it fails**
```bash
uv run pytest tests/test_config.py::TestAppDbPathSettings -v --no-cov
```
Expected output:
```
FAILED ... AttributeError: ... app_db_path
```
(or collection error if class added but Settings lacks field)

**Step 3: Write minimal implementation**

In `pyproject.toml`, add to `dependencies`:
```toml
    "aiosqlite>=0.20.0",
```

In `marvin_hue/config.py`, update imports and add field + validator after `positions_file`:

```python
from pathlib import Path
from typing import Literal
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
```

```python
    # App-owned SQLite (lights registry catalog). Separate from chat_checkpoint_db.
    app_db_path: str = Field(
        default=".res/marvin_hue.sqlite",
        description="Caminho do SQLite da aplicação (catálogo de lâmpadas; NÃO o chat)",
    )

    @model_validator(mode="after")
    def validate_app_db_path_isolation(self) -> "Settings":
        """Refuse collinding app DB with chat checkpointer file."""
        app_raw = (self.app_db_path or "").strip()
        chat_raw = (self.chat_checkpoint_db or "").strip()
        if not app_raw:
            raise ValueError("app_db_path must be a non-empty path")
        if Path(app_raw).name == "chat_memory.sqlite":
            raise ValueError(
                "app_db_path must not use basename chat_memory.sqlite "
                "(reserved for chat checkpointer)"
            )
        # Prefer project .res/ for relative paths in docs; resolve for equality only.
        try:
            app_res = Path(app_raw).expanduser().resolve()
            chat_res = Path(chat_raw).expanduser().resolve()
        except OSError:
            app_res = Path(app_raw).expanduser()
            chat_res = Path(chat_raw).expanduser()
        if app_res == chat_res:
            raise ValueError(
                "app_db_path must be different from chat_checkpoint_db"
            )
        return self
```

In `.gitignore`, after chat sqlite entries, add:
```
.res/marvin_hue.sqlite
.res/marvin_hue.sqlite-wal
.res/marvin_hue.sqlite-shm
```

In `.env.example`, after file-path section (or after POSITIONS), add:
```bash
# App SQLite (lights registry catalog). Prefer under .res/. Do NOT use chat_memory.sqlite.
# APP_DB_PATH=.res/marvin_hue.sqlite
```

**Step 4: Verify tests pass**
```bash
uv sync
uv run pytest tests/test_config.py::TestAppDbPathSettings -v --no-cov
```
Expected:
```
PASSED test_default_app_db_path
PASSED test_app_db_path_from_env
PASSED test_app_db_path_distinct_from_chat_checkpoint_db
PASSED test_app_db_path_rejects_same_as_chat_db
PASSED test_app_db_path_rejects_chat_memory_basename
```

**Step 5: Commit**

Use `jarvis-default-commit` skill to stage and commit changes.

**If Task Fails:**
1. `uv sync` fails → check network / lock conflict; pin `aiosqlite>=0.20.0,<1`
2. Settings still fails → ensure field name is `app_db_path` (env `APP_DB_PATH`)
3. Validator too strict on relative paths → compare only after `expanduser().resolve()` when both paths exist parents; for non-existing paths `resolve()` still works for absolute form
4. Can't recover → Document what failed and stop. Return to human.

---

### Task 2: Domain entity and errors

**Files:**
- Create: `marvin_hue/domain/__init__.py`
- Create: `marvin_hue/domain/lights.py`
- Create: `tests/test_domain_lights.py`

**Prerequisites:**
- Task 1 complete (not strictly required for domain, but keep order)

**Step 1: Write the failing test**

Create `tests/test_domain_lights.py`:

```python
"""Unit tests for RegisteredLight domain entity."""

from datetime import datetime, timezone

import pytest

from marvin_hue.domain.lights import (
    LightConflictError,
    LightNotFoundError,
    LightValidationError,
    RegisteredLight,
)


def test_registered_light_defaults():
    light = RegisteredLight(
        id="11111111-1111-1111-1111-111111111111",
        name="Lâmpada 1",
    )
    assert light.name == "Lâmpada 1"
    assert light.nickname is None
    assert light.room is None
    assert light.notes is None
    assert light.bridge_light_id is None
    assert light.eye_safety_limit_pct is None
    assert light.enabled_for_app is True
    assert light.deleted_at is None
    assert light.is_deleted is False


def test_registered_light_is_deleted_when_deleted_at_set():
    light = RegisteredLight(
        id="11111111-1111-1111-1111-111111111111",
        name="Fita Led",
        deleted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert light.is_deleted is True


def test_registered_light_rejects_empty_name():
    with pytest.raises(LightValidationError):
        RegisteredLight(id="x", name="  ")


def test_eye_safety_limit_range():
    with pytest.raises(LightValidationError):
        RegisteredLight(
            id="x",
            name="Fita Led",
            eye_safety_limit_pct=101,
        )
    with pytest.raises(LightValidationError):
        RegisteredLight(
            id="x",
            name="Fita Led",
            eye_safety_limit_pct=-1,
        )
    ok = RegisteredLight(id="x", name="Fita Led", eye_safety_limit_pct=25)
    assert ok.eye_safety_limit_pct == 25


def test_domain_errors_are_exceptions():
    assert issubclass(LightNotFoundError, Exception)
    assert issubclass(LightValidationError, Exception)
    assert issubclass(LightConflictError, LightValidationError)
```

**Step 2: Run test to verify it fails**
```bash
uv run pytest tests/test_domain_lights.py -v --no-cov
```
Expected:
```
FAILED ... ModuleNotFoundError: No module named 'marvin_hue.domain'
```

**Step 3: Write minimal implementation**

`marvin_hue/domain/__init__.py`:
```python
"""Domain models and errors (framework-agnostic)."""

from marvin_hue.domain.lights import (
    LightConflictError,
    LightNotFoundError,
    LightValidationError,
    RegisteredLight,
)

__all__ = [
    "LightConflictError",
    "LightNotFoundError",
    "LightValidationError",
    "RegisteredLight",
]
```

`marvin_hue/domain/lights.py`:
```python
"""Light registry domain: catalog entity and errors.

SQLite owns app-side metadata. Philips Hue bridge remains source of truth
for physical device presence and live state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


class LightValidationError(ValueError):
    """Invalid light registry data."""


class LightConflictError(LightValidationError):
    """Active name (or other unique constraint) conflict."""


class LightNotFoundError(LookupError):
    """Registered light not found (or soft-deleted when not included)."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class RegisteredLight:
    """App catalog entry for a lamp/light.

    Attributes:
        id: Stable app UUID (string).
        name: Bridge/display name used to match Hue lights and setups JSON.
        nickname: Optional friendly name for UI/chat.
        room: Optional room label.
        notes: Free-text notes.
        bridge_light_id: Optional stable Hue id (prefer uniqueid, else light_id).
        eye_safety_limit_pct: Optional max brightness percent (0-100) stored for
            app use; v1 does not replace marvin_hue.eye_safety.EYE_SAFETY_LIMITS.
        enabled_for_app: If False, app features may skip this light.
        deleted_at: Soft-delete timestamp (UTC); None if active.
        created_at / updated_at: UTC timestamps.
    """

    id: str
    name: str
    nickname: Optional[str] = None
    room: Optional[str] = None
    notes: Optional[str] = None
    bridge_light_id: Optional[str] = None
    eye_safety_limit_pct: Optional[int] = None
    enabled_for_app: bool = True
    deleted_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        name = (self.name or "").strip()
        if not name:
            raise LightValidationError("name must be a non-empty string")
        self.name = name

        if self.nickname is not None:
            self.nickname = self.nickname.strip() or None
        if self.room is not None:
            self.room = self.room.strip() or None
        if self.notes is not None:
            self.notes = self.notes.strip() or None
        if self.bridge_light_id is not None:
            self.bridge_light_id = str(self.bridge_light_id).strip() or None

        if self.eye_safety_limit_pct is not None:
            if not isinstance(self.eye_safety_limit_pct, int) or isinstance(
                self.eye_safety_limit_pct, bool
            ):
                raise LightValidationError("eye_safety_limit_pct must be int or None")
            if self.eye_safety_limit_pct < 0 or self.eye_safety_limit_pct > 100:
                raise LightValidationError(
                    "eye_safety_limit_pct must be between 0 and 100"
                )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None
```

**Step 4: Verify tests pass**
```bash
uv run pytest tests/test_domain_lights.py -v --no-cov
```
Expected: all PASSED

**Step 5: Commit**

Use `jarvis-default-commit` skill to stage and commit changes.

**If Task Fails:**
1. Import path wrong → ensure `marvin_hue/domain/` is under package (hatch packages `marvin_hue`)
2. Dataclass validation → fix `__post_init__` only; no ORM yet

---

### Task 3: Schema init and versioned migrations

**Files:**
- Create: `marvin_hue/persistence/__init__.py`
- Create: `marvin_hue/persistence/schema.py`
- Create: `tests/test_persistence_schema.py`

**Prerequisites:**
- Task 1 (aiosqlite available)

**Step 1: Write the failing test**

Create `tests/test_persistence_schema.py`:

```python
"""Tests for SQLite schema initialization (lights registry)."""

import aiosqlite
import pytest

from marvin_hue.persistence.schema import CURRENT_SCHEMA_VERSION, init_db


@pytest.fixture
async def db_path(tmp_path):
    return str(tmp_path / "marvin_hue_test.sqlite")


@pytest.mark.asyncio
async def test_init_db_creates_schema_version_and_lights(db_path):
    await init_db(db_path)

    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
        assert row is not None
        assert int(row["version"]) == CURRENT_SCHEMA_VERSION

        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='lights'"
        ) as cur:
            assert await cur.fetchone() is not None


@pytest.mark.asyncio
async def test_init_db_is_idempotent(db_path):
    await init_db(db_path)
    await init_db(db_path)

    async with aiosqlite.connect(db_path) as conn:
        async with conn.execute("SELECT COUNT(*) FROM schema_version") as cur:
            count = (await cur.fetchone())[0]
        # one row per applied version
        assert count == CURRENT_SCHEMA_VERSION


@pytest.mark.asyncio
async def test_lights_table_columns(db_path):
    await init_db(db_path)
    async with aiosqlite.connect(db_path) as conn:
        async with conn.execute("PRAGMA table_info(lights)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
    expected = {
        "id",
        "bridge_light_id",
        "name",
        "nickname",
        "room",
        "notes",
        "eye_safety_limit_pct",
        "enabled_for_app",
        "deleted_at",
        "created_at",
        "updated_at",
    }
    assert expected.issubset(cols)


@pytest.mark.asyncio
async def test_init_db_enables_wal(db_path):
    await init_db(db_path)
    async with aiosqlite.connect(db_path) as conn:
        async with conn.execute("PRAGMA journal_mode") as cur:
            mode = (await cur.fetchone())[0]
    assert str(mode).lower() == "wal"
```

**Step 2: Run test to verify it fails**
```bash
uv run pytest tests/test_persistence_schema.py -v --no-cov
```
Expected: `ModuleNotFoundError: No module named 'marvin_hue.persistence'`

**Step 3: Write minimal implementation**

`marvin_hue/persistence/__init__.py`:
```python
"""Persistence adapters (SQLite)."""

from marvin_hue.persistence.schema import CURRENT_SCHEMA_VERSION, init_db

__all__ = ["CURRENT_SCHEMA_VERSION", "init_db"]
```

`marvin_hue/persistence/schema.py`:
```python
"""Versioned SQLite schema for the app-owned database.

Database file: settings.app_db_path (default .res/marvin_hue.sqlite).
Never share tables with chat_memory.sqlite.
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite

CURRENT_SCHEMA_VERSION = 1

# Ordered migrations: version -> list of SQL statements
_MIGRATIONS: dict[int, list[str]] = {
    1: [
        """
        CREATE TABLE IF NOT EXISTS lights (
            id TEXT PRIMARY KEY NOT NULL,
            bridge_light_id TEXT,
            name TEXT NOT NULL,
            nickname TEXT,
            room TEXT,
            notes TEXT,
            eye_safety_limit_pct INTEGER,
            enabled_for_app INTEGER NOT NULL DEFAULT 1,
            deleted_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_lights_name_active
        ON lights(name)
        WHERE deleted_at IS NULL
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_lights_bridge_light_id
        ON lights(bridge_light_id)
        WHERE bridge_light_id IS NOT NULL
        """,
    ],
}


async def _applied_versions(conn: aiosqlite.Connection) -> set[int]:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    await conn.commit()
    async with conn.execute("SELECT version FROM schema_version") as cur:
        rows = await cur.fetchall()
    return {int(r[0]) for r in rows}


async def init_db(db_path: str) -> None:
    """Create parent dir, open DB, apply pending migrations, enable WAL."""
    path = Path(db_path)
    if path.parent and str(path.parent) not in ("", "."):
        path.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        # Optional but recommended for concurrent readers (FastAPI + tools)
        await conn.execute("PRAGMA journal_mode=WAL")
        applied = await _applied_versions(conn)
        for version in sorted(_MIGRATIONS.keys()):
            if version in applied:
                continue
            for statement in _MIGRATIONS[version]:
                await conn.execute(statement)
            await conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, datetime('now'))",
                (version,),
            )
            await conn.commit()
```

**Step 4: Verify tests pass**
```bash
uv run pytest tests/test_persistence_schema.py -v --no-cov
```
Expected: all PASSED

**Step 5: Commit**

Use `jarvis-default-commit` skill to stage and commit changes.

**If Task Fails:**
1. Partial unique index unsupported → SQLite 3.8+ required (all modern distros OK)
2. WAL fails on network FS → rare; if test fails only on exotic FS, document; keep WAL for local `.res/`
3. Path permission → ensure tmp_path used in tests; for real path ensure `.res/` writable

---

### Task 4: Repository Protocol + create / get / list

**Files:**
- Create: `marvin_hue/persistence/light_repository.py`
- Create: `tests/test_light_repository.py`

**Prerequisites:**
- Tasks 2–3 complete

**Step 1: Write the failing test**

Create `tests/test_light_repository.py`:

```python
"""Tests for SqliteLightRegistryRepository (create/get/list)."""

from uuid import uuid4

import pytest

from marvin_hue.domain.lights import LightNotFoundError, LightValidationError, RegisteredLight
from marvin_hue.persistence.light_repository import SqliteLightRegistryRepository
from marvin_hue.persistence.schema import init_db


@pytest.fixture
async def repo(tmp_path):
    path = str(tmp_path / "lights.sqlite")
    await init_db(path)
    r = await SqliteLightRegistryRepository.open(path)
    yield r
    await r.close()


def _make_light(**kwargs) -> RegisteredLight:
    defaults = dict(
        id=str(uuid4()),
        name="Lâmpada 1",
        nickname="Mesa",
        room="Escritório",
        notes="teste",
        bridge_light_id="00:17:88:01:aa:bb-0b",
        eye_safety_limit_pct=None,
        enabled_for_app=True,
    )
    defaults.update(kwargs)
    return RegisteredLight(**defaults)


@pytest.mark.asyncio
async def test_create_and_get_by_id(repo):
    light = _make_light()
    created = await repo.create(light)
    assert created.id == light.id

    found = await repo.get_by_id(light.id)
    assert found.name == "Lâmpada 1"
    assert found.nickname == "Mesa"
    assert found.bridge_light_id == "00:17:88:01:aa:bb-0b"
    assert found.enabled_for_app is True
    assert found.deleted_at is None


@pytest.mark.asyncio
async def test_get_by_id_missing(repo):
    with pytest.raises(LightNotFoundError):
        await repo.get_by_id("00000000-0000-0000-0000-000000000000")


@pytest.mark.asyncio
async def test_list_excludes_deleted_by_default(repo):
    a = await repo.create(_make_light(name="A", bridge_light_id="id-a"))
    b = await repo.create(_make_light(name="B", bridge_light_id="id-b"))
    await repo.soft_delete(b.id)

    active = await repo.list_all(include_deleted=False)
    names = {x.name for x in active}
    assert names == {"A"}

    all_rows = await repo.list_all(include_deleted=True)
    assert {x.name for x in all_rows} == {"A", "B"}


@pytest.mark.asyncio
async def test_get_by_name_active(repo):
    await repo.create(_make_light(name="Hue Iris", bridge_light_id="id-iris"))
    found = await repo.get_by_name("Hue Iris")
    assert found is not None
    assert found.name == "Hue Iris"


@pytest.mark.asyncio
async def test_get_by_bridge_light_id(repo):
    await repo.create(_make_light(name="Play", bridge_light_id="unique-play"))
    found = await repo.get_by_bridge_light_id("unique-play")
    assert found is not None
    assert found.name == "Play"


@pytest.mark.asyncio
async def test_unique_active_name_raises_domain_error(repo):
    await repo.create(_make_light(name="Dup", bridge_light_id="d1"))
    with pytest.raises(LightValidationError):
        await repo.create(_make_light(name="Dup", bridge_light_id="d2"))
```

**Step 2: Run test to verify it fails**
```bash
uv run pytest tests/test_light_repository.py -v --no-cov
```
Expected: import/AttributeError for `SqliteLightRegistryRepository`

**Step 3: Write minimal implementation**

Implement full repository in `marvin_hue/persistence/light_repository.py` (create/get/list/get_by_bridge_light_id/soft_delete needed for these tests; include update for Task 5).

```python
"""Light registry repository: Protocol + aiosqlite adapter."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from typing import Optional, Protocol, runtime_checkable

import aiosqlite

from marvin_hue.domain.lights import (
    LightNotFoundError,
    LightValidationError,
    RegisteredLight,
)


def _dt_to_iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _iso_to_dt(value: Optional[str]) -> Optional[datetime]:
    if value is None or value == "":
        return None
    text = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _row_to_light(row: aiosqlite.Row) -> RegisteredLight:
    return RegisteredLight(
        id=row["id"],
        name=row["name"],
        nickname=row["nickname"],
        room=row["room"],
        notes=row["notes"],
        bridge_light_id=row["bridge_light_id"],
        eye_safety_limit_pct=row["eye_safety_limit_pct"],
        enabled_for_app=bool(row["enabled_for_app"]),
        deleted_at=_iso_to_dt(row["deleted_at"]),
        created_at=_iso_to_dt(row["created_at"]) or datetime.now(timezone.utc),
        updated_at=_iso_to_dt(row["updated_at"]) or datetime.now(timezone.utc),
    )


@runtime_checkable
class LightRegistryRepository(Protocol):
    async def create(self, light: RegisteredLight) -> RegisteredLight: ...

    async def get_by_id(
        self, light_id: str, *, include_deleted: bool = False
    ) -> RegisteredLight: ...

    async def get_by_name(
        self, name: str, *, include_deleted: bool = False
    ) -> Optional[RegisteredLight]: ...

    async def get_by_bridge_light_id(
        self, bridge_light_id: str, *, include_deleted: bool = False
    ) -> Optional[RegisteredLight]: ...

    async def list_all(self, *, include_deleted: bool = False) -> list[RegisteredLight]: ...

    async def update(self, light: RegisteredLight) -> RegisteredLight: ...

    async def soft_delete(self, light_id: str) -> RegisteredLight: ...

    async def close(self) -> None: ...


class SqliteLightRegistryRepository:
    """aiosqlite-backed light catalog repository.

    One shared connection per instance, serialized with asyncio.Lock for
    safe concurrent use under FastAPI.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    @classmethod
    async def open(cls, db_path: str) -> "SqliteLightRegistryRepository":
        repo = cls(db_path)
        await repo._get_conn()
        return repo

    async def _get_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            self._conn = await aiosqlite.connect(self._db_path)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA foreign_keys = ON")
        return self._conn

    async def close(self) -> None:
        async with self._lock:
            if self._conn is not None:
                await self._conn.close()
                self._conn = None

    async def create(self, light: RegisteredLight) -> RegisteredLight:
        async with self._lock:
            conn = await self._get_conn()
            try:
                await conn.execute(
                    """
                    INSERT INTO lights (
                        id, bridge_light_id, name, nickname, room, notes,
                        eye_safety_limit_pct, enabled_for_app, deleted_at,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        light.id,
                        light.bridge_light_id,
                        light.name,
                        light.nickname,
                        light.room,
                        light.notes,
                        light.eye_safety_limit_pct,
                        1 if light.enabled_for_app else 0,
                        _dt_to_iso(light.deleted_at),
                        _dt_to_iso(light.created_at),
                        _dt_to_iso(light.updated_at),
                    ),
                )
                await conn.commit()
            except (sqlite3.IntegrityError, aiosqlite.IntegrityError) as exc:
                raise LightValidationError(
                    f"Active light with name {light.name!r} already exists"
                ) from exc
            return await self._get_by_id_unlocked(light.id, include_deleted=True)

    async def _get_by_id_unlocked(
        self, light_id: str, *, include_deleted: bool = False
    ) -> RegisteredLight:
        conn = await self._get_conn()
        sql = "SELECT * FROM lights WHERE id = ?"
        params: list[object] = [light_id]
        if not include_deleted:
            sql += " AND deleted_at IS NULL"
        async with conn.execute(sql, params) as cur:
            row = await cur.fetchone()
        if row is None:
            raise LightNotFoundError(f"Light id={light_id!r} not found")
        return _row_to_light(row)

    async def get_by_id(
        self, light_id: str, *, include_deleted: bool = False
    ) -> RegisteredLight:
        async with self._lock:
            return await self._get_by_id_unlocked(
                light_id, include_deleted=include_deleted
            )

    async def get_by_name(
        self, name: str, *, include_deleted: bool = False
    ) -> Optional[RegisteredLight]:
        """Deterministic: prefer active, then most recently updated."""
        async with self._lock:
            conn = await self._get_conn()
            sql = """
                SELECT * FROM lights
                WHERE name = ?
            """
            params: list[object] = [name]
            if not include_deleted:
                sql += " AND deleted_at IS NULL"
            sql += " ORDER BY deleted_at IS NULL DESC, updated_at DESC LIMIT 1"
            async with conn.execute(sql, params) as cur:
                row = await cur.fetchone()
            if row is None:
                return None
            return _row_to_light(row)

    async def get_by_bridge_light_id(
        self, bridge_light_id: str, *, include_deleted: bool = False
    ) -> Optional[RegisteredLight]:
        """Deterministic: prefer active, then most recently updated."""
        async with self._lock:
            conn = await self._get_conn()
            sql = """
                SELECT * FROM lights
                WHERE bridge_light_id = ?
            """
            params: list[object] = [bridge_light_id]
            if not include_deleted:
                sql += " AND deleted_at IS NULL"
            sql += " ORDER BY deleted_at IS NULL DESC, updated_at DESC LIMIT 1"
            async with conn.execute(sql, params) as cur:
                row = await cur.fetchone()
            if row is None:
                return None
            return _row_to_light(row)

    async def list_all(self, *, include_deleted: bool = False) -> list[RegisteredLight]:
        async with self._lock:
            conn = await self._get_conn()
            sql = "SELECT * FROM lights"
            if not include_deleted:
                sql += " WHERE deleted_at IS NULL"
            sql += " ORDER BY name COLLATE NOCASE"
            async with conn.execute(sql) as cur:
                rows = await cur.fetchall()
            return [_row_to_light(r) for r in rows]

    async def update(self, light: RegisteredLight) -> RegisteredLight:
        async with self._lock:
            conn = await self._get_conn()
            await self._get_by_id_unlocked(light.id, include_deleted=True)
            now = datetime.now(timezone.utc)
            light.updated_at = now
            try:
                await conn.execute(
                    """
                    UPDATE lights SET
                        bridge_light_id = ?,
                        name = ?,
                        nickname = ?,
                        room = ?,
                        notes = ?,
                        eye_safety_limit_pct = ?,
                        enabled_for_app = ?,
                        deleted_at = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        light.bridge_light_id,
                        light.name,
                        light.nickname,
                        light.room,
                        light.notes,
                        light.eye_safety_limit_pct,
                        1 if light.enabled_for_app else 0,
                        _dt_to_iso(light.deleted_at),
                        _dt_to_iso(light.updated_at),
                        light.id,
                    ),
                )
                await conn.commit()
            except (sqlite3.IntegrityError, aiosqlite.IntegrityError) as exc:
                raise LightValidationError(
                    f"Active light with name {light.name!r} already exists"
                ) from exc
            return await self._get_by_id_unlocked(light.id, include_deleted=True)

    async def soft_delete(self, light_id: str) -> RegisteredLight:
        async with self._lock:
            light = await self._get_by_id_unlocked(light_id, include_deleted=False)
            light.deleted_at = datetime.now(timezone.utc)
            light.updated_at = light.deleted_at
            # inline update without re-entering lock
            conn = await self._get_conn()
            await conn.execute(
                """
                UPDATE lights SET
                    deleted_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    _dt_to_iso(light.deleted_at),
                    _dt_to_iso(light.updated_at),
                    light.id,
                ),
            )
            await conn.commit()
            return await self._get_by_id_unlocked(light.id, include_deleted=True)
```

**Step 4: Verify tests pass**
```bash
uv run pytest tests/test_light_repository.py -v --no-cov
```
Expected: all PASSED

**Step 5: Commit**

Use `jarvis-default-commit` skill to stage and commit changes.

**If Task Fails:**
1. Unique index violation type → must map to `LightValidationError`, never raw 500
2. Connection not closed → fixture must `await repo.close()`
3. Deadlock on nested lock → soft_delete must not call `update()` which re-acquires lock (implementation above avoids that)
4. Timezone parsing → ensure ISO with offset in helpers

---

### Task 5: Repository update / soft-delete + ordered lookup edge cases

**Files:**
- Modify: `tests/test_light_repository.py` (add cases)
- Modify: `marvin_hue/persistence/light_repository.py` only if gaps found

**Prerequisites:**
- Task 4 complete

**Step 1: Write the failing test**

Append to `tests/test_light_repository.py`:

```python
@pytest.mark.asyncio
async def test_update_metadata(repo):
    light = await repo.create(
        _make_light(name="Hue Play 1", nickname=None, bridge_light_id="play-1")
    )
    light.nickname = "Esquerda"
    light.room = "Sala"
    light.eye_safety_limit_pct = 40
    light.enabled_for_app = False
    updated = await repo.update(light)
    assert updated.nickname == "Esquerda"
    assert updated.room == "Sala"
    assert updated.eye_safety_limit_pct == 40
    assert updated.enabled_for_app is False
    assert updated.updated_at >= light.created_at


@pytest.mark.asyncio
async def test_soft_delete_then_get_by_id_hidden(repo):
    light = await repo.create(_make_light(name="Led cima", bridge_light_id="led-top"))
    await repo.soft_delete(light.id)
    with pytest.raises(LightNotFoundError):
        await repo.get_by_id(light.id, include_deleted=False)
    found = await repo.get_by_id(light.id, include_deleted=True)
    assert found.is_deleted is True


@pytest.mark.asyncio
async def test_soft_delete_missing_raises(repo):
    with pytest.raises(LightNotFoundError):
        await repo.soft_delete("00000000-0000-0000-0000-000000000000")


@pytest.mark.asyncio
async def test_soft_delete_then_create_same_name_active(repo):
    first = await repo.create(_make_light(name="Reuse", bridge_light_id="old-id"))
    await repo.soft_delete(first.id)
    second = await repo.create(_make_light(name="Reuse", bridge_light_id=None))
    assert second.deleted_at is None
    assert second.id != first.id
    active = await repo.get_by_name("Reuse", include_deleted=False)
    assert active is not None
    assert active.id == second.id


@pytest.mark.asyncio
async def test_get_by_name_prefers_active_over_deleted(repo):
    deleted = await repo.create(_make_light(name="Prefer", bridge_light_id="p-old"))
    await repo.soft_delete(deleted.id)
    active = await repo.create(_make_light(name="Prefer", bridge_light_id="p-new"))
    found = await repo.get_by_name("Prefer", include_deleted=True)
    assert found is not None
    assert found.id == active.id
    assert found.deleted_at is None


@pytest.mark.asyncio
async def test_get_by_bridge_light_id_prefers_active(repo):
    old = await repo.create(_make_light(name="N1", bridge_light_id="same-bid"))
    await repo.soft_delete(old.id)
    # After soft-delete, bridge_id may still be on deleted row; create another
    # active with different name but same bridge id only if unique index allows
    # (no unique on bridge_id). Prefer active when both exist.
    active = await repo.create(_make_light(name="N2", bridge_light_id="same-bid"))
    found = await repo.get_by_bridge_light_id("same-bid", include_deleted=True)
    assert found is not None
    assert found.id == active.id
```

**Step 2: Run tests**
```bash
uv run pytest tests/test_light_repository.py -v --no-cov
```
Expected: all PASSED (if Task 4 implementation complete). If any fail, fix repository.

**Step 3: Minimal fix if needed** — only adjust code that fails.

**Step 4: Re-run full repository + schema suite**
```bash
uv run pytest tests/test_persistence_schema.py tests/test_light_repository.py -v --no-cov
```
Expected: all PASSED

**Step 5: Commit**

Use `jarvis-default-commit` skill to stage and commit changes.

**If Task Fails:**
1. `updated_at` comparison timezone-aware vs naive → normalize both to UTC
2. soft_delete on already deleted → current design raises NotFound (OK for v1)
3. ORDER BY clause wrong on SQLite → use `ORDER BY (deleted_at IS NULL) DESC, updated_at DESC`

---

### Task 6: Code Review Checkpoint A

1. **REQUIRED SUB-SKILL:** Use jarvis-default-codereview — dispatch all reviewers in parallel
2. **Scope:** `marvin_hue/domain/`, `marvin_hue/persistence/`, related tests, config/pyproject changes
3. **Handle findings by severity:** see jarvis-default-codereview severity rules
4. **Proceed only when:** zero Critical/High/Medium issues remain

---

## Phase 1 — Service + bridge inventory

### Task 7: LightRegistryService CRUD only

**Files:**
- Create: `marvin_hue/services/__init__.py`
- Create: `marvin_hue/services/light_registry.py`
- Create: `tests/test_light_registry_service.py`

**Prerequisites:**
- Tasks 2–5 complete

**Step 1: Write the failing test**

Create `tests/test_light_registry_service.py`:

```python
"""Service-layer tests for light registry CRUD (in-memory fake repo)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import pytest

from marvin_hue.domain.lights import (
    LightConflictError,
    LightNotFoundError,
    LightValidationError,
    RegisteredLight,
)
from marvin_hue.services.light_registry import LightRegistryService, _UNSET


class FakeRepo:
    def __init__(self) -> None:
        self._items: dict[str, RegisteredLight] = {}

    async def create(self, light: RegisteredLight) -> RegisteredLight:
        for existing in self._items.values():
            if existing.deleted_at is None and existing.name == light.name:
                raise LightValidationError(f"name already exists: {light.name}")
        self._items[light.id] = light
        return light

    async def get_by_id(
        self, light_id: str, *, include_deleted: bool = False
    ) -> RegisteredLight:
        light = self._items.get(light_id)
        if light is None:
            raise LightNotFoundError(light_id)
        if light.deleted_at is not None and not include_deleted:
            raise LightNotFoundError(light_id)
        return light

    async def get_by_name(
        self, name: str, *, include_deleted: bool = False
    ) -> Optional[RegisteredLight]:
        candidates = [
            light
            for light in self._items.values()
            if light.name == name
            and (include_deleted or light.deleted_at is None)
        ]
        if not candidates:
            return None
        candidates.sort(
            key=lambda x: (x.deleted_at is None, x.updated_at), reverse=True
        )
        return candidates[0]

    async def get_by_bridge_light_id(
        self, bridge_light_id: str, *, include_deleted: bool = False
    ) -> Optional[RegisteredLight]:
        candidates = [
            light
            for light in self._items.values()
            if light.bridge_light_id == bridge_light_id
            and (include_deleted or light.deleted_at is None)
        ]
        if not candidates:
            return None
        candidates.sort(
            key=lambda x: (x.deleted_at is None, x.updated_at), reverse=True
        )
        return candidates[0]

    async def list_all(self, *, include_deleted: bool = False) -> list[RegisteredLight]:
        out = []
        for light in self._items.values():
            if light.deleted_at is not None and not include_deleted:
                continue
            out.append(light)
        return sorted(out, key=lambda x: x.name.lower())

    async def update(self, light: RegisteredLight) -> RegisteredLight:
        if light.id not in self._items:
            raise LightNotFoundError(light.id)
        self._items[light.id] = light
        return light

    async def soft_delete(self, light_id: str) -> RegisteredLight:
        light = await self.get_by_id(light_id, include_deleted=False)
        light.deleted_at = datetime.now(timezone.utc)
        return await self.update(light)

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_create_generates_uuid_and_persists():
    svc = LightRegistryService(FakeRepo())
    created = await svc.create_light(name="Lâmpada 1", nickname="Mesa")
    assert created.id
    assert created.name == "Lâmpada 1"
    assert created.nickname == "Mesa"
    listed = await svc.list_lights()
    assert len(listed) == 1


@pytest.mark.asyncio
async def test_update_partial_metadata():
    svc = LightRegistryService(FakeRepo())
    created = await svc.create_light(name="Hue Iris")
    updated = await svc.update_light(
        created.id, nickname="Iris", room="Sala", enabled_for_app=False
    )
    assert updated.nickname == "Iris"
    assert updated.room == "Sala"
    assert updated.enabled_for_app is False
    assert updated.name == "Hue Iris"


@pytest.mark.asyncio
async def test_update_clears_nullable_with_none():
    svc = LightRegistryService(FakeRepo())
    created = await svc.create_light(name="ClearMe", nickname="Nick", notes="n")
    updated = await svc.update_light(
        created.id, nickname=None, notes=None, eye_safety_limit_pct=None
    )
    # Explicit None clears; unset fields stay
    assert updated.nickname is None
    assert updated.notes is None
    assert updated.name == "ClearMe"


@pytest.mark.asyncio
async def test_update_unset_does_not_clear():
    svc = LightRegistryService(FakeRepo())
    created = await svc.create_light(name="Keep", nickname="Nick")
    updated = await svc.update_light(created.id, room="Sala")
    assert updated.nickname == "Nick"
    assert updated.room == "Sala"


@pytest.mark.asyncio
async def test_delete_soft():
    svc = LightRegistryService(FakeRepo())
    created = await svc.create_light(name="Fita Led")
    await svc.delete_light(created.id)
    with pytest.raises(LightNotFoundError):
        await svc.get_light(created.id)
    all_rows = await svc.list_lights(include_deleted=True)
    assert len(all_rows) == 1
    assert all_rows[0].is_deleted


@pytest.mark.asyncio
async def test_create_duplicate_name_fails():
    svc = LightRegistryService(FakeRepo())
    await svc.create_light(name="X")
    with pytest.raises(LightConflictError):
        await svc.create_light(name="X")
```

**Step 2: Run test to verify it fails**
```bash
uv run pytest tests/test_light_registry_service.py -v --no-cov
```
Expected: ModuleNotFoundError for `marvin_hue.services.light_registry`

**Step 3: Write minimal implementation**

`marvin_hue/services/__init__.py`:
```python
"""Application services."""

from marvin_hue.services.light_registry import LightRegistryService

__all__ = ["LightRegistryService"]
```

`marvin_hue/services/light_registry.py` (CRUD only in this task; sync stubs deferred to Task 9 — implement CRUD completely):

```python
"""Light registry application service: CRUD + bridge sync."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Protocol
from uuid import uuid4

from marvin_hue.domain.lights import (
    LightConflictError,
    LightNotFoundError,
    LightValidationError,
    RegisteredLight,
)
from marvin_hue.persistence.light_repository import LightRegistryRepository

# Sentinel for PATCH: missing key = leave unchanged; explicit None = clear nullable.
_UNSET: object = object()


class BridgeLightInventory(Protocol):
    """Minimal port for reading lights from HueController."""

    def list_bridge_lights(self) -> list[dict[str, Any]]:
        """Return list of {name, bridge_light_id?} from the physical bridge."""
        ...


class LightRegistryService:
    def __init__(
        self,
        repo: LightRegistryRepository,
        bridge: Optional[BridgeLightInventory] = None,
    ) -> None:
        self._repo = repo
        self._bridge = bridge

    async def aclose(self) -> None:
        await self._repo.close()

    async def list_lights(
        self, *, include_deleted: bool = False
    ) -> list[RegisteredLight]:
        return await self._repo.list_all(include_deleted=include_deleted)

    async def get_light(
        self, light_id: str, *, include_deleted: bool = False
    ) -> RegisteredLight:
        return await self._repo.get_by_id(light_id, include_deleted=include_deleted)

    async def create_light(
        self,
        *,
        name: str,
        nickname: Optional[str] = None,
        room: Optional[str] = None,
        notes: Optional[str] = None,
        bridge_light_id: Optional[str] = None,
        eye_safety_limit_pct: Optional[int] = None,
        enabled_for_app: bool = True,
    ) -> RegisteredLight:
        existing = await self._repo.get_by_name(name.strip(), include_deleted=False)
        if existing is not None:
            raise LightConflictError(
                f"Active light with name {name!r} already exists"
            )

        now = datetime.now(timezone.utc)
        light = RegisteredLight(
            id=str(uuid4()),
            name=name,
            nickname=nickname,
            room=room,
            notes=notes,
            bridge_light_id=bridge_light_id,
            eye_safety_limit_pct=eye_safety_limit_pct,
            enabled_for_app=enabled_for_app,
            created_at=now,
            updated_at=now,
        )
        try:
            return await self._repo.create(light)
        except LightValidationError as exc:
            # Repo maps IntegrityError → LightValidationError; promote conflicts.
            msg = str(exc).lower()
            if "already exists" in msg or "unique" in msg:
                raise LightConflictError(str(exc)) from exc
            raise

    async def update_light(
        self,
        light_id: str,
        *,
        name: object = _UNSET,
        nickname: object = _UNSET,
        room: object = _UNSET,
        notes: object = _UNSET,
        bridge_light_id: object = _UNSET,
        eye_safety_limit_pct: object = _UNSET,
        enabled_for_app: object = _UNSET,
    ) -> RegisteredLight:
        light = await self._repo.get_by_id(light_id, include_deleted=False)

        if name is not _UNSET:
            if name is None:
                raise LightValidationError("name must be non-empty")
            new_name = str(name).strip()
            if not new_name:
                raise LightValidationError("name must be non-empty")
            other = await self._repo.get_by_name(new_name, include_deleted=False)
            if other is not None and other.id != light.id:
                raise LightConflictError(
                    f"Active light with name {new_name!r} already exists"
                )
            light.name = new_name

        if nickname is not _UNSET:
            light.nickname = nickname  # type: ignore[assignment]
        if room is not _UNSET:
            light.room = room  # type: ignore[assignment]
        if notes is not _UNSET:
            light.notes = notes  # type: ignore[assignment]
        if bridge_light_id is not _UNSET:
            light.bridge_light_id = (
                str(bridge_light_id).strip() or None
                if bridge_light_id is not None
                else None
            )
        if eye_safety_limit_pct is not _UNSET:
            light.eye_safety_limit_pct = eye_safety_limit_pct  # type: ignore[assignment]
        if enabled_for_app is not _UNSET:
            if enabled_for_app is None:
                raise LightValidationError("enabled_for_app cannot be null")
            light.enabled_for_app = bool(enabled_for_app)

        light = RegisteredLight(
            id=light.id,
            name=light.name,
            nickname=light.nickname,
            room=light.room,
            notes=light.notes,
            bridge_light_id=light.bridge_light_id,
            eye_safety_limit_pct=light.eye_safety_limit_pct,
            enabled_for_app=light.enabled_for_app,
            deleted_at=light.deleted_at,
            created_at=light.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        try:
            return await self._repo.update(light)
        except LightValidationError as exc:
            msg = str(exc).lower()
            if "already exists" in msg or "unique" in msg:
                raise LightConflictError(str(exc)) from exc
            raise

    async def delete_light(self, light_id: str) -> RegisteredLight:
        """Soft-delete catalog entry only. Never deletes on Hue bridge."""
        return await self._repo.soft_delete(light_id)
```

**Step 4: Verify tests pass**
```bash
uv run pytest tests/test_light_registry_service.py -v --no-cov
```
Expected: all PASSED

**Step 5: Commit**

Use `jarvis-default-commit` skill to stage and commit changes.

**If Task Fails:**
1. FakeRepo typing vs Protocol → Protocol is structural; methods must match including `get_by_bridge_light_id`
2. `_UNSET` import in tests → export from service module

---

### Task 8: Bridge inventory helper on HueController

**Files:**
- Modify: `marvin_hue/controllers.py` (add `list_bridge_lights`)
- Modify: `tests/test_controllers.py` (add test under `TestHueControllerLightLookup`)

**Prerequisites:**
- None beyond existing controller tests

**Step 1: Write the failing test**

Append to class `TestHueControllerLightLookup` in `tests/test_controllers.py` (this class already uses `mock_hue_controller` and covers `list_lights` / cache):

```python
    def test_list_bridge_lights_returns_name_and_id(self, mock_hue_controller):
        """Inventory for catalog sync: prefer uniqueid over light_id."""
        for i, light in enumerate(mock_hue_controller.lights, start=1):
            light.light_id = i
            light.uniqueid = f"00:17:88:01:00:00:00:{i:02d}-0b"
        rows = mock_hue_controller.list_bridge_lights()
        assert isinstance(rows, list)
        assert len(rows) >= 1
        assert "name" in rows[0]
        assert rows[0]["name"]
        assert "bridge_light_id" in rows[0]
        # uniqueid preferred
        assert rows[0]["bridge_light_id"].startswith("00:17:88")

    def test_list_bridge_lights_falls_back_to_light_id(self, mock_hue_controller):
        for i, light in enumerate(mock_hue_controller.lights, start=1):
            light.light_id = 10 + i
            if hasattr(light, "uniqueid"):
                del light.uniqueid
            light.uniqueid = None
        rows = mock_hue_controller.list_bridge_lights()
        assert rows[0]["bridge_light_id"] is not None
        assert rows[0]["bridge_light_id"].isdigit() or rows[0]["bridge_light_id"]
```

**Step 2: Run tests to verify failure**
```bash
uv run pytest tests/test_controllers.py::TestHueControllerLightLookup -k list_bridge -v --no-cov
```
Expected: AttributeError / no method `list_bridge_lights`

**Step 3: Implement on HueController**

In `marvin_hue/controllers.py`, after `list_lights` (ensure `Any` is already imported from typing):

```python
    def list_bridge_lights(self) -> list[dict[str, Any]]:
        """Inventory for catalog sync: name + optional stable bridge light id.

        Field mapping:
        - name ← light.name
        - bridge_light_id ← uniqueid (preferred, stable) else light_id (volatile)

        Does not hit extra HTTP if lights already cached on the controller.
        Call refresh_lights() first if topology may have changed.
        """
        inventory: list[dict[str, Any]] = []
        for light in self.lights:
            bridge_id: str | None = None
            uniqueid = getattr(light, "uniqueid", None)
            if uniqueid:
                bridge_id = str(uniqueid)
            elif hasattr(light, "light_id") and light.light_id is not None:
                bridge_id = str(light.light_id)
            inventory.append(
                {
                    "name": light.name,
                    "bridge_light_id": bridge_id,
                }
            )
        return inventory
```

**Step 4: Verify**
```bash
uv run pytest tests/test_controllers.py::TestHueControllerLightLookup -k list_bridge -v --no-cov
```
Expected: matching tests PASSED

**Step 5: Commit**

Use `jarvis-default-commit` skill to stage and commit changes.

**If Task Fails:**
1. Mock lights lack `light_id` / `uniqueid` → set on mock in test; method must tolerate absence (`None`)
2. Wrong test class name → use `TestHueControllerLightLookup` (confirmed in `tests/test_controllers.py`)

---

### Task 9: Service sync with soft-delete policy

**Files:**
- Modify: `marvin_hue/services/light_registry.py` (add `sync_from_bridge`, `refresh_and_sync`, `SyncResult`)
- Modify: `tests/test_light_registry_service.py` (sync policy tests)

**Prerequisites:**
- Tasks 7–8 complete

**Step 1: Write the failing tests**

Append to `tests/test_light_registry_service.py`:

```python
class FakeBridge:
    def __init__(self, lights: list[dict]):
        self._lights = lights
        self.refresh_calls = 0

    def list_bridge_lights(self) -> list[dict]:
        return list(self._lights)

    def refresh_lights(self) -> None:
        self.refresh_calls += 1


@pytest.mark.asyncio
async def test_sync_creates_new_lights():
    repo = FakeRepo()
    bridge = FakeBridge(
        [
            {"name": "Lâmpada 1", "bridge_light_id": "uid-1"},
            {"name": "Hue Play 1", "bridge_light_id": "uid-5"},
        ]
    )
    svc = LightRegistryService(repo, bridge=bridge)
    result = await svc.sync_from_bridge()
    assert result["created"] == 2
    assert result["total_bridge"] == 2
    names = {x.name for x in await svc.list_lights()}
    assert names == {"Lâmpada 1", "Hue Play 1"}


@pytest.mark.asyncio
async def test_sync_updates_bridge_id_and_is_idempotent():
    repo = FakeRepo()
    svc = LightRegistryService(
        repo, bridge=FakeBridge([{"name": "A", "bridge_light_id": "1"}])
    )
    await svc.sync_from_bridge()
    result2 = await svc.sync_from_bridge()
    assert result2["created"] == 0
    assert result2["unchanged"] == 1

    svc2 = LightRegistryService(
        repo, bridge=FakeBridge([{"name": "A", "bridge_light_id": "99"}])
    )
    result3 = await svc2.sync_from_bridge()
    assert result3["updated"] == 1
    light = await svc2.list_lights()
    assert light[0].bridge_light_id == "99"


@pytest.mark.asyncio
async def test_sync_does_not_revive_soft_deleted_by_default():
    repo = FakeRepo()
    svc = LightRegistryService(
        repo, bridge=FakeBridge([{"name": "Ghost", "bridge_light_id": "g1"}])
    )
    await svc.sync_from_bridge()
    light = (await svc.list_lights())[0]
    await svc.delete_light(light.id)

    result = await svc.sync_from_bridge()
    assert result["created"] == 0
    assert result["updated"] == 0
    active = await svc.list_lights(include_deleted=False)
    assert active == []
    deleted = await svc.list_lights(include_deleted=True)
    assert len(deleted) == 1
    assert deleted[0].is_deleted


@pytest.mark.asyncio
async def test_sync_reactivate_deleted_true_revives():
    repo = FakeRepo()
    svc = LightRegistryService(
        repo, bridge=FakeBridge([{"name": "Ghost", "bridge_light_id": "g1"}])
    )
    await svc.sync_from_bridge()
    light = (await svc.list_lights())[0]
    await svc.delete_light(light.id)

    result = await svc.sync_from_bridge(reactivate_deleted=True)
    assert result["updated"] == 1
    active = await svc.list_lights(include_deleted=False)
    assert len(active) == 1
    assert active[0].id == light.id
    assert active[0].deleted_at is None


@pytest.mark.asyncio
async def test_soft_delete_create_same_name_then_sync_attaches_bridge_id():
    repo = FakeRepo()
    svc = LightRegistryService(repo, bridge=None)
    first = await svc.create_light(name="Reuse", bridge_light_id="old-uid")
    await svc.delete_light(first.id)
    second = await svc.create_light(name="Reuse", bridge_light_id=None)
    svc._bridge = FakeBridge(
        [{"name": "Reuse", "bridge_light_id": "old-uid"}]
    )
    result = await svc.sync_from_bridge()
    # Attaches to active row by name; does not revive deleted
    assert result["updated"] == 1 or result["unchanged"] == 1 or result["created"] == 0
    active = await svc.get_light(second.id)
    assert active.bridge_light_id == "old-uid"
    assert active.deleted_at is None
    still_deleted = await svc.get_light(first.id, include_deleted=True)
    assert still_deleted.is_deleted


@pytest.mark.asyncio
async def test_sync_rename_on_bridge_matches_by_bridge_id():
    repo = FakeRepo()
    svc = LightRegistryService(
        repo, bridge=FakeBridge([{"name": "OldName", "bridge_light_id": "stable"}])
    )
    await svc.sync_from_bridge()
    svc._bridge = FakeBridge(
        [{"name": "NewName", "bridge_light_id": "stable"}]
    )
    result = await svc.sync_from_bridge()
    assert result["updated"] == 1
    lights = await svc.list_lights()
    assert len(lights) == 1
    assert lights[0].name == "NewName"
    assert lights[0].bridge_light_id == "stable"


@pytest.mark.asyncio
async def test_refresh_and_sync_calls_refresh():
    bridge = FakeBridge([{"name": "A", "bridge_light_id": "1"}])
    svc = LightRegistryService(FakeRepo(), bridge=bridge)
    await svc.refresh_and_sync()
    assert bridge.refresh_calls == 1


@pytest.mark.asyncio
async def test_sync_without_bridge_raises():
    svc = LightRegistryService(FakeRepo(), bridge=None)
    with pytest.raises(LightValidationError):
        await svc.sync_from_bridge()
```

**Step 2: Run to fail**
```bash
uv run pytest tests/test_light_registry_service.py -k sync -v --no-cov
```
Expected: AttributeError / missing `sync_from_bridge`

**Step 3: Implement sync on service**

Append to `LightRegistryService` in `marvin_hue/services/light_registry.py`:

```python
    async def sync_from_bridge(
        self, *, reactivate_deleted: bool = False
    ) -> dict[str, int]:
        """Upsert catalog rows from bridge inventory.

        Identity: bridge_light_id first (active), then name (active).
        Soft-deleted rows are not reactivated unless reactivate_deleted=True.
        Soft-deleted matches without reactivate are skipped (no create).

        Returns counts: created, updated, unchanged, skipped_deleted, total_bridge.
        """
        if self._bridge is None:
            raise LightValidationError("Bridge inventory is not configured")

        inventory = self._bridge.list_bridge_lights()
        created = updated = unchanged = skipped_deleted = 0

        for item in inventory:
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            raw_bid = item.get("bridge_light_id")
            bridge_id_str = str(raw_bid).strip() if raw_bid is not None else None
            if bridge_id_str == "":
                bridge_id_str = None

            active: Optional[RegisteredLight] = None
            if bridge_id_str is not None:
                active = await self._repo.get_by_bridge_light_id(
                    bridge_id_str, include_deleted=False
                )
            if active is None:
                active = await self._repo.get_by_name(name, include_deleted=False)

            if active is not None:
                changed = False
                if active.name != name:
                    active.name = name
                    changed = True
                if (
                    bridge_id_str is not None
                    and active.bridge_light_id != bridge_id_str
                ):
                    active.bridge_light_id = bridge_id_str
                    changed = True
                if changed:
                    active.updated_at = datetime.now(timezone.utc)
                    await self._repo.update(active)
                    updated += 1
                else:
                    unchanged += 1
                continue

            # No active match: consider soft-deleted
            deleted: Optional[RegisteredLight] = None
            if bridge_id_str is not None:
                candidate = await self._repo.get_by_bridge_light_id(
                    bridge_id_str, include_deleted=True
                )
                if candidate is not None and candidate.deleted_at is not None:
                    deleted = candidate
            if deleted is None:
                candidate = await self._repo.get_by_name(name, include_deleted=True)
                if candidate is not None and candidate.deleted_at is not None:
                    deleted = candidate

            if deleted is not None:
                if not reactivate_deleted:
                    skipped_deleted += 1
                    continue
                deleted.deleted_at = None
                deleted.name = name
                if bridge_id_str is not None:
                    deleted.bridge_light_id = bridge_id_str
                deleted.updated_at = datetime.now(timezone.utc)
                await self._repo.update(deleted)
                updated += 1
                continue

            # Unknown: create
            await self.create_light(name=name, bridge_light_id=bridge_id_str)
            created += 1

        return {
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
            "skipped_deleted": skipped_deleted,
            "total_bridge": len(inventory),
        }

    async def refresh_and_sync(
        self, *, reactivate_deleted: bool = False
    ) -> dict[str, int]:
        """Refresh bridge topology if available, then sync.

        Raises LightValidationError if bridge missing.
        Propagates refresh failures as LightValidationError with generic message
        (no exception string leakage for API layer).
        """
        if self._bridge is None:
            raise LightValidationError("Bridge inventory is not configured")
        refresh = getattr(self._bridge, "refresh_lights", None)
        if callable(refresh):
            try:
                refresh()
            except Exception as exc:
                raise LightValidationError(
                    "Unable to refresh lights from bridge"
                ) from exc
        return await self.sync_from_bridge(reactivate_deleted=reactivate_deleted)
```

**Step 4: Verify**
```bash
uv run pytest tests/test_light_registry_service.py -v --no-cov
```
Expected: all PASSED

**Step 5: Commit**

Use `jarvis-default-commit` skill to stage and commit changes.

**If Task Fails:**
1. Soft-delete then create then sync: match active by name before deleted by bridge_id — order in algorithm is critical
2. Rename creates duplicate → must match bridge_id on active first
3. Name conflict on create during sync → map IntegrityError via create_light to LightConflictError

---

### Task 10: Code Review Checkpoint B

1. **REQUIRED SUB-SKILL:** Use jarvis-default-codereview — dispatch all reviewers in parallel
2. **Scope:** `marvin_hue/services/light_registry.py`, `controllers.py` `list_bridge_lights`, service tests
3. **Handle findings by severity**
4. **Proceed only when:** zero Critical/High/Medium issues remain

---

## Phase 2 — API models, DI, lifespan, routes

### Task 11: Pydantic API models for lights registry

**Files:**
- Modify: `marvin_hue/api/models.py`
- Create: `tests/test_api_light_models.py`

**Prerequisites:**
- Domain entity exists (Task 2)

**Step 1: Write the failing test**

Create `tests/test_api_light_models.py`:

```python
"""Validation tests for lights registry API models."""

import pytest
from pydantic import ValidationError

from marvin_hue.api.models import (
    LightCreateRequest,
    LightResponse,
    LightUpdateRequest,
    LightsSyncResponse,
)


def test_create_request_requires_name():
    with pytest.raises(ValidationError):
        LightCreateRequest()


def test_create_request_ok():
    m = LightCreateRequest(name="Lâmpada 1", nickname="Mesa", room="Escritório")
    assert m.name == "Lâmpada 1"
    assert m.enabled_for_app is True


def test_update_request_all_optional():
    m = LightUpdateRequest(nickname="X")
    assert m.nickname == "X"
    assert m.name is None
    # exclude_unset distinguishes missing vs null
    assert "nickname" in m.model_dump(exclude_unset=True)
    assert "name" not in m.model_dump(exclude_unset=True)


def test_update_request_explicit_null_is_set():
    m = LightUpdateRequest.model_validate({"nickname": None})
    dumped = m.model_dump(exclude_unset=True)
    assert "nickname" in dumped
    assert dumped["nickname"] is None


def test_light_response_from_fields():
    m = LightResponse(
        id="11111111-1111-1111-1111-111111111111",
        name="Hue Iris",
        nickname=None,
        room=None,
        notes=None,
        bridge_light_id="2",
        eye_safety_limit_pct=None,
        enabled_for_app=True,
        deleted_at=None,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    assert m.bridge_light_id == "2"


def test_sync_response():
    m = LightsSyncResponse(
        created=1, updated=0, unchanged=2, skipped_deleted=0, total_bridge=3
    )
    assert m.total_bridge == 3
```

**Step 2: Run to fail**
```bash
uv run pytest tests/test_api_light_models.py -v --no-cov
```
Expected: ImportError for missing model names

**Step 3: Implement models**

Append to `marvin_hue/api/models.py` (file already imports `BaseModel`, `Field`, `field_validator`):

```python
class LightCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    nickname: str | None = Field(default=None, max_length=100)
    room: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)
    bridge_light_id: str | None = Field(default=None, max_length=64)
    eye_safety_limit_pct: int | None = Field(default=None, ge=0, le=100)
    enabled_for_app: bool = True

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("name must be non-empty")
        return cleaned


class LightUpdateRequest(BaseModel):
    """Partial update. Omitted fields stay unchanged; explicit null clears nullables."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    nickname: str | None = Field(default=None, max_length=100)
    room: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)
    bridge_light_id: str | None = Field(default=None, max_length=64)
    eye_safety_limit_pct: int | None = Field(default=None, ge=0, le=100)
    enabled_for_app: bool | None = None

    @field_validator("name")
    @classmethod
    def strip_name_optional(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("name must be non-empty")
        return cleaned


class LightResponse(BaseModel):
    id: str
    name: str
    nickname: str | None
    room: str | None
    notes: str | None
    bridge_light_id: str | None
    eye_safety_limit_pct: int | None
    enabled_for_app: bool
    deleted_at: str | None
    created_at: str
    updated_at: str


class LightsSyncResponse(BaseModel):
    created: int
    updated: int
    unchanged: int
    skipped_deleted: int = 0
    total_bridge: int
```

**Step 4: Verify**
```bash
uv run pytest tests/test_api_light_models.py -v --no-cov
```
Expected: all PASSED

**Step 5: Commit**

Use `jarvis-default-commit` skill to stage and commit changes.

**If Task Fails:**
1. Field validator conflicts with existing imports → ensure `field_validator` already imported in models.py

---

### Task 12: Dependencies (DI only)

**Files:**
- Modify: `marvin_hue/api/dependencies.py`
- Create: `tests/test_light_registry_di.py`

**Prerequisites:**
- Task 7 complete

**Step 1: Write failing test for DI**

Create `tests/test_light_registry_di.py`:

```python
"""Dependency injection smoke for light registry service."""

import pytest
from marvin_hue.api import dependencies
from marvin_hue.services.light_registry import LightRegistryService


def test_get_light_registry_service_raises_if_unset():
    original = getattr(dependencies, "_light_registry_service", None)
    dependencies._light_registry_service = None
    try:
        with pytest.raises(RuntimeError):
            dependencies.get_light_registry_service()
    finally:
        dependencies._light_registry_service = original


@pytest.mark.asyncio
async def test_set_and_get_light_registry_service(tmp_path):
    from marvin_hue.persistence.schema import init_db
    from marvin_hue.persistence.light_repository import SqliteLightRegistryRepository

    path = str(tmp_path / "di.sqlite")
    await init_db(path)
    repo = await SqliteLightRegistryRepository.open(path)
    svc = LightRegistryService(repo)
    dependencies.set_light_registry_service(svc)
    try:
        got = dependencies.get_light_registry_service()
        assert got is svc
    finally:
        dependencies.set_light_registry_service(None)
        await repo.close()
```

**Step 2: Run to fail**
```bash
uv run pytest tests/test_light_registry_di.py -v --no-cov
```
Expected: AttributeError missing setters/getters

**Step 3: Implement DI only**

In `marvin_hue/api/dependencies.py`, add:

```python
from marvin_hue.services.light_registry import LightRegistryService

_light_registry_service: LightRegistryService | None = None


def set_light_registry_service(service: LightRegistryService | None) -> None:
    global _light_registry_service
    _light_registry_service = service


def get_light_registry_service() -> LightRegistryService:
    if _light_registry_service is None:
        raise RuntimeError("LightRegistryService não inicializado")
    return _light_registry_service
```

**Step 4: Verify**
```bash
uv run pytest tests/test_light_registry_di.py -v --no-cov
```
Expected: all PASSED

**Step 5: Commit**

Use `jarvis-default-commit` skill to stage and commit changes.

**If Task Fails:**
1. Circular import service ↔ dependencies → import LightRegistryService only for type/runtime at bottom or keep as-is (services must not import dependencies)

---

### Task 13: Lifespan wiring (full replacement)

**Files:**
- Modify: `app.py` (lifespan init/close + import)

**Prerequisites:**
- Tasks 3, 4, 7, 12 complete; Task 8 for bridge protocol

**Step 1: Manual verification prep**

No unit test for lifespan alone (covered by API tests after Task 14–16). Diff carefully against current `app.py`.

**Step 2: Confirm current structure**

`app.py` uses `AsyncExitStack` for chat checkpointer, then `yield`, then screen_mirror shutdown. Registry must init before yield and close in `try/finally` around yield.

**Step 3: Replace lifespan + imports with this complete function**

Update imports near top of `app.py`:

```python
from marvin_hue.api.routes import status, configurations, positions, mirror, chat, lights  # noqa: E402
```

Replace the entire `lifespan` function with:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerencia o ciclo de vida da aplicação."""
    # Startup
    logger.info("Starting Marvin Hue application")
    logger.info(
        f"Configuration: bridge_ip={settings.bridge_ip}, api_port={settings.api_port}, log_level={settings.log_level}"
    )

    # Inicializa componentes principais
    hue = HueController(ip_address=settings.bridge_ip)
    manager = LightSetupsManager(settings.setups_file)
    screen_mirror = ScreenMirror(hue, settings.positions_file)

    # Registra dependências
    dependencies.set_hue_controller(hue)
    dependencies.set_manager(manager)
    dependencies.set_screen_mirror(screen_mirror)

    # App-owned lights registry (separate SQLite from chat checkpointer)
    from marvin_hue.persistence.schema import init_db
    from marvin_hue.persistence.light_repository import SqliteLightRegistryRepository
    from marvin_hue.services.light_registry import LightRegistryService

    light_repo: SqliteLightRegistryRepository | None = None
    try:
        await init_db(settings.app_db_path)
        light_repo = await SqliteLightRegistryRepository.open(settings.app_db_path)
        light_registry = LightRegistryService(light_repo, bridge=hue)
        dependencies.set_light_registry_service(light_registry)
        logger.info(f"Light registry initialized at {settings.app_db_path}")
    except Exception as e:
        logger.exception(f"Error initializing light registry: {e}")
        dependencies.set_light_registry_service(None)
        # Fail closed for registry: leave service unset so routes return 503/500
        # via RuntimeError → map in routes if desired. Prefer re-raise for hard fail:
        raise

    # Inicializa o agente de chat
    logger.info(
        f"Initializing chat agent with provider='{settings.chat_provider}', "
        f"model='{settings.chat_model}', checkpoint='{settings.chat_checkpoint}'"
    )

    # O ciclo de vida do checkpointer é do COMPOSITOR (este lifespan), não do
    # agente. Para sqlite usamos AsyncSqliteSaver — REQUERIDO sob concorrência de
    # sessões (FastAPI async); o SqliteSaver síncrono daria "database is locked".
    async with AsyncExitStack() as stack:
        checkpointer = None
        if settings.chat_checkpoint == "sqlite":
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
            checkpointer = await stack.enter_async_context(
                AsyncSqliteSaver.from_conn_string(settings.chat_checkpoint_db)
            )
        # Registra o checkpointer p/ que o reconfigure reuse o MESMO (não recaia
        # em InMemorySaver sob sqlite).
        dependencies.set_chat_checkpointer(checkpointer)

        try:
            chat_agent = create_hue_agent(
                controller=hue,
                manager=manager,
                provider=settings.chat_provider,
                model=settings.chat_model,
                temperature=settings.chat_temperature,
                checkpointer=checkpointer,
            )
            dependencies.set_chat_agent(chat_agent)
            logger.info("Chat agent initialized successfully")
        except Exception as e:
            logger.exception(f"Error initializing chat agent: {e}")
            # Diagnóstico para clientes da API (sem secrets): key ausente tem
            # prioridade; senão, primeira linha sanitizada da exceção.
            reason = dependencies.diagnose_chat_credentials(settings.chat_provider)
            if reason is None:
                sanitized = dependencies.sanitize_chat_init_error(e)
                reason = f"Falha ao inicializar agente: {sanitized}"
            dependencies.set_chat_agent(None, reason=reason)

        try:
            yield
        finally:
            if light_repo is not None:
                await light_repo.close()
            dependencies.set_light_registry_service(None)
    # Saída do AsyncExitStack fecha o AsyncSqliteSaver (se usado) no shutdown.

    # Shutdown
    logger.info("Shutting down Marvin Hue application")
    if screen_mirror and screen_mirror.is_running():
        screen_mirror.stop()
    logger.info("Application shutdown complete")
```

Register router **after** status (and before or after others is fine as long as status is first for `/api/lights/status`):

```python
app.include_router(status.router)
app.include_router(lights.router)
app.include_router(configurations.router)
app.include_router(positions.router)
app.include_router(mirror.router)
app.include_router(chat.router)
```

**Note:** `lights` router module is created in Task 15; if implementing lifespan before routes exist, add the import/include in Task 15 and only do registry DI here. **Executor order:** complete Task 13 lifespan **without** `lights` import if module missing, then Task 15 adds import+include. Prefer:

- Task 13: only registry init/close in lifespan (no `lights` import yet)
- Task 15: add `lights` import + `include_router`

**Step 4: Smoke import**
```bash
uv run python -c "import app; print('ok', app.app.title)"
```
Expected: `ok Marvin Hue Controller` (may connect bridge if Settings loads — use BRIDGE_IP in env)

Safer:
```bash
BRIDGE_IP=192.168.1.100 uv run python -c "from marvin_hue.api import dependencies; print(hasattr(dependencies, 'get_light_registry_service'))"
```
Expected: `True`

**Step 5: Commit**

Use `jarvis-default-commit` skill to stage and commit changes.

**If Task Fails:**
1. Init fails because path → ensure `.res/` creatable
2. Double-close repo → only close in finally once
3. Import lights missing → defer include_router to Task 15

---

### Task 14: Conftest TestClient + temp registry (single recipe)

**Files:**
- Modify: `tests/conftest.py` (`fastapi_test_client` only)

**Prerequisites:**
- Tasks 3, 4, 7, 8, 12 complete

**Step 1: Document the single bootstrap recipe**

Sync `TestClient` fixture has **no** running event loop. Use **only** `asyncio.run` for async bootstrap/teardown. Do **not** use `get_event_loop().run_until_complete`. Do **not** add “if flaky try anyio” branches.

**Step 2: Replace `fastapi_test_client` fixture**

Replace the existing `fastapi_test_client` in `tests/conftest.py` with:

```python
@pytest.fixture
def fastapi_test_client(
    mock_hue_controller,
    mock_light_setups_manager,
    mock_screen_mirror,
    monkeypatch,
    tmp_path,
) -> Generator:
    """Provides a FastAPI TestClient for integration tests.

    Bootstraps light registry on a temp SQLite via asyncio.run (sync fixture;
    no running loop under TestClient setup).
    """
    import asyncio

    monkeypatch.setenv("BRIDGE_IP", "192.168.1.100")
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "test_marvin_hue.sqlite"))

    from marvin_hue.api import dependencies
    import app

    original_hue = dependencies._hue_controller
    original_manager = dependencies._manager
    original_mirror = dependencies._screen_mirror
    original_chat = dependencies._chat_agent
    original_chat_reason = dependencies._chat_unavailable_reason
    original_registry = getattr(dependencies, "_light_registry_service", None)

    dependencies.set_hue_controller(mock_hue_controller)
    dependencies.set_manager(mock_light_setups_manager)
    dependencies.set_screen_mirror(mock_screen_mirror)
    dependencies.set_chat_agent(
        None, reason="Provider 'xai' sem XAI_API_KEY configurada."
    )

    db_path = str(tmp_path / "test_marvin_hue.sqlite")

    async def _bootstrap():
        from marvin_hue.persistence.schema import init_db
        from marvin_hue.persistence.light_repository import (
            SqliteLightRegistryRepository,
        )
        from marvin_hue.services.light_registry import LightRegistryService

        await init_db(db_path)
        repo = await SqliteLightRegistryRepository.open(db_path)
        return LightRegistryService(repo, bridge=mock_hue_controller)

    service = asyncio.run(_bootstrap())
    dependencies.set_light_registry_service(service)

    client = TestClient(app.app)
    yield client

    async def _teardown():
        await service.aclose()

    asyncio.run(_teardown())
    dependencies._hue_controller = original_hue
    dependencies._manager = original_manager
    dependencies._screen_mirror = original_mirror
    dependencies._chat_agent = original_chat
    dependencies._chat_unavailable_reason = original_chat_reason
    dependencies._light_registry_service = original_registry
```

Ensure `Generator` is imported from `typing` (already is in conftest).

**Step 3: Verify existing API tests still pass**
```bash
uv run pytest tests/test_api.py tests/test_light_registry_di.py -q --no-cov
```
Expected: PASS (or only pre-existing failures unrelated to registry)

**Step 4: N/A code beyond conftest**

**Step 5: Commit**

Use `jarvis-default-commit` skill to stage and commit changes.

**If Task Fails:**
1. `asyncio.run` complains about running loop → should not happen in sync TestClient fixture; do not invent alternate recipes
2. Service aclose missing → Task 7 must define `aclose`
3. Import app triggers settings without BRIDGE_IP → fixture sets env before `import app` if needed; current conftest imports app after setenv

---

### Task 15: REST routes — list/create/get/update/delete + route order

**Files:**
- Create: `marvin_hue/api/routes/lights.py`
- Modify: `app.py` (include_router after status; import lights)
- Create: `tests/test_api_lights_registry.py`

**Prerequisites:**
- Tasks 11–14 complete

**Step 1: Write failing API tests**

Create `tests/test_api_lights_registry.py`:

```python
"""API tests for /api/lights registry CRUD."""


class TestLightsRegistryCRUD:
    def test_list_empty(self, fastapi_test_client):
        r = fastapi_test_client.get("/api/lights")
        assert r.status_code == 200
        body = r.json()
        assert body == []

    def test_create_and_get(self, fastapi_test_client):
        r = fastapi_test_client.post(
            "/api/lights",
            json={
                "name": "Lâmpada 1",
                "nickname": "Mesa",
                "room": "Escritório",
                "eye_safety_limit_pct": None,
            },
        )
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["name"] == "Lâmpada 1"
        assert data["nickname"] == "Mesa"
        light_id = data["id"]

        r2 = fastapi_test_client.get(f"/api/lights/{light_id}")
        assert r2.status_code == 200
        assert r2.json()["id"] == light_id

    def test_list_after_create(self, fastapi_test_client):
        fastapi_test_client.post("/api/lights", json={"name": "Hue Iris"})
        r = fastapi_test_client.get("/api/lights")
        assert r.status_code == 200
        names = [x["name"] for x in r.json()]
        assert "Hue Iris" in names

    def test_patch_metadata(self, fastapi_test_client):
        created = fastapi_test_client.post(
            "/api/lights", json={"name": "Hue Play 1"}
        ).json()
        r = fastapi_test_client.patch(
            f"/api/lights/{created['id']}",
            json={"nickname": "Esquerda", "enabled_for_app": False},
        )
        assert r.status_code == 200
        assert r.json()["nickname"] == "Esquerda"
        assert r.json()["enabled_for_app"] is False

    def test_patch_clear_nickname_with_null(self, fastapi_test_client):
        created = fastapi_test_client.post(
            "/api/lights", json={"name": "NullNick", "nickname": "Temp"}
        ).json()
        assert created["nickname"] == "Temp"
        r = fastapi_test_client.patch(
            f"/api/lights/{created['id']}",
            json={"nickname": None},
        )
        assert r.status_code == 200, r.text
        assert r.json()["nickname"] is None

    def test_delete_soft(self, fastapi_test_client):
        created = fastapi_test_client.post(
            "/api/lights", json={"name": "Fita Led"}
        ).json()
        r = fastapi_test_client.delete(f"/api/lights/{created['id']}")
        assert r.status_code == 200
        assert r.json()["deleted_at"] is not None

        r2 = fastapi_test_client.get(f"/api/lights/{created['id']}")
        assert r2.status_code == 404

        r3 = fastapi_test_client.get("/api/lights?include_deleted=true")
        assert r3.status_code == 200
        deleted = [x for x in r3.json() if x["id"] == created["id"]]
        assert len(deleted) == 1

    def test_get_missing_404(self, fastapi_test_client):
        r = fastapi_test_client.get(
            "/api/lights/00000000-0000-0000-0000-000000000000"
        )
        assert r.status_code == 404

    def test_create_duplicate_409(self, fastapi_test_client):
        fastapi_test_client.post("/api/lights", json={"name": "DupLight"})
        r = fastapi_test_client.post("/api/lights", json={"name": "DupLight"})
        assert r.status_code == 409

    def test_live_status_endpoint_still_exists(self, fastapi_test_client):
        """Do not break GET /api/lights/status (live Hue state)."""
        r = fastapi_test_client.get("/api/lights/status")
        assert r.status_code == 200
        assert "lights" in r.json()
```

**Step 2: Run to fail**
```bash
uv run pytest tests/test_api_lights_registry.py -v --no-cov
```
Expected: 404 on `/api/lights` (route missing)

**Step 3: Implement routes**

Create `marvin_hue/api/routes/lights.py`:

```python
"""Lights registry routes (app catalog CRUD + bridge sync).

Live Hue state remains at GET /api/lights/status (status router).
Static paths (/api/lights, /api/lights/sync) must be declared before /{light_id}.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from marvin_hue.api.dependencies import get_light_registry_service
from marvin_hue.api.models import (
    LightCreateRequest,
    LightResponse,
    LightUpdateRequest,
    LightsSyncResponse,
)
from marvin_hue.domain.lights import (
    LightConflictError,
    LightNotFoundError,
    LightValidationError,
    RegisteredLight,
)
from marvin_hue.services.light_registry import LightRegistryService

router = APIRouter(tags=["Lights Registry"])


def _dt_iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat()


def to_response(light: RegisteredLight) -> LightResponse:
    return LightResponse(
        id=light.id,
        name=light.name,
        nickname=light.nickname,
        room=light.room,
        notes=light.notes,
        bridge_light_id=light.bridge_light_id,
        eye_safety_limit_pct=light.eye_safety_limit_pct,
        enabled_for_app=light.enabled_for_app,
        deleted_at=_dt_iso(light.deleted_at),
        created_at=_dt_iso(light.created_at) or "",
        updated_at=_dt_iso(light.updated_at) or "",
    )


def _http_from_validation(exc: LightValidationError) -> HTTPException:
    if isinstance(exc, LightConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/api/lights", response_model=list[LightResponse])
async def list_registered_lights(
    include_deleted: bool = Query(default=False),
    svc: LightRegistryService = Depends(get_light_registry_service),
):
    lights = await svc.list_lights(include_deleted=include_deleted)
    return [to_response(x) for x in lights]


@router.post(
    "/api/lights",
    response_model=LightResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_registered_light(
    body: LightCreateRequest,
    svc: LightRegistryService = Depends(get_light_registry_service),
):
    try:
        light = await svc.create_light(
            name=body.name,
            nickname=body.nickname,
            room=body.room,
            notes=body.notes,
            bridge_light_id=body.bridge_light_id,
            eye_safety_limit_pct=body.eye_safety_limit_pct,
            enabled_for_app=body.enabled_for_app,
        )
    except LightValidationError as exc:
        raise _http_from_validation(exc) from exc
    return to_response(light)


# Sync is registered in Task 16 BEFORE /{light_id} — placeholder path reserved:
# POST /api/lights/sync


@router.get("/api/lights/{light_id}", response_model=LightResponse)
async def get_registered_light(
    light_id: str,
    svc: LightRegistryService = Depends(get_light_registry_service),
):
    try:
        light = await svc.get_light(light_id)
    except LightNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return to_response(light)


@router.patch("/api/lights/{light_id}", response_model=LightResponse)
async def update_registered_light(
    light_id: str,
    body: LightUpdateRequest,
    svc: LightRegistryService = Depends(get_light_registry_service),
):
    # Only pass fields explicitly set by client (null clears nullables)
    data = body.model_dump(exclude_unset=True)
    try:
        light = await svc.update_light(light_id, **data)
    except LightNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LightValidationError as exc:
        raise _http_from_validation(exc) from exc
    return to_response(light)


@router.delete("/api/lights/{light_id}", response_model=LightResponse)
async def delete_registered_light(
    light_id: str,
    svc: LightRegistryService = Depends(get_light_registry_service),
):
    try:
        light = await svc.delete_light(light_id)
    except LightNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return to_response(light)
```

Wire in `app.py` (import + include order):

```python
from marvin_hue.api.routes import status, configurations, positions, mirror, chat, lights  # noqa: E402

app.include_router(status.router)
app.include_router(lights.router)
app.include_router(configurations.router)
app.include_router(positions.router)
app.include_router(mirror.router)
app.include_router(chat.router)
```

**Step 4: Verify**
```bash
uv run pytest tests/test_api_lights_registry.py -v --no-cov
```
Expected: all PASSED (sync tests not yet present)

**Step 5: Commit**

Use `jarvis-default-commit` skill to stage and commit changes.

**If Task Fails:**
1. RuntimeError LightRegistryService → conftest DI not wired (Task 14)
2. 404 on status → ensure `status.router` registered before `lights.router`
3. PATCH null not clearing → ensure `exclude_unset=True` and service `_UNSET` defaults
4. Duplicate returns 400 → map `LightConflictError` to 409

---

### Task 16: POST /api/lights/sync + refresh_and_sync only

**Files:**
- Modify: `marvin_hue/api/routes/lights.py` (add sync route **before** `/{light_id}`)
- Modify: `tests/test_api_lights_registry.py`

**Prerequisites:**
- Task 15 complete; Task 9 complete

**Step 1: Write failing tests**

Append to `tests/test_api_lights_registry.py`:

```python
class TestLightsSync:
    def test_sync_from_bridge(self, fastapi_test_client, mock_hue_controller):
        for i, light in enumerate(mock_hue_controller.lights, start=1):
            light.uniqueid = f"00:17:88:aa:{i:02d}"
            light.light_id = i
        r = fastapi_test_client.post("/api/lights/sync")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total_bridge"] >= 1
        assert (
            body["created"]
            + body["updated"]
            + body["unchanged"]
            + body.get("skipped_deleted", 0)
            == body["total_bridge"]
        )

        listed = fastapi_test_client.get("/api/lights").json()
        names = {x["name"] for x in listed}
        for light in mock_hue_controller.lights:
            assert light.name in names

    def test_sync_idempotent(self, fastapi_test_client, mock_hue_controller):
        for i, light in enumerate(mock_hue_controller.lights, start=1):
            light.uniqueid = f"00:17:88:bb:{i:02d}"
            light.light_id = i
        fastapi_test_client.post("/api/lights/sync")
        r2 = fastapi_test_client.post("/api/lights/sync")
        assert r2.status_code == 200
        assert r2.json()["created"] == 0

    def test_sync_path_not_captured_as_light_id(self, fastapi_test_client):
        """POST /api/lights/sync must not be treated as GET/POST /{light_id}='sync'."""
        r = fastapi_test_client.post("/api/lights/sync")
        # 200 success or 503 if bridge broken — never 422 path validation for UUID
        assert r.status_code in (200, 503)
        assert r.status_code != 404

    def test_sync_soft_deleted_not_revived_by_default(
        self, fastapi_test_client, mock_hue_controller
    ):
        for i, light in enumerate(mock_hue_controller.lights, start=1):
            light.uniqueid = f"00:17:88:cc:{i:02d}"
        fastapi_test_client.post("/api/lights/sync")
        listed = fastapi_test_client.get("/api/lights").json()
        assert listed
        lid = listed[0]["id"]
        fastapi_test_client.delete(f"/api/lights/{lid}")
        r = fastapi_test_client.post("/api/lights/sync")
        assert r.status_code == 200
        active = fastapi_test_client.get("/api/lights").json()
        assert all(x["id"] != lid for x in active)

    def test_sync_reactivate_deleted_query(
        self, fastapi_test_client, mock_hue_controller
    ):
        for i, light in enumerate(mock_hue_controller.lights, start=1):
            light.uniqueid = f"00:17:88:dd:{i:02d}"
        fastapi_test_client.post("/api/lights/sync")
        listed = fastapi_test_client.get("/api/lights").json()
        lid = listed[0]["id"]
        fastapi_test_client.delete(f"/api/lights/{lid}")
        r = fastapi_test_client.post(
            "/api/lights/sync", params={"reactivate_deleted": True}
        )
        assert r.status_code == 200
        active_ids = {x["id"] for x in fastapi_test_client.get("/api/lights").json()}
        assert lid in active_ids
```

**Step 2: Run to fail**
```bash
uv run pytest tests/test_api_lights_registry.py::TestLightsSync -v --no-cov
```
Expected: 404 / method not allowed for `/api/lights/sync`

**Step 3: Implement sync route (only path — no `svc._bridge`)**

In `marvin_hue/api/routes/lights.py`, place this **immediately after** `create_registered_light` and **before** `@router.get("/api/lights/{light_id}")`:

```python
@router.post("/api/lights/sync", response_model=LightsSyncResponse)
async def sync_lights_from_bridge(
    reactivate_deleted: bool = Query(default=False),
    svc: LightRegistryService = Depends(get_light_registry_service),
):
    """Upsert registry from Hue bridge inventory.

    Soft-deleted rows are not reactivated unless reactivate_deleted=true.
    """
    try:
        result = await svc.refresh_and_sync(reactivate_deleted=reactivate_deleted)
    except LightValidationError as exc:
        # Missing bridge / refresh failure — generic 503, no raw internal strings required
        raise HTTPException(
            status_code=503,
            detail="Light registry sync unavailable",
        ) from exc
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Internal error during light registry sync",
        )
    return LightsSyncResponse(**result)
```

**Never** access `svc._bridge` from the route. **Never** put `str(exc)` in 500/503 details.

**Step 4: Verify**
```bash
uv run pytest tests/test_api_lights_registry.py -v --no-cov
```
Expected: all PASSED

**Step 5: Commit**

Use `jarvis-default-commit` skill to stage and commit changes.

**If Task Fails:**
1. Sync 503 bridge not configured → DI must pass `bridge=mock_hue_controller`
2. Path captured as light_id → move `@router.post("/api/lights/sync")` above `/{light_id}`
3. 500 with exception text → remove detail=str(exc)

---

### Task 17: Code Review Checkpoint C

1. **REQUIRED SUB-SKILL:** Use jarvis-default-codereview — dispatch all reviewers in parallel
2. **Scope:** `api/routes/lights.py`, models, dependencies, app.py lifespan, conftest, API tests
3. **Handle findings by severity**
4. **Proceed only when:** zero Critical/High/Medium issues remain

---

## Phase 3 — Docs + regression

### Task 18: Documentation updates

**Files:**
- Modify: `docs/API.md` (new section Lights Registry)
- Modify: `docs/CONFIGURATION.md` (APP_DB_PATH)
- Modify: `docs/ARCHITECTURE.md` (short persistence paragraph) — only if a natural place exists; keep minimal
- Modify: `.env.example` if not fully done in Task 1

**Prerequisites:**
- API routes complete

**Step 1: Write doc content (no automated test; manual verification)**

Add to `docs/API.md` index and new section:

```markdown
## Catálogo de Lâmpadas (Registry)

Catálogo app-side em SQLite (`.res/marvin_hue.sqlite`). Não altera o estado
físico na bridge. Soft-delete apenas no catálogo.

Live state continua em `GET /api/lights/status`.

Identidade no sync: `bridge_light_id` (preferir Hue `uniqueid`) depois `name`.
Soft-deleted **não** é reativado no sync por padrão; use
`POST /api/lights/sync?reactivate_deleted=true` para reativar.

Segurança v1: igual ao restante da API (sem API_KEY obrigatória; rede LAN confiável).

### GET /api/lights

Query: `include_deleted` (bool, default false)

### GET /api/lights/{light_id}

### POST /api/lights

Body: LightCreateRequest. Conflito de nome ativo → **409**.

### PATCH /api/lights/{light_id}

Body: LightUpdateRequest (partial). Campo omitido = inalterado; `null` limpa
campos anuláveis (`nickname`, `room`, `notes`, `bridge_light_id`,
`eye_safety_limit_pct`).

### DELETE /api/lights/{light_id}

Soft-delete. Não remove a lâmpada na bridge Hue.

### POST /api/lights/sync

Query: `reactivate_deleted` (bool, default false)

Upsert a partir do inventário atual da bridge
(`HueController.list_bridge_lights` → `LightRegistryService.refresh_and_sync`).
```

Add to `docs/CONFIGURATION.md`:

```markdown
#### `APP_DB_PATH`

Caminho do SQLite da aplicação (catálogo de lâmpadas). Preferir sob `.res/`.

```bash
APP_DB_PATH=.res/marvin_hue.sqlite
```

**Importante:** não use o mesmo arquivo de `CHAT_CHECKPOINT_DB`
(`.res/chat_memory.sqlite`). Settings rejeita colisão de path e o basename
`chat_memory.sqlite`.
```

**Step 2: Verify docs**
```bash
test -f docs/API.md && rg -n "Catálogo de Lâmpadas|/api/lights/sync|APP_DB_PATH|reactivate_deleted" docs/
```
Expected: matches in API.md and CONFIGURATION.md

**Step 3: No code implementation beyond docs**

**Step 4: N/A**

**Step 5: Commit**

Use `jarvis-default-commit` skill to stage and commit changes.

**If Task Fails:**
1. Doc path wrong → project uses `docs/API.md` (confirmed)

---

### Task 19: Full regression suite + manual smoke checklist

**Files:**
- None new (run commands only)
- Optional fix only if regressions found in this feature's files

**Prerequisites:**
- All previous tasks complete

**Step 1: Run focused suite**
```bash
uv run pytest \
  tests/test_domain_lights.py \
  tests/test_persistence_schema.py \
  tests/test_light_repository.py \
  tests/test_light_registry_service.py \
  tests/test_light_registry_di.py \
  tests/test_api_light_models.py \
  tests/test_api_lights_registry.py \
  tests/test_config.py \
  -v --no-cov
```
Expected: all PASSED

**Step 2: Run broader regression (may include unrelated failures from WIP)**
```bash
uv run pytest tests/test_api.py tests/test_controllers.py tests/test_config.py -q --no-cov
```
Expected: PASS for green baseline; if unrelated WIP fails, note and do not "fix" unrelated modules unless trivial

**Step 3: Manual smoke (optional, needs bridge)**
```bash
# with .env BRIDGE_IP set
uv run uvicorn app:app --port 5081
curl -s http://127.0.0.1:5081/api/lights | jq .
curl -s -X POST http://127.0.0.1:5081/api/lights/sync | jq .
curl -s http://127.0.0.1:5081/api/lights | jq .
curl -s http://127.0.0.1:5081/api/lights/status | jq .  # still live state
curl -s -X PATCH http://127.0.0.1:5081/api/lights/<id> -H 'Content-Type: application/json' -d '{"nickname":null}' | jq .
```
Expected: sync creates rows; status still returns live on/off/color; null nickname clears

**Step 4: Confirm DB isolation**
```bash
# after sync
sqlite3 .res/marvin_hue.sqlite ".tables"
# Expected: lights  schema_version
# And chat file (if exists) has different tables — no lights table there:
sqlite3 .res/chat_memory.sqlite ".tables" 2>/dev/null || true
```

**Step 5: Final commit if any doc/test polish**

Use `jarvis-default-commit` skill.

**If Task Fails:**
1. Focus suite fails → fix only registry files
2. Unrelated suite fails → document; do not expand scope

---

### Task 20: Code Review Checkpoint D (final)

1. **REQUIRED SUB-SKILL:** Use jarvis-default-codereview — dispatch all reviewers in parallel
2. **Scope:** entire feature diff vs main/base
3. **Handle findings by severity**
4. **Proceed only when:** zero Critical/High/Medium issues remain

---

## Definition of Done

This feature is done when **all** of the following hold:

1. Focused pytest suite in Task 19 Step 1 is green.
2. `GET /api/lights/status` still returns live Hue state (200) and is not shadowed by registry routes.
3. `POST /api/lights/sync` is not captured as `/{light_id}` and implements safe soft-delete policy (no auto-revive without `reactivate_deleted=true`).
4. Active name conflicts return **409**; validation errors **400**; missing **404**; bridge/sync unavailable **503** without raw exception strings on 5xx.
5. PATCH with explicit `null` clears nullable fields; omitted fields leave values unchanged.
6. App DB file is `.res/marvin_hue.sqlite` (or configured path) and never shares tables/file with `chat_memory.sqlite`.
7. Docs (`docs/API.md`, `docs/CONFIGURATION.md`) describe registry endpoints, sync identity, soft-delete policy, and `APP_DB_PATH`.

---

## Reference: entity field dictionary

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| id | UUID str | yes | App-generated |
| name | str | yes | Unique among non-deleted; matches Hue/setup names |
| nickname | str? | no | Display alias; PATCH null clears |
| room | str? | no | Free label; PATCH null clears |
| notes | str? | no | Free text; PATCH null clears |
| bridge_light_id | str? | no | Prefer phue `uniqueid`, else `light_id` |
| eye_safety_limit_pct | int? 0–100 | no | Stored only; clamp still uses `eye_safety.py` in v1 |
| enabled_for_app | bool | yes default true | App feature gate; not nullable |
| deleted_at | datetime? | no | Soft-delete |
| created_at / updated_at | datetime | yes | UTC ISO in API |

---

## Reference: file checklist

| Path | Action |
|------|--------|
| `pyproject.toml` | Add aiosqlite direct dep |
| `marvin_hue/config.py` | `app_db_path` + isolation validator |
| `.gitignore` | Ignore marvin_hue.sqlite* |
| `.env.example` | Document APP_DB_PATH |
| `marvin_hue/domain/__init__.py` | Create |
| `marvin_hue/domain/lights.py` | Create |
| `marvin_hue/persistence/__init__.py` | Create |
| `marvin_hue/persistence/schema.py` | Create (+ WAL) |
| `marvin_hue/persistence/light_repository.py` | Create (lock + ordered lookups) |
| `marvin_hue/services/__init__.py` | Create |
| `marvin_hue/services/light_registry.py` | Create (CRUD + sync policy) |
| `marvin_hue/controllers.py` | Add `list_bridge_lights` |
| `marvin_hue/api/models.py` | Add request/response models |
| `marvin_hue/api/dependencies.py` | Registry DI |
| `marvin_hue/api/routes/lights.py` | Create router |
| `app.py` | Lifespan init + include_router after status |
| `tests/conftest.py` | Temp DB for TestClient (`asyncio.run` only) |
| `tests/test_*.py` (new) | As listed per task |
| `docs/API.md`, `docs/CONFIGURATION.md` | Document |

---

## Non-goals reminder (do not implement in this plan)

- Migrating `setups.json` / `light_positions.json` into SQLite
- Replacing `EYE_SAFETY_LIMITS` code map with DB-driven clamp
- Alembic, SQLAlchemy, Postgres
- Multi-user auth / API_KEY enforcement (document only)
- Web UI for registry (optional later)
- Deleting lights from the Hue bridge
- Putting tables into `chat_memory.sqlite`
- Auto-reactivating soft-deleted lights on sync without explicit flag

---

## Plan Checklist

- [x] Header with goal, architecture, tech stack, prerequisites
- [x] Validation amendments section (2026-08-08)
- [x] Verification commands with expected output
- [x] Tasks broken into 2-5 min bite-sized steps (~20 tasks)
- [x] Exact file paths for all files
- [x] Complete code (no placeholders / no dual recipes)
- [x] Commands with expected output
- [x] Failure recovery steps per task
- [x] Code review checkpoints (Tasks 6, 10, 17, 20)
- [x] Definition of Done (7 bullets)
- [x] Sync identity, soft-delete policy, PATCH _UNSET, lock, route order fixed
- [x] Passes Zero-Context Test
