# Hue Entertainment Music/Sync Upgrade Implementation Plan

> **For Agents:** Implement this plan task-by-task following the structure below; review between tasks via jarvis-default-codereview.  
> **Do not reverse-engineer the official Philips Hue Sync / mobile app.** Use only documented Hue Entertainment protocol + OSS clients.

**Goal:** Close the quality gap between Marvin Hue audio/screen mirroring and the official Hue Sync experience by streaming colors over the **Hue Entertainment API** (DTLS/HueStream) instead of REST/`phue`, while keeping software audio analysis and a safe REST fallback.

**Architecture:** Introduce a dual-transport **output port** (`LightOutputPort`) so `AudioMirror` and optionally `ScreenMirror` push per-frame RGB frames without knowing REST vs Entertainment. Prefer the OSS library [`hue-entertainment`](https://github.com/music-assistant/hue-entertainment) (`EntertainmentSession` / `LightColorCommand`, HueStream v2 RGB, ~25–50 Hz) for DTLS-PSK streaming. Keep `HueController` + `phue` for presets, registry sync, on/off, and as automatic fallback when Entertainment is disabled, unpaired, or the stream fails. Map registry / `light_positions.json` names ↔ entertainment area **channels**. Credentials (`app_key` + DTLS `clientkey`) live in env / a dedicated secrets file — **never** in chat SQLite. Feature flag `ENTERTAINMENT_ENABLED` (default off until pairing succeeds). Eye safety + `enabled_for_app` still clamp brightness **before** any frame is sent.

**Tech Stack:**
- Python 3.11+ required for `hue-entertainment` (runtime today is 3.13; bump `requires-python` when adding the dep)
- Existing: FastAPI, `phue` (`HueController`), `AudioMirror` + `audio_engine` (numpy FFT multi-band + beat + HSV), `ScreenMirror` (mss/Pillow), SQLite light registry, Jinja2 mirror UI
- New: `hue-entertainment` (+ its deps `aiohttp`, `cryptography`, `zeroconf` — often already transitive)
- Tests: pytest + mocks; **no real bridge required for CI**

**Out of scope (non-goals — do not implement):**
- Reverse-engineering the official Hue Sync / Hue mobile app
- Native mobile apps, Hue Sync Box hardware emulation
- Postgres / multi-bridge / multi-user OAuth
- Replacing `phue` for non-streaming control (presets, chat tools, schedules stay on REST)
- Reimplementing full HyperHDR pipeline; only a thin Entertainment path for screen region colors
- Storing Entertainment credentials in chat checkpointer DB (`.res/chat_memory.sqlite`) or app catalog DB as free-form secrets without isolation

**Problem statement (why this plan exists):**
- Official app feels much better for music because it uses the **Entertainment streaming API** (UDP + DTLS + HueStream), not REST.
- REST via `phue` is rate-limited (~10–25 updates/s shared), cannot stop cleanly from other apps, and floods state — Philips documents that continuous fast updates **must not** use REST.
- Current Marvin path: `AudioMirror._apply_color_to_light` → `HueController.set_light_color` → REST XY/brightness per light per change. Analysis quality improved (`audio_engine.entertainment_color`), but transport remains the bottleneck.

**OSS / docs references (read in Phase 0):**

| Resource | URL | Role |
|----------|-----|------|
| Hue Entertainment API (official) | https://developers.meethue.com/develop/hue-entertainment/hue-entertainment-api/ | Protocol, areas, streaming rules |
| Hue API v2 core | https://developers.meethue.com/develop/hue-api-v2/ | CLIP v2 entertainment resources |
| music-assistant/hue-entertainment | https://github.com/music-assistant/hue-entertainment | Preferred Python async DTLS client |
| Music Assistant Hue plugin | https://www.music-assistant.io/plugins/hue-entertainment/ | Productized usage notes |
| rschio/huestream | https://github.com/rschio/huestream | Go reference implementation |
| YourRobotOverlord/hui | https://github.com/YourRobotOverlord/hui | Audio → Entertainment (Windows) |
| HyperHDR | https://github.com/awawa-dev/HyperHDR | Screen+audio + Hue Ent v2 (inspiration only) |
| openhue-api | https://github.com/openhue/openhue-api | CLIP/OpenAPI reference |
| aiohue | https://github.com/home-assistant-libs/aiohue | HA async bridge client (REST/v2 patterns) |
| IoTech blog (DTLS overview) | https://iotech.blog/posts/philips-hue-entertainment-api/ | Informal DTLS/HueStream walkthrough |

**Existing anchors (do not reinvent):**

| Concern | Path |
|---------|------|
| Settings / env | `marvin_hue/config.py`, `.env.example` |
| REST controller | `marvin_hue/controllers.py` (`set_light_color`, eye safety clamp) |
| Eye safety | `marvin_hue/eye_safety.py` (`clamp_eye_safety`, `is_enabled_for_app`) |
| Audio analysis | `marvin_hue/audio_engine.py` (`AudioAnalyzer`, `entertainment_color`, `AnalysisFrame`) |
| Audio mirror loop | `marvin_hue/audio_mirror.py` (`AudioMirror`, `_apply_color_to_light`, profiles party/chill/pulse) |
| Screen mirror | `marvin_hue/screen_mirror.py` (`ScreenMirror`, `_apply_color_to_light`) |
| Positions map | `.res/light_positions.json` via `settings.positions_file` |
| Light registry | `marvin_hue/domain/lights.py`, `marvin_hue/services/light_registry.py` |
| DI / lifespan | `marvin_hue/api/dependencies.py`, `app.py` |
| Mirror API + mutual exclusion | `marvin_hue/api/routes/mirror.py` (`_active_mode`, `_stop_if_running`) |
| Mirror UI | `web/templates/mirror.html`, `web/static/mirror.js` |
| API models | `marvin_hue/api/models.py` |
| Tests | `tests/test_audio_mirror.py`, `tests/test_audio_engine.py`, `tests/test_audio_mirror_api.py`, `tests/test_mirror_profiles.py`, `tests/test_screen_mirror_enabled.py`, `tests/test_controller_eye_safety.py` |
| Docs | `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/CONFIGURATION.md` |

**Global Prerequisites:**
- Environment: Linux (PulseAudio/PipeWire for audio capture), project root `/run/media/marvinbraga/dados-linux/marvin/my_phillips_hue`
- Tools: `uv`, `git`, `uv run pytest`
- Access: Hue Bridge on LAN; **Entertainment area** must be created once in the official Hue app (user action — not automated in v1 of this plan)
- Bridge: square V2 or Pro recommended (`hue-entertainment` targets these)
- Link button press required once for Entertainment pairing (`username` + `clientkey`)
- Constraints: DRY/YAGNI/TDD; keep CI bridge-free; do not break existing audio REST path when flag is off

**Verification before starting:**
```bash
cd /run/media/marvinbraga/dados-linux/marvin/my_phillips_hue
python --version   # Expected: Python 3.11+ (3.13 OK)
uv --version       # Expected: uv 0.x
git status         # Expected: clean enough to branch/commit
uv run pytest tests/test_audio_engine.py tests/test_audio_mirror.py tests/test_audio_mirror_api.py tests/test_controller_eye_safety.py -q --no-cov
# Expected: all PASSED
```

**Effort estimates (calendar, one engineer familiar with the repo):**

| Phase | Effort | Notes |
|-------|--------|-------|
| 0 Research / spike | 0.5–1 day | Docs + PoC script; no product merge required |
| 1 Entertainment client | 1–2 days | Pairing, areas, stream start/stop, channel map, credentials |
| 2 Dual transport | 1–2 days | Port + adapters + AudioMirror wiring + fallback |
| 3 Audio quality | 0.5–1 day | Intensity profiles, stereo→layout; mostly software |
| 4 Screen via Entertainment | 0.5–1 day | Optional; after Phase 2 stable |
| 5 UI/API/docs | 1 day | Mirror page + status fields + CONFIGURATION/API |
| 6 Tests & safety | 1 day | Mocks, exclusion, eye safety on stream path |
| **Total** | **~5–9 days** | Can ship Phases 1–3+6 first for music win |

**Parallel execution map:**
```
Phase 0 (spike) ──► Phase 1 (client + creds + flag)
                         │
                         ▼
                    Phase 2 (LightOutputPort + fallback)
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
         Phase 3     Phase 4     Phase 5
         (audio)   (screen opt)  (UI/API)
              └──────────┬──────────┘
                         ▼
                    Phase 6 (tests/safety harden)
```

**Definition of Done (product):**
1. With `ENTERTAINMENT_ENABLED=true` and valid credentials + entertainment area, `POST /mirror/start` with `mode=audio` streams via DTLS; `/mirror/status` reports `transport=entertainment`, area name, and effective fps.
2. Bridge lights update smoothly at ≥25 Hz for multi-light areas (subjective: clearly closer to official Sync than REST).
3. If stream fails or flag is false, audio still works via REST (`transport=rest`) without crashing the app.
4. Eye safety / `enabled_for_app` applied to stream colors; disabled lights never appear in frames.
5. Screen and audio (and entertainment stream) remain mutually exclusive sessions.
6. CI green with **mocked** stream only; no bridge in pytest.
7. Docs updated: setup of entertainment group in Hue app, env vars, API status fields.
8. Official app is **not** reverse-engineered; dependency is OSS + public Hue docs.

---

## Decision log / validation amendments

| ID | Decision | Rationale | Date |
|----|----------|-----------|------|
| D1 | Prefer `hue-entertainment` over hand-rolled DTLS | Pure-Python DTLS-PSK + HueStream v2, async facade, Apache-2.0, powers Music Assistant | 2026-08-08 |
| D2 | Dual transport, not full phue removal | Presets/chat/schedules need REST; Entertainment is for high-rate frames only | 2026-08-08 |
| D3 | Entertainment areas created in Hue app (manual) | Creating areas via CLIP is possible later; v1 reduces risk (YAGNI) | 2026-08-08 |
| D4 | Credentials: env vars + optional JSON file under `.res/`, gitignored | Not chat SQLite; not mixed into light registry rows | 2026-08-08 |
| D5 | Feature flag default **false** | Safe for users without pairing; REST path unchanged | 2026-08-08 |
| D6 | Bump `requires-python` to `>=3.11` when adding package | `hue-entertainment` requires 3.11+; project already runs 3.13 | 2026-08-08 |
| D7 | Intensity profiles map onto existing audio profiles first | Avoid new UI surface until Ent transport works; optional `subtle/moderate/high/extreme` aliases in Phase 3 | 2026-08-08 |
| D8 | Screen Entertainment is Phase 4 optional | Music quality gap is primary user pain | 2026-08-08 |
| D9 | Channel map by light name / bridge id, positions inform stereo layout | Entertainment channel order is area-defined; positions still drive **color roles** | 2026-08-08 |

**Open questions resolved by defaults (revisit only if blocked):**
- **Sync vs async stream send from AudioMirror thread:** use thread-safe `send` on `EntertainmentSession` (library documents non-blocking send) or a small queue drained by asyncio; implementer chooses based on Phase 0 spike notes — prefer **queue + dedicated sender** if `send` is not thread-safe.
- **HueStream color space:** library uses 16-bit RGB commands; convert 0–255 → 0–65535 by `* 257` (or `<< 8 | value`).

---

## Phase 0 — Research / spike (read-only + PoC)

**Goal:** Confirm protocol assumptions, API surface of `hue-entertainment`, and that the user's bridge has an entertainment area. **No production wiring.**

**Effort:** 0.5–1 day

### Task 0.1: Read official Entertainment docs (checklist)

**Files:** none (notes only — append to this plan's Decision log if facts change)

**Step 1:** Open and skim:
- https://developers.meethue.com/develop/hue-entertainment/hue-entertainment-api/
- https://developers.meethue.com/develop/hue-api-v2/ (entertainment configuration resources)
- https://github.com/music-assistant/hue-entertainment/blob/main/README.md

**Step 2:** Record answers in a short spike note file:

**Create:** `docs/plans/spikes/2026-08-08-entertainment-spike.md`

```markdown
# Entertainment spike notes

## Bridge
- Model / firmware: (fill)
- Entertainment areas present: yes/no (names, channel counts)
- Max concurrent streams: 1 (expected)

## hue-entertainment API used
- pair() → username + clientkey
- get_entertainment_areas() → id, channels[]
- EntertainmentSession.start(area_id) / send / aclose

## Risks
- ...
```

**Step 3:** In Hue mobile app: ensure at least one **Entertainment area** exists with the lights you want for music/sync. Note area name.

**If Task Fails:** No developer account for meethue → use Music Assistant README + IoTech blog + library source as secondary sources; still create the spike file with “docs behind login”.

---

### Task 0.2: Dependency smoke (install in throwaway env)

**Files:** none committed yet

**Step 1:** Confirm package installs under project Python:
```bash
cd /run/media/marvinbraga/dados-linux/marvin/my_phillips_hue
uv run python -c "import sys; print(sys.version)"
uv pip install hue-entertainment --dry-run 2>&1 | head -40
# Or: uv add --dev is wrong; for spike only:
uv run pip install 'hue-entertainment'  # temporary; revert lock later if desired
uv run python -c "from hue_entertainment import EntertainmentSession, HueEntertainmentAPI, LightColorCommand; print('ok')"
```
Expected: import succeeds on Python ≥3.11.

**If Task Fails:** Package missing on PyPI for your index → pin git URL  
`hue-entertainment @ git+https://github.com/music-assistant/hue-entertainment` in a local experiment only; record in spike notes.

---

### Task 0.3: Manual PoC script (optional live bridge)

**Create (local only, may stay uncommitted or under `scripts/`):** `scripts/entertainment_poc.py`

```python
"""One-shot PoC: pair (optional) and flash white on all channels ~5s.

Usage:
  HUE_HOST=192.168.x.x HUE_APP_KEY=... HUE_CLIENT_KEY=... uv run python scripts/entertainment_poc.py
  # First time: press bridge button, set PAIR=1
  PAIR=1 HUE_HOST=... uv run python scripts/entertainment_poc.py
"""
from __future__ import annotations

import asyncio
import os
import sys


async def main() -> int:
    host = os.environ.get("HUE_HOST") or os.environ.get("BRIDGE_IP")
    if not host:
        print("Set HUE_HOST or BRIDGE_IP", file=sys.stderr)
        return 2

    from hue_entertainment import EntertainmentSession, HueEntertainmentAPI, LightColorCommand

    app_key = os.environ.get("HUE_APP_KEY")
    client_key = os.environ.get("HUE_CLIENT_KEY")

    if os.environ.get("PAIR") == "1":
        api = HueEntertainmentAPI(host)
        creds = await api.pair()
        await api.close()
        print("PAIR_OK", creds)
        app_key = creds["username"]
        client_key = creds["clientkey"]

    if not app_key or not client_key:
        print("Need HUE_APP_KEY + HUE_CLIENT_KEY or PAIR=1", file=sys.stderr)
        return 2

    session = EntertainmentSession(host, app_key, client_key)
    areas = await session.get_entertainment_areas()
    if not areas:
        print("No entertainment areas — create one in the Hue app", file=sys.stderr)
        await session.aclose()
        return 3
    area = areas[0]
    print("AREA", area.id, getattr(area, "name", ""), "channels", len(area.channels))
    await session.start(area.id)
    try:
        for _ in range(100):
            session.send(
                [
                    LightColorCommand(
                        channel_id=ch.channel_id,
                        red=40000,
                        green=40000,
                        blue=40000,
                    )
                    for ch in area.channels
                ]
            )
            await asyncio.sleep(1 / 40)
    finally:
        await session.aclose()
    print("DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

**Step 2 (manual):** Press bridge link button if pairing; run PoC; verify lights flash.

**Step 3:** Append results to spike notes (area id, channel count, errors).

**If Task Fails:** Document error (DTLS blocked by firewall, no areas, wrong bridge firmware). Phase 1 still proceeds with mocks.

### Task 0.4: Code review checkpoint (Phase 0)

1. **REQUIRED:** Use jarvis-default-codereview on spike notes + optional script only if committed.
2. Proceed when spike answers D1–D9 still hold.

---

## Phase 1 — Entertainment client integration

**Goal:** First-class wrapper, settings, credential storage, feature flag, area discovery — still **not** required for AudioMirror to work.

**Effort:** 1–2 days

### Task 1.1: Settings + env surface

**Files:**
- Modify: `marvin_hue/config.py`
- Modify: `.env.example`
- Test: `tests/test_config.py`

**Prerequisites:** none

**Step 1: Write failing tests** (append to `tests/test_config.py`):

```python
import os
from unittest.mock import patch

from marvin_hue.config import Settings


def test_entertainment_defaults_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("BRIDGE_IP", "192.168.1.1")
    # Isolate from real .env
    s = Settings(
        _env_file=None,  # if supported; else monkeypatch all required
        bridge_ip="192.168.1.1",
        entertainment_enabled=False,
    )
    # Prefer constructing via env for pydantic-settings consistency:
    monkeypatch.setenv("BRIDGE_IP", "10.0.0.1")
    monkeypatch.delenv("ENTERTAINMENT_ENABLED", raising=False)
    monkeypatch.delenv("HUE_APP_KEY", raising=False)
    monkeypatch.delenv("HUE_CLIENT_KEY", raising=False)
    # Re-import pattern used elsewhere in test_config.py — follow existing tests.
```

**Adapt to existing `tests/test_config.py` patterns** (read that file first). Required assertions:

```python
def test_entertainment_settings_fields(monkeypatch):
    monkeypatch.setenv("BRIDGE_IP", "10.0.0.1")
    monkeypatch.setenv("ENTERTAINMENT_ENABLED", "true")
    monkeypatch.setenv("HUE_APP_KEY", "appkey123")
    monkeypatch.setenv("HUE_CLIENT_KEY", "clientkey456")
    monkeypatch.setenv("ENTERTAINMENT_AREA_ID", "area-uuid")
    monkeypatch.setenv("ENTERTAINMENT_CREDS_FILE", ".res/hue_entertainment_creds.json")
    # Construct Settings the same way other tests do (often Settings() after env).
    from marvin_hue import config as config_module
    # If module-level `settings` is a singleton, test the class with model_validate:
    s = config_module.Settings(
        bridge_ip="10.0.0.1",
        entertainment_enabled=True,
        hue_app_key="appkey123",
        hue_client_key="clientkey456",
        entertainment_area_id="area-uuid",
        entertainment_creds_file=".res/hue_entertainment_creds.json",
    )
    assert s.entertainment_enabled is True
    assert s.hue_app_key == "appkey123"
    assert s.hue_client_key == "clientkey456"
    assert s.entertainment_area_id == "area-uuid"
    assert s.entertainment_creds_file == ".res/hue_entertainment_creds.json"
```

**Step 2: Run test to verify it fails**
```bash
uv run pytest tests/test_config.py -k entertainment -v --no-cov
```
Expected: `FAILED` — unexpected keyword / attribute missing.

**Step 3: Implement fields on `Settings` in `marvin_hue/config.py`**

Add after `bridge_timeout` (or near bridge section):

```python
    # --- Hue Entertainment (DTLS stream); optional ---
    entertainment_enabled: bool = Field(
        default=False,
        description="Enable Hue Entertainment DTLS streaming when credentials exist",
    )
    hue_app_key: str | None = Field(
        default=None,
        description="Hue application key (CLIP username) for Entertainment API",
    )
    hue_client_key: str | None = Field(
        default=None,
        description="DTLS client key (clientkey) from Entertainment pairing",
    )
    entertainment_area_id: str | None = Field(
        default=None,
        description="Default entertainment configuration id (CLIP v2 resource id)",
    )
    entertainment_creds_file: str = Field(
        default=".res/hue_entertainment_creds.json",
        description="JSON file for app_key/clientkey (gitignored); env overrides file",
    )
    entertainment_fps: int = Field(
        default=40,
        ge=10,
        le=60,
        description="Target Entertainment stream FPS when transport=entertainment",
    )
```

Env names (pydantic-settings case-insensitive): `ENTERTAINMENT_ENABLED`, `HUE_APP_KEY`, `HUE_CLIENT_KEY`, `ENTERTAINMENT_AREA_ID`, `ENTERTAINMENT_CREDS_FILE`, `ENTERTAINMENT_FPS`.

**Step 4: Update `.env.example`** with commented block:

```bash
# ====================================
# Hue Entertainment (optional DTLS stream)
# ====================================
# Create an Entertainment area in the official Hue app first.
# Pair once (press bridge button) via API or scripts/entertainment_poc.py
ENTERTAINMENT_ENABLED=false
# HUE_APP_KEY=
# HUE_CLIENT_KEY=
# ENTERTAINMENT_AREA_ID=
# ENTERTAINMENT_CREDS_FILE=.res/hue_entertainment_creds.json
# ENTERTAINMENT_FPS=40
```

**Step 5: Ensure `.gitignore` ignores creds file**
```bash
grep -n 'hue_entertainment' .gitignore || echo '.res/hue_entertainment_creds.json' >> .gitignore
```

**Step 6: Verify tests pass**
```bash
uv run pytest tests/test_config.py -k entertainment -v --no-cov
# Expected: PASSED
```

**Step 7: Commit** — use jarvis-default-commit  
Message hint: `feat(config): entertainment settings and feature flag`

**If Task Fails:** Follow patterns in existing `tests/test_config.py` for how Settings is constructed (singleton vs class).

---

### Task 1.2: Add dependency + Python floor

**Files:**
- Modify: `pyproject.toml` (`requires-python`, `dependencies`)
- Modify: `uv.lock` (via `uv add`)

**Step 1:**
```bash
cd /run/media/marvinbraga/dados-linux/marvin/my_phillips_hue
# Bump requires-python to >=3.11 in pyproject.toml (and tool.mypy python_version if needed)
uv add 'hue-entertainment'
uv run python -c "from hue_entertainment import EntertainmentSession; print(EntertainmentSession)"
```
Expected: package importable; lockfile updated.

**Step 2: Commit** — `build: add hue-entertainment dependency (Python >=3.11)`

**If Task Fails:** Try git dependency form in pyproject; document pin in spike notes.

---

### Task 1.3: Credentials helper (file + env merge)

**Files:**
- Create: `marvin_hue/entertainment/__init__.py`
- Create: `marvin_hue/entertainment/credentials.py`
- Test: `tests/test_entertainment_credentials.py`

**Step 1: Failing tests**

```python
# tests/test_entertainment_credentials.py
import json
from pathlib import Path

from marvin_hue.entertainment.credentials import load_entertainment_credentials, save_entertainment_credentials


def test_load_prefers_env_over_file(tmp_path, monkeypatch):
    path = tmp_path / "creds.json"
    path.write_text(json.dumps({"username": "file-user", "clientkey": "file-key"}), encoding="utf-8")
    monkeypatch.setenv("HUE_APP_KEY", "env-user")
    monkeypatch.setenv("HUE_CLIENT_KEY", "env-key")
    creds = load_entertainment_credentials(
        creds_file=str(path),
        env_app_key="env-user",
        env_client_key="env-key",
    )
    assert creds is not None
    assert creds.username == "env-user"
    assert creds.clientkey == "env-key"


def test_load_from_file_when_env_missing(tmp_path):
    path = tmp_path / "creds.json"
    path.write_text(json.dumps({"username": "u", "clientkey": "k"}), encoding="utf-8")
    creds = load_entertainment_credentials(
        creds_file=str(path),
        env_app_key=None,
        env_client_key=None,
    )
    assert creds is not None
    assert creds.username == "u"
    assert creds.clientkey == "k"


def test_load_returns_none_when_incomplete(tmp_path):
    path = tmp_path / "creds.json"
    path.write_text("{}", encoding="utf-8")
    assert (
        load_entertainment_credentials(str(path), None, None) is None
    )


def test_save_roundtrip(tmp_path):
    path = tmp_path / "creds.json"
    save_entertainment_credentials(str(path), username="u", clientkey="k")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["username"] == "u"
    assert data["clientkey"] == "k"
    assert path.stat().st_mode & 0o077 == 0  # not group/world readable if chmod applied
```

**Step 2:**
```bash
uv run pytest tests/test_entertainment_credentials.py -v --no-cov
# Expected: FAILED import
```

**Step 3: Implementation**

```python
# marvin_hue/entertainment/__init__.py
"""Hue Entertainment (DTLS / HueStream) integration package."""

from marvin_hue.entertainment.credentials import (
    EntertainmentCredentials,
    load_entertainment_credentials,
    save_entertainment_credentials,
)

__all__ = [
    "EntertainmentCredentials",
    "load_entertainment_credentials",
    "save_entertainment_credentials",
]
```

```python
# marvin_hue/entertainment/credentials.py
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from marvin_hue.logging_config import get_logger

logger = get_logger("entertainment.credentials")


@dataclass(frozen=True, slots=True)
class EntertainmentCredentials:
    username: str  # app key
    clientkey: str  # DTLS PSK material as hex string from bridge


def load_entertainment_credentials(
    creds_file: str,
    env_app_key: str | None,
    env_client_key: str | None,
) -> EntertainmentCredentials | None:
    """Merge env over file. Returns None if incomplete."""
    username = (env_app_key or "").strip() or None
    clientkey = (env_client_key or "").strip() or None

    if username is None or clientkey is None:
        path = Path(creds_file)
        if path.is_file():
            try:
                data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"Could not read entertainment creds file {path}: {e}")
                data = {}
            username = username or (str(data.get("username") or data.get("app_key") or "").strip() or None)
            clientkey = clientkey or (
                str(data.get("clientkey") or data.get("client_key") or "").strip() or None
            )

    if not username or not clientkey:
        return None
    return EntertainmentCredentials(username=username, clientkey=clientkey)


def save_entertainment_credentials(
    creds_file: str,
    *,
    username: str,
    clientkey: str,
) -> None:
    path = Path(creds_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"username": username, "clientkey": clientkey}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        logger.debug("chmod 600 not applied on credentials file")
```

**Step 4:** Tests pass → commit `feat(entertainment): credentials load/save helper`

---

### Task 1.4: Entertainment client wrapper (mockable)

**Files:**
- Create: `marvin_hue/entertainment/client.py`
- Create: `marvin_hue/entertainment/models.py`
- Test: `tests/test_entertainment_client.py`

**Design:** Thin wrapper around `hue_entertainment` so tests never import real DTLS sockets. Protocol-oriented methods:

- `async pair() -> EntertainmentCredentials`
- `async list_areas() -> list[EntertainmentAreaInfo]`
- `async start_stream(area_id: str) -> None`
- `send_frame(colors: list[ChannelColor]) -> None`  # may be sync
- `async stop_stream() -> None`
- `is_streaming: bool`
- `active_area_id: str | None`

**Step 1: Domain models**

```python
# marvin_hue/entertainment/models.py
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ChannelInfo:
    channel_id: int
    # Optional stable light references from CLIP (string ids / names if library exposes)
    light_ids: tuple[str, ...] = ()
    position: tuple[float, float, float] | None = None  # x,y,z if available


@dataclass(frozen=True, slots=True)
class EntertainmentAreaInfo:
    id: str
    name: str
    channels: tuple[ChannelInfo, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ChannelColor:
    channel_id: int
    r: int  # 0-255
    g: int
    b: int
```

**Step 2: Tests with mock session**

```python
# tests/test_entertainment_client.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from marvin_hue.entertainment.client import EntertainmentClient
from marvin_hue.entertainment.credentials import EntertainmentCredentials
from marvin_hue.entertainment.models import ChannelColor


@pytest.mark.asyncio
async def test_list_areas_maps_models():
    creds = EntertainmentCredentials(username="u", clientkey="k")
    client = EntertainmentClient(host="10.0.0.1", credentials=creds)

    fake_ch = MagicMock(channel_id=0)
    fake_area = MagicMock(id="area-1", name="Sala", channels=[fake_ch])
    fake_session = AsyncMock()
    fake_session.get_entertainment_areas = AsyncMock(return_value=[fake_area])

    with patch.object(client, "_ensure_session", AsyncMock(return_value=fake_session)):
        areas = await client.list_areas()
    assert len(areas) == 1
    assert areas[0].id == "area-1"
    assert areas[0].channels[0].channel_id == 0


@pytest.mark.asyncio
async def test_start_send_stop_frame():
    creds = EntertainmentCredentials(username="u", clientkey="k")
    client = EntertainmentClient(host="10.0.0.1", credentials=creds)
    fake_session = MagicMock()
    fake_session.start = AsyncMock()
    fake_session.send = MagicMock()
    fake_session.stop = AsyncMock()
    fake_session.aclose = AsyncMock()

    with patch.object(client, "_ensure_session", AsyncMock(return_value=fake_session)):
        await client.start_stream("area-1")
        client.send_frame([ChannelColor(0, 255, 0, 0)])
        await client.stop_stream()

    fake_session.start.assert_awaited()
    fake_session.send.assert_called()
    assert client.is_streaming is False
```

**Step 3: Implementation sketch** (complete, not placeholder):

```python
# marvin_hue/entertainment/client.py
from __future__ import annotations

from typing import Any

from marvin_hue.entertainment.credentials import EntertainmentCredentials
from marvin_hue.entertainment.models import (
    ChannelColor,
    ChannelInfo,
    EntertainmentAreaInfo,
)
from marvin_hue.logging_config import get_logger

logger = get_logger("entertainment.client")


def _rgb8_to_16(v: int) -> int:
    v = max(0, min(255, int(v)))
    return (v << 8) | v  # 0..65535 style used by HueStream helpers


class EntertainmentClient:
    """Mockable facade over hue_entertainment.EntertainmentSession."""

    def __init__(
        self,
        host: str,
        credentials: EntertainmentCredentials | None,
    ) -> None:
        self.host = host
        self.credentials = credentials
        self._session: Any | None = None
        self._streaming = False
        self._area_id: str | None = None

    @property
    def is_streaming(self) -> bool:
        return self._streaming

    @property
    def active_area_id(self) -> str | None:
        return self._area_id

    async def _ensure_session(self) -> Any:
        if self.credentials is None:
            raise RuntimeError("Entertainment credentials missing")
        if self._session is None:
            from hue_entertainment import EntertainmentSession

            self._session = EntertainmentSession(
                self.host,
                self.credentials.username,
                self.credentials.clientkey,
            )
        return self._session

    async def pair(self) -> EntertainmentCredentials:
        from hue_entertainment import HueEntertainmentAPI

        api = HueEntertainmentAPI(self.host)
        try:
            creds = await api.pair()
        finally:
            await api.close()
        self.credentials = EntertainmentCredentials(
            username=creds["username"],
            clientkey=creds["clientkey"],
        )
        return self.credentials

    async def list_areas(self) -> list[EntertainmentAreaInfo]:
        session = await self._ensure_session()
        raw_areas = await session.get_entertainment_areas()
        out: list[EntertainmentAreaInfo] = []
        for area in raw_areas:
            channels: list[ChannelInfo] = []
            for ch in getattr(area, "channels", []) or []:
                channels.append(
                    ChannelInfo(
                        channel_id=int(ch.channel_id),
                        light_ids=tuple(
                            str(x)
                            for x in (
                                getattr(ch, "light_ids", None)
                                or getattr(ch, "members", None)
                                or ()
                            )
                        ),
                        position=getattr(ch, "position", None),
                    )
                )
            out.append(
                EntertainmentAreaInfo(
                    id=str(area.id),
                    name=str(getattr(area, "name", "") or area.id),
                    channels=tuple(channels),
                )
            )
        return out

    async def start_stream(self, area_id: str) -> None:
        session = await self._ensure_session()
        await session.start(area_id)
        self._area_id = area_id
        self._streaming = True
        logger.info(f"Entertainment stream started area={area_id}")

    def send_frame(self, colors: list[ChannelColor]) -> None:
        if not self._streaming or self._session is None:
            raise RuntimeError("Entertainment stream not active")
        from hue_entertainment import LightColorCommand

        cmds = [
            LightColorCommand(
                channel_id=c.channel_id,
                red=_rgb8_to_16(c.r),
                green=_rgb8_to_16(c.g),
                blue=_rgb8_to_16(c.b),
            )
            for c in colors
        ]
        self._session.send(cmds)

    async def stop_stream(self) -> None:
        if self._session is not None:
            stop = getattr(self._session, "stop", None)
            if callable(stop):
                res = stop()
                if hasattr(res, "__await__"):
                    await res
            aclose = getattr(self._session, "aclose", None)
            if callable(aclose):
                await aclose()
        self._session = None
        self._streaming = False
        self._area_id = None
        logger.info("Entertainment stream stopped")
```

**Note:** Adjust `LightColorCommand` kwargs to match installed package version (Phase 0). If constructor differs, fix only in this file.

**Step 4:** Tests pass → commit `feat(entertainment): mockable EntertainmentClient wrapper`

---

### Task 1.5: Channel mapper (registry / positions → channels)

**Files:**
- Create: `marvin_hue/entertainment/channel_map.py`
- Test: `tests/test_entertainment_channel_map.py`

**Behavior:**
- Input: `EntertainmentAreaInfo` + list of active lights from positions (`name`, `position`) + optional registry `bridge_light_id`
- Output: ordered mapping `list[MappedChannel]` with `channel_id`, `light_name`, `position`
- Matching strategy (in order): exact name in channel metadata → bridge id → fallback **index order** of enabled lights sorted by name (document as best-effort; user can reorder area in Hue app)

```python
# marvin_hue/entertainment/channel_map.py
from __future__ import annotations

from dataclasses import dataclass

from marvin_hue.entertainment.models import EntertainmentAreaInfo


@dataclass(frozen=True, slots=True)
class MappedChannel:
    channel_id: int
    light_name: str
    position: str


def map_lights_to_channels(
    area: EntertainmentAreaInfo,
    lights: list[dict],
) -> list[MappedChannel]:
    """
    lights items: {"name": str, "position": str, "bridge_light_id": str | None}
    """
    remaining = list(area.channels)
    mapped: list[MappedChannel] = []
    used_names: set[str] = set()

    # Pass 1: match by light id string contained in channel.light_ids
    for light in lights:
        name = str(light.get("name") or "")
        if not name:
            continue
        bridge_id = str(light.get("bridge_light_id") or "")
        pos = str(light.get("position") or "ambient")
        for ch in list(remaining):
            ids = {str(x) for x in ch.light_ids}
            if bridge_id and bridge_id in ids:
                mapped.append(MappedChannel(ch.channel_id, name, pos))
                remaining.remove(ch)
                used_names.add(name)
                break
            if name in ids:
                mapped.append(MappedChannel(ch.channel_id, name, pos))
                remaining.remove(ch)
                used_names.add(name)
                break

    # Pass 2: zip leftover channels with unmatched lights
    unmatched = [L for L in lights if str(L.get("name") or "") not in used_names]
    for ch, light in zip(remaining, unmatched):
        name = str(light.get("name") or "")
        pos = str(light.get("position") or "ambient")
        if name:
            mapped.append(MappedChannel(ch.channel_id, name, pos))

    return mapped
```

Tests: empty area → []; id match; name match; zip fallback.

**Commit:** `feat(entertainment): map registry lights to entertainment channels`

---

### Task 1.6: DI wiring for EntertainmentClient (lazy)

**Files:**
- Modify: `marvin_hue/api/dependencies.py`
- Modify: `app.py` (lifespan create client if enabled + creds present)
- Test: `tests/test_entertainment_di.py` (optional light unit) or extend existing DI tests

**Behavior:**
- `set_entertainment_client` / `get_entertainment_client` → `EntertainmentClient | None`
- Lifespan: if `settings.entertainment_enabled` and credentials load OK → construct client; else `None`
- On shutdown: `await client.stop_stream()` if streaming

**Commit:** `feat(entertainment): wire EntertainmentClient into app lifespan`

### Task 1.7: Code review checkpoint (Phase 1)

1. **REQUIRED SUB-SKILL:** jarvis-default-codereview — all Phase 1 files  
2. Fix Critical/High/Medium before Phase 2  
3. Confirm secrets not logged at INFO

---

## Phase 2 — Dual transport (`LightOutputPort`)

**Goal:** AudioMirror (and later ScreenMirror) push frames through an abstraction; Entertainment preferred when available; REST fallback.

**Effort:** 1–2 days

### Task 2.1: Define port + frame types

**Files:**
- Create: `marvin_hue/output/__init__.py`
- Create: `marvin_hue/output/port.py`
- Test: `tests/test_light_output_port.py`

```python
# marvin_hue/output/port.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class LightFrameColor:
    light_name: str
    r: int
    g: int
    b: int
    brightness: int  # 0-254 Hue scale after eye-safety clamp preference


TransportName = Literal["rest", "entertainment"]


@runtime_checkable
class LightOutputPort(Protocol):
    @property
    def transport(self) -> TransportName: ...

    def begin_session(self) -> None:
        """Prepare transport (no-op for REST)."""
        ...

    def apply_frame(self, colors: list[LightFrameColor]) -> None:
        """Push one full frame. Must be safe to call from mirror thread."""
        ...

    def end_session(self) -> None:
        """Release transport (stop DTLS stream)."""
        ...
```

**Test:** structural — create a fake port implementing protocol; `isinstance(fake, LightOutputPort)`.

**Commit:** `feat(output): LightOutputPort protocol`

---

### Task 2.2: RestPhueAdapter

**Files:**
- Create: `marvin_hue/output/rest_adapter.py`
- Test: `tests/test_rest_output_adapter.py`

```python
# marvin_hue/output/rest_adapter.py
from __future__ import annotations

from marvin_hue.colors import Color
from marvin_hue.controllers import HueController
from marvin_hue.eye_safety import clamp_eye_safety, is_enabled_for_app
from marvin_hue.output.port import LightFrameColor, LightOutputPort, TransportName


class RestPhueAdapter:
    def __init__(self, hue: HueController, transition_time: int = 0) -> None:
        self._hue = hue
        self.transition_time = transition_time

    @property
    def transport(self) -> TransportName:
        return "rest"

    def begin_session(self) -> None:
        return None

    def end_session(self) -> None:
        return None

    def apply_frame(self, colors: list[LightFrameColor]) -> None:
        for c in colors:
            if not is_enabled_for_app(c.light_name):
                continue
            bri = clamp_eye_safety(c.light_name, c.brightness, scale="hue")
            light = self._hue.set_light_color(
                c.light_name,
                Color(c.r, c.g, c.b, bri),
            )
            if light is not None:
                light.transitiontime = int(self.transition_time)
```

**Note:** `set_light_color` already clamps eye safety — double clamp is OK (idempotent for same scale). Prefer **single** clamp in adapters if `set_light_color` always clamps; then adapter may pass brightness through. Tests should mock `HueController.set_light_color`.

**Commit:** `feat(output): RestPhueAdapter`

---

### Task 2.3: EntertainmentStreamAdapter

**Files:**
- Create: `marvin_hue/output/entertainment_adapter.py`
- Test: `tests/test_entertainment_output_adapter.py`

**Behavior:**
- Constructor: `EntertainmentClient`, `list[MappedChannel]`, optional `HueController` unused for color
- `begin_session`: if not streaming, schedule/start stream for configured area (sync wrapper via `asyncio.run` **forbidden** if loop running — use client API that start was already done by mirror service, **or** provide `start_sync` helper using a background loop).  
  **Preferred design:** `AudioMirror.start` is sync today. Entertainment start is async. Options:
  1. Run `asyncio.run_coroutine_threadsafe` against app loop (store loop in client)
  2. Use library’s blocking `HueDtlsStreamer` in mirror thread only  
  **Plan mandate:** In `app.py` lifespan, keep a reference to the running event loop (`asyncio.get_running_loop()`). `EntertainmentStreamAdapter.begin_session` uses `asyncio.run_coroutine_threadsafe(client.start_stream(area_id), loop).result(timeout=10)`.
- `apply_frame`: map light_name → channel_id; build `ChannelColor`; apply eye safety on brightness → scale RGB by bri/254 if needed; `client.send_frame`
- `end_session`: `run_coroutine_threadsafe(client.stop_stream(), loop)`

**Eye safety for RGB stream:**  
`bri = clamp_eye_safety(name, brightness, scale="hue")`; scale each channel: `r' = r * bri // 254` (or keep RGB and encode brightness into value — match current AudioMirror which bakes bri into Color). Mirror current audio path: compute bri then pass RGB + bri into frame; adapter scales RGB by `bri/254` for stream so absolute brightness is limited.

```python
def _apply_bri(r: int, g: int, b: int, bri: int) -> tuple[int, int, int]:
    bri = max(0, min(254, bri))
    return (
        max(0, min(255, r * bri // 254)),
        max(0, min(255, g * bri // 254)),
        max(0, min(255, b * bri // 254)),
    )
```

**Tests:** mock client; ensure disabled lights skipped; `send_frame` called with expected channel ids.

**Commit:** `feat(output): EntertainmentStreamAdapter`

---

### Task 2.4: FallbackOutputPort (composite)

**Files:**
- Create: `marvin_hue/output/fallback.py`
- Test: `tests/test_fallback_output_port.py`

```python
class FallbackOutputPort:
    """Try entertainment; on begin/apply failure, degrade to REST for session."""

    def __init__(self, primary: LightOutputPort, secondary: LightOutputPort) -> None:
        self._primary = primary
        self._secondary = secondary
        self._active: LightOutputPort = primary
        self._degraded = False

    @property
    def transport(self) -> TransportName:
        return self._active.transport

    def begin_session(self) -> None:
        try:
            self._primary.begin_session()
            self._active = self._primary
            self._degraded = False
        except Exception:
            self._secondary.begin_session()
            self._active = self._secondary
            self._degraded = True

    def apply_frame(self, colors: list[LightFrameColor]) -> None:
        try:
            self._active.apply_frame(colors)
        except Exception:
            if self._active is self._primary:
                try:
                    self._primary.end_session()
                except Exception:
                    pass
                self._secondary.begin_session()
                self._active = self._secondary
                self._degraded = True
                self._active.apply_frame(colors)
            else:
                raise

    def end_session(self) -> None:
        try:
            self._active.end_session()
        finally:
            self._active = self._secondary
```

**Commit:** `feat(output): FallbackOutputPort for entertainment→REST`

---

### Task 2.5: Wire AudioMirror to LightOutputPort

**Files:**
- Modify: `marvin_hue/audio_mirror.py`
- Modify: `marvin_hue/api/routes/mirror.py` (status fields)
- Modify: `app.py` / factory that builds port
- Test: `tests/test_audio_mirror.py`, `tests/test_audio_mirror_api.py`

**Changes:**
1. `AudioMirror.__init__(self, hue_controller, positions_file, output_port: LightOutputPort | None = None)`
2. If `output_port is None` → default `RestPhueAdapter(hue_controller)` (backward compatible).
3. Replace body of `_apply_color_to_light` accumulation: better — collect all colors per frame in `_process_frame` and call `self._output.apply_frame([...])` once per frame (batch). Rest adapter still per-light; Entertainment needs full frame.
4. `start()` calls `self._output.begin_session()` after capture opens; `stop()` calls `end_session()`.
5. `get_status()` adds:
   - `transport`: `self._output.transport`
   - `entertainment_area_id`: optional from client
   - `entertainment_enabled`: from settings flag (optional)

**Factory helper** `marvin_hue/output/factory.py`:

```python
def build_audio_output_port(
    hue: HueController,
    *,
    entertainment_enabled: bool,
    client: EntertainmentClient | None,
    area_id: str | None,
    mapped_channels: list[MappedChannel] | None,
    loop: asyncio.AbstractEventLoop | None,
    transition_time: int = 0,
) -> LightOutputPort:
    rest = RestPhueAdapter(hue, transition_time=transition_time)
    if (
        entertainment_enabled
        and client is not None
        and client.credentials is not None
        and area_id
        and mapped_channels
        and loop is not None
    ):
        ent = EntertainmentStreamAdapter(
            client=client,
            area_id=area_id,
            channels=mapped_channels,
            loop=loop,
        )
        return FallbackOutputPort(ent, rest)
    return rest
```

**Wire in `start_mirror` (audio branch):** reload positions → if entertainment, `list_areas` / use `settings.entertainment_area_id` → `map_lights_to_channels` → rebuild port → assign `audio_mirror.set_output_port(port)` (add setter).

**FPS:** When transport is entertainment, prefer `settings.entertainment_fps` (default 40) unless user/profile overrides.

**Step: tests**
- Unit: AudioMirror with FakePort records frames; no HueController color calls.
- API: with entertainment disabled, status `transport=rest`.

**Commit:** `feat(audio): dual transport via LightOutputPort`

### Task 2.6: Code review checkpoint (Phase 2)

1. jarvis-default-codereview  
2. Verify no asyncio deadlocks (begin_session from mirror thread)  
3. Proceed only when Medium+ cleared

---

## Phase 3 — Audio quality (software)

**Goal:** Leverage faster transport with better intensity mapping and stereo layout; keep `audio_engine` as source of truth.

**Effort:** 0.5–1 day

### Task 3.1: Intensity profiles (Hue Sync-like)

**Files:**
- Modify: `marvin_hue/audio_mirror.py` (`AUDIO_MIRROR_PROFILES`)
- Modify: `marvin_hue/audio_engine.py` if new AnalyzerConfig knobs needed
- Modify: `web/static/mirror.js`, `web/templates/mirror.html` (optional aliases)
- Test: `tests/test_mirror_profiles.py`, `tests/test_audio_engine.py`

**Add intensity multipliers** (or alias map):

| Intensity | Maps to / behavior |
|-----------|--------------------|
| `subtle` | chill-like: low energy_gain, low beat, lower bri |
| `moderate` | default party mid |
| `high` | party+ |
| `extreme` | pulse-like max beat_sensitivity + energy_gain |

Implementation options (pick one, document in commit):
- **A (YAGNI):** Document that `chill|party|pulse` ≈ subtle|high|extreme; add only `intensity` float 0.5–1.5 on settings API.
- **B:** Add four named profiles that set the same keys as existing ones.

**Recommended B minimal:**

```python
AUDIO_INTENSITY_PROFILES = {
    "subtle": {**AUDIO_MIRROR_PROFILES["chill"], "fps": 24},
    "moderate": {
        "fps": 30,
        "brightness": 200,
        "smoothing_factor": 0.50,
        "transition_time": 0,
        "energy_gain": 1.0,
        "beat_sensitivity": 1.0,
        "hue_speed": 0.8,
        "attack": 0.45,
        "release": 0.10,
    },
    "high": {**AUDIO_MIRROR_PROFILES["party"]},
    "extreme": {**AUDIO_MIRROR_PROFILES["pulse"]},
}
```

Expose via `GET /mirror/profiles` as `audio_intensity_profiles` and accept `profile` values in start/settings.

**Commit:** `feat(audio): intensity profiles for entertainment-style sync`

---

### Task 3.2: Stereo mapping to entertainment layout

**Files:**
- Modify: `marvin_hue/audio_engine.py` (`color_for_position` / `entertainment_color`) — already has `stereo_bias`
- Modify: `marvin_hue/entertainment/channel_map.py` if channel `position` (x,y,z) available
- Test: `tests/test_audio_engine.py`

**Behavior when channel has spatial position from area:**
- `x < 0` → treat as left bias; `x > 0` → right; else ambient
- Prefer existing position string from `light_positions.json` when present; spatial only as fallback

**Commit:** `feat(audio): stereo bias from entertainment channel positions`

### Task 3.3: Code review (Phase 3)

jarvis-default-codereview on audio_engine/audio_mirror changes only.

---

## Phase 4 — Screen mirror via Entertainment (optional)

**Goal:** `ScreenMirror` can stream region colors as one Entertainment frame (HyperHDR-lite).

**Effort:** 0.5–1 day  
**Skip if:** music path not yet validated on real hardware.

### Task 4.1: Wire ScreenMirror to LightOutputPort

**Files:**
- Modify: `marvin_hue/screen_mirror.py` — same pattern as AudioMirror: batch frame → `apply_frame`
- Modify: `marvin_hue/api/routes/mirror.py` — when mode=screen and entertainment enabled, build port
- Test: `tests/test_screen_mirror_enabled.py` + new `tests/test_screen_mirror_output_port.py`

**Mutual exclusion:** existing `_stop_if_running` already stops the other mirror; Entertainment `end_session` on stop ensures single stream.

**Commit:** `feat(screen): optional Entertainment transport`

### Task 4.2: Code review (Phase 4)

---

## Phase 5 — UI / API / docs

**Effort:** 1 day

### Task 5.1: API models + endpoints

**Files:**
- Modify: `marvin_hue/api/models.py`
- Modify: `marvin_hue/api/routes/mirror.py`
- Test: `tests/test_audio_mirror_api.py`, new `tests/test_entertainment_api.py`

**Status fields (extend `_unified_status` / mirror get_status):**

```json
{
  "running": true,
  "mode": "audio",
  "transport": "entertainment",
  "entertainment_enabled": true,
  "entertainment_area_id": "…",
  "entertainment_area_name": "Sala",
  "fps": 40,
  "profile": "party",
  "bass": 0.2,
  "mid": 0.5,
  "treble": 0.1
}
```

**New endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/mirror/entertainment/areas` | List areas (503/empty if disabled/unpaired) |
| POST | `/mirror/entertainment/pair` | Pair (requires link button); saves creds file |
| POST | `/mirror/start` | Accept optional `transport`: `auto`\|`rest`\|`entertainment` (default `auto`) |
| POST | `/mirror/settings` | Optional `entertainment_area_id`, `transport` |

**Pair handler sketch:**

```python
@router.post("/mirror/entertainment/pair")
async def pair_entertainment(...):
    # 1) client.pair()
    # 2) save_entertainment_credentials(settings.entertainment_creds_file, ...)
    # 3) return {"ok": true, "username_suffix": username[-4:]}  # never full key in logs
```

**Start request:** if `transport=entertainment` but flag false or no creds → HTTP 400 with clear message.

**Commit:** `feat(api): entertainment areas, pair, transport status`

---

### Task 5.2: Mirror UI

**Files:**
- Modify: `web/templates/mirror.html`
- Modify: `web/static/mirror.js`

**UI elements:**
- Badge: transport `REST` vs `Entertainment` (color-coded)
- Select: entertainment area (populated from GET areas)
- Select/toggle: transport auto/rest/entertainment
- Intensity profiles if Phase 3 added
- Help text: “Create Entertainment area in Hue app; pair once with bridge button”

**Commit:** `feat(ui): entertainment transport controls on mirror page`

---

### Task 5.3: Documentation

**Files:**
- Modify: `docs/CONFIGURATION.md` — Entertainment section (env, pairing, area setup, firewall UDP)
- Modify: `docs/API.md` — new endpoints + status fields
- Modify: `docs/ARCHITECTURE.md` — dual transport diagram blurb (Future already linked)

**CONFIGURATION checklist for users:**
1. Hue app → create Entertainment area with desired lights  
2. Press bridge link button  
3. `POST /mirror/entertainment/pair` or PoC script  
4. Set `ENTERTAINMENT_ENABLED=true`  
5. Optional: set `ENTERTAINMENT_AREA_ID`  
6. Start audio mirror; confirm `transport=entertainment`

**Commit:** `docs: Hue Entertainment setup and API`

### Task 5.4: Code review (Phase 5)

---

## Phase 6 — Tests & safety harden

**Effort:** 1 day

### Task 6.1: Unit tests with mocked stream (CI gate)

**Files:**
- Ensure: `tests/test_entertainment_client.py`
- Ensure: `tests/test_entertainment_output_adapter.py`
- Ensure: `tests/test_fallback_output_port.py`
- Ensure: `tests/test_audio_mirror.py` uses FakePort
- Create: `tests/test_entertainment_eye_safety.py`

**Eye safety test:**

```python
def test_entertainment_adapter_clamps_brightness(monkeypatch):
    # light with low limit → scaled RGB lower than input
    ...
```

**CI command (document in CONTRIBUTING or tests/README):**
```bash
uv run pytest tests/test_entertainment_*.py tests/test_audio_mirror.py tests/test_rest_output_adapter.py tests/test_fallback_output_port.py -q --no-cov
```

**Hard rule:** no test opens real UDP/DTLS to a bridge.

**Commit:** `test(entertainment): mocked stream and eye safety`

---

### Task 6.2: Mutual exclusion sessions

**Files:**
- Modify: `marvin_hue/api/routes/mirror.py`
- Test: `tests/test_audio_mirror_api.py`

**Rules:**
1. Starting audio stops screen (existing) **and** ends entertainment session from screen if any  
2. Starting screen stops audio and ends stream  
3. Starting entertainment transport while REST audio running: same AudioMirror instance switches port only on start — must `end_session` old port first  
4. Optional: reject second Entertainment stream with 409 if client.is_streaming from another mode

**Commit:** `fix(mirror): mutual exclusion includes entertainment sessions`

---

### Task 6.3: Full regression

```bash
uv run pytest tests/test_audio_engine.py tests/test_audio_mirror.py tests/test_audio_mirror_api.py tests/test_mirror_profiles.py tests/test_screen_mirror_enabled.py tests/test_controller_eye_safety.py tests/test_entertainment_*.py tests/test_rest_output_adapter.py tests/test_fallback_output_port.py tests/test_light_output_port.py -q
# Expected: all PASSED
```

### Task 6.4: Final code review checkpoint

1. jarvis-default-codereview across entertainment + output + mirror  
2. Security pass: no clientkey in API responses or logs  
3. Definition of Done checklist above

---

## Suggested target file tree (after full plan)

```
marvin_hue/
  entertainment/
    __init__.py
    credentials.py
    client.py
    models.py
    channel_map.py
  output/
    __init__.py
    port.py
    rest_adapter.py
    entertainment_adapter.py
    fallback.py
    factory.py
  audio_mirror.py          # uses LightOutputPort
  audio_engine.py          # intensity/stereo tweaks
  screen_mirror.py         # optional port
  config.py                # entertainment_* settings
  api/routes/mirror.py     # areas, pair, transport
  api/models.py
web/templates/mirror.html
web/static/mirror.js
tests/test_entertainment_*.py
tests/test_*_output*.py
scripts/entertainment_poc.py   # optional
docs/plans/spikes/2026-08-08-entertainment-spike.md
.res/hue_entertainment_creds.json  # gitignored, runtime
```

---

## Risk register

| Risk | Mitigation |
|------|------------|
| DTLS blocked on LAN/firewall | Document UDP to bridge; fallback REST |
| Single stream constraint | Fallback + mutual exclusion; stop on mode switch |
| Channel map wrong lights | Prefer bridge ids; UI shows mapping; allow area rebuild in Hue app |
| `hue-entertainment` API drift | Pin version in uv.lock; wrapper isolates |
| Async/sync deadlock | run_coroutine_threadsafe + timeouts; never asyncio.run inside running loop |
| Eye safety bypass | Clamp in EntertainmentStreamAdapter before send; unit tests |
| Credential leak | chmod 600 file; redacted API; .gitignore |

---

## Manual acceptance (human on LAN)

1. Pair + list areas  
2. Audio + entertainment: play music 2 min — subjective smoothness vs REST  
3. Kill stream (stop mirror) — lights leave entertainment mode cleanly  
4. Disable flag — audio still works REST  
5. Screen + audio still exclusive  
6. Light with eye_safety_limit never exceeds cap under extreme profile  

---

## Appendix A — Why REST cannot match official Sync

Philips states continuous fast light updates must use the Entertainment streaming API; REST is slower, cannot be preempted the same way, and floods the event stream. Official Sync and Music Assistant use DTLS HueStream. This plan aligns Marvin Hue with that architecture without cloning proprietary app UI/logic.

## Appendix B — Color conversion cheat sheet

| Space | Range | Use |
|-------|-------|-----|
| App RGB | 0–255 | audio_engine / screen |
| Hue brightness | 0–254 | eye_safety, Color.brightness |
| LightColorCommand | 0–65535 per channel | Entertainment send (`(v<<8)|v`) |
| REST path | XY + bri | RestPhueAdapter via HueController |

## Appendix C — Commit message series (suggested)

1. `docs: plan Hue Entertainment music/sync upgrade` ← **this document**  
2. `feat(config): entertainment settings and feature flag`  
3. `build: add hue-entertainment dependency (Python >=3.11)`  
4. `feat(entertainment): credentials + client + channel map`  
5. `feat(output): LightOutputPort REST/Entertainment/fallback`  
6. `feat(audio): dual transport via LightOutputPort`  
7. `feat(audio): intensity profiles for entertainment-style sync`  
8. `feat(api/ui): entertainment transport controls`  
9. `test(entertainment): mocked stream and eye safety`  
10. `docs: Hue Entertainment setup and API`
