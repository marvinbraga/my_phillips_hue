"""Smoke test of the REAL ``app.py`` lifespan (issue #20).

``fastapi_test_client`` wires the services by hand and never runs the lifespan,
so a wiring bug in ``app.py`` would go unnoticed. Here ``with TestClient(app)``
runs startup and shutdown for real, against a temp SQLite file, temp copies of
the JSON files, a mocked phue Bridge and no chat keys (chat fails open).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from marvin_hue.api import dependencies
from marvin_hue.persistence.favorites_repository import SqliteSceneFavoritesRepository
from marvin_hue.persistence.group_repository import SqliteGroupRepository
from marvin_hue.persistence.last_applied_repository import (
    SqliteLastAppliedSceneRepository,
)
from marvin_hue.persistence.light_repository import SqliteLightRegistryRepository
from marvin_hue.persistence.scene_history_repository import (
    SqliteSceneHistoryRepository,
)
from marvin_hue.persistence.schedule_repository import SqliteScheduleRepository

_REPO_CLASSES = (
    SqliteLightRegistryRepository,
    SqliteGroupRepository,
    SqliteSceneHistoryRepository,
    SqliteScheduleRepository,
    SqliteSceneFavoritesRepository,
    SqliteLastAppliedSceneRepository,
)

# Process-wide state in the service locator: restored after the test so the
# lifespan's leftovers (hue controller, mirrors, chat agent...) never leak.
_DEPENDENCY_STATE = (
    "_hue_controller",
    "_manager",
    "_screen_mirror",
    "_audio_mirror",
    "_entertainment_client",
    "_chat_agent",
    "_chat_unavailable_reason",
    "_chat_checkpointer",
    "_light_registry_service",
    "_group_service",
    "_scene_history_service",
    "_schedule_service",
    "_schedule_runner",
    "_mirror_control_service",
    "_backup_service",
    "_scene_favorites_service",
    "_last_applied_scene_service",
    "_bound_app",
)

_CHAT_KEY_ENV = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "GROQ_API_KEY",
)

_RES = Path(__file__).resolve().parent.parent / ".res"


def _copy_or_write(name: str, dest_dir: Path, fallback: Any) -> Path:
    dest = dest_dir / name
    source = _RES / name
    if source.exists():
        shutil.copyfile(source, dest)
    else:
        dest.write_text(json.dumps(fallback), encoding="utf-8")
    return dest


@pytest.fixture
def isolated_app(monkeypatch, tmp_path, mock_phue_bridge: Mock):
    """``app.app`` pointed at temp files, mocked bridge and no chat keys."""
    import app as app_module
    from marvin_hue.config import settings

    for name in _DEPENDENCY_STATE:
        monkeypatch.setattr(dependencies, name, getattr(dependencies, name))

    res = tmp_path / "res"
    res.mkdir()
    setups = _copy_or_write("setups.json", res, {"setups": []})
    positions = _copy_or_write("light_positions.json", res, {})
    physical = _copy_or_write("light_physical_locations.json", res, {})
    db_path = tmp_path / "app.sqlite"

    overrides: dict[str, Any] = {
        "app_db_path": str(db_path),
        "setups_file": str(setups),
        "positions_file": str(positions),
        "entertainment_enabled": False,
        "entertainment_area_id": None,
        "entertainment_creds_file": str(tmp_path / "no_creds.json"),
        "hue_app_key": None,
        "hue_client_key": None,
        "chat_provider": "openai",
        "chat_checkpoint": "memory",
        "chat_checkpoint_db": str(tmp_path / "chat.sqlite"),
        "openai_api_key": None,
        "anthropic_api_key": None,
        "xai_api_key": None,
        "groq_api_key": None,
    }
    for attr, value in overrides.items():
        monkeypatch.setattr(settings, attr, value)
    monkeypatch.setattr(dependencies, "_DEFAULT_PHYSICAL_LOCATIONS", str(physical))
    for env in _CHAT_KEY_ENV:
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr("marvin_hue.controllers.Bridge", lambda ip: mock_phue_bridge)

    opened: list[tuple[object, str]] = []
    closed: list[object] = []
    for cls in _REPO_CLASSES:
        original_open = cls.open
        original_close = cls.close

        async def _open(db: str, _orig: Any = original_open) -> Any:
            repo = await _orig(db)
            opened.append((repo, db))
            return repo

        async def _close(self: Any, _orig: Any = original_close) -> None:
            closed.append(self)
            await _orig(self)

        monkeypatch.setattr(cls, "open", staticmethod(_open))
        monkeypatch.setattr(cls, "close", _close)

    return app_module.app, {"db_path": str(db_path), "opened": opened, "closed": closed}


def _api_headers(app: Any) -> dict[str, str]:
    """Send the key the ApiKeyMiddleware was built with (if any)."""
    for middleware in app.user_middleware:
        key = middleware.kwargs.get("api_key")
        if key:
            return {"X-API-Key": key}
    return {}


def test_lifespan_registers_services_and_releases_them(isolated_app) -> None:
    app, spy = isolated_app
    headers = _api_headers(app)

    with TestClient(app) as client:
        assert dependencies.get_light_registry_service() is not None
        assert dependencies.get_group_service() is not None
        assert dependencies.get_scene_history_service() is not None
        assert dependencies.get_schedule_service() is not None
        assert dependencies.get_scene_favorites_service() is not None
        assert dependencies.get_last_applied_scene_service_optional() is not None
        assert dependencies.get_backup_service() is not None
        assert dependencies.get_entertainment_client() is not None

        runner = dependencies.get_schedule_runner()
        assert runner is not None and runner.is_running is True

        mirror_control = dependencies.get_mirror_control_service()
        assert mirror_control.unified_status()["running"] is False
        screen = dependencies.get_screen_mirror()
        audio = dependencies.get_audio_mirror()
        assert not screen.is_running() and not audio.is_running()

        # Chat fails open without keys: no agent, but a diagnostic reason.
        assert dependencies.get_chat_agent() is None
        assert dependencies.get_chat_unavailable_reason()

        health = client.get("/api/health", headers=headers)
        assert health.status_code == 200
        payload = health.json()
        assert payload["schedules"]["runner_alive"] is True
        assert payload["mirror"]["running"] is False
        assert payload["chat"]["available"] is False
        assert payload["registry"]["db_path"] == spy["db_path"]

        last_applied = client.get("/configurations/last-applied")
        assert last_applied.status_code == 200
        assert last_applied.json()["name"] is None

    # Every repo opened on the temp DB, and every one was closed on shutdown.
    assert len(spy["opened"]) == len(_REPO_CLASSES)
    assert {db for _, db in spy["opened"]} == {spy["db_path"]}
    assert {id(repo) for repo, _ in spy["opened"]} == {id(r) for r in spy["closed"]}

    assert runner.is_running is False
    assert dependencies.get_schedule_runner() is None
    assert dependencies.get_last_applied_scene_service_optional() is None
    assert dependencies.get_entertainment_client() is None
    for getter in (
        dependencies.get_light_registry_service,
        dependencies.get_group_service,
        dependencies.get_scene_history_service,
        dependencies.get_schedule_service,
        dependencies.get_scene_favorites_service,
        dependencies.get_backup_service,
    ):
        with pytest.raises(RuntimeError):
            getter()
