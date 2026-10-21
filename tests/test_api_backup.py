"""API tests for /api/backup/export and /api/backup/import."""

from __future__ import annotations

import io
import json
import shutil
import zipfile
from pathlib import Path

import pytest

_REAL_PHYSICAL = Path(".res/light_physical_locations.json")


@pytest.fixture(autouse=True)
def _isolate_res_files(tmp_path, monkeypatch):
    """Keep import from writing JSON (and ``.bak`` siblings) into the real ``.res``.

    ``physical_locations_file`` is not a Settings field: BackupService falls
    back to ``dependencies._DEFAULT_PHYSICAL_LOCATIONS``, so patch that too.
    """
    iso = tmp_path / "iso_res"
    iso.mkdir()
    physical = iso / "light_physical_locations.json"
    if _REAL_PHYSICAL.exists():
        shutil.copyfile(_REAL_PHYSICAL, physical)  # read-only use of the real file
    else:
        physical.write_text("{}", encoding="utf-8")
    setups = iso / "setups.json"
    positions = iso / "positions.json"
    setups.write_text(json.dumps({"setups": []}), encoding="utf-8")
    positions.write_text(json.dumps({"lights": []}), encoding="utf-8")
    monkeypatch.setattr(
        "marvin_hue.api.dependencies._DEFAULT_PHYSICAL_LOCATIONS", str(physical)
    )
    monkeypatch.setattr("marvin_hue.api.routes.backup.settings.setups_file", str(setups))
    monkeypatch.setattr(
        "marvin_hue.api.routes.backup.settings.positions_file", str(positions)
    )
    return iso


def _isolate_res_files_dir(tmp_path: Path) -> Path:
    return tmp_path / "iso_res"


class TestBackupAPI:
    def test_export_empty_zip(self, fastapi_test_client):
        r = fastapi_test_client.get("/api/backup/export")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("application/zip")
        assert "attachment" in r.headers.get("content-disposition", "")
        assert zipfile.is_zipfile(io.BytesIO(r.content))
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            names = set(zf.namelist())
        assert "manifest.json" in names
        assert "lights.json" in names
        assert "groups.json" in names
        assert "schedules.json" in names
        assert "favorites.json" in names

    def test_export_includes_favorites(self, fastapi_test_client):
        put = fastapi_test_client.put("/configurations/favorites/relax")
        assert put.status_code == 200, put.text
        r = fastapi_test_client.get("/api/backup/export")
        assert r.status_code == 200
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            favorites = json.loads(zf.read("favorites.json"))
        assert favorites == ["relax"]

    def test_export_includes_created_light(self, fastapi_test_client):
        created = fastapi_test_client.post(
            "/api/lights",
            json={"name": "Backup Lamp", "bridge_light_id": "bb-1"},
        )
        assert created.status_code == 201, created.text
        r = fastapi_test_client.get("/api/backup/export")
        assert r.status_code == 200
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            lights = json.loads(zf.read("lights.json"))
        assert any(x["name"] == "Backup Lamp" for x in lights)

    def test_import_roundtrip_merge(self, fastapi_test_client, tmp_path, monkeypatch):
        # Point JSON targets at temp files so import does not clobber real .res
        setups = tmp_path / "setups.json"
        positions = tmp_path / "positions.json"
        setups.write_text(json.dumps({"setups": []}), encoding="utf-8")
        positions.write_text(json.dumps({"lights": []}), encoding="utf-8")
        monkeypatch.setattr(
            "marvin_hue.api.routes.backup.settings.setups_file", str(setups)
        )
        monkeypatch.setattr(
            "marvin_hue.api.routes.backup.settings.positions_file", str(positions)
        )

        fav = fastapi_test_client.put("/configurations/favorites/relax")
        assert fav.status_code == 200, fav.text
        fastapi_test_client.post(
            "/api/lights",
            json={
                "name": "Roundtrip",
                "nickname": "RT",
                "bridge_light_id": "rt-1",
                "eye_safety_limit_pct": 50,
            },
        )
        exported = fastapi_test_client.get("/api/backup/export")
        assert exported.status_code == 200

        # Soft-delete via API then re-import
        listed = fastapi_test_client.get("/api/lights").json()
        lid = next(x["id"] for x in listed if x["name"] == "Roundtrip")
        fastapi_test_client.delete(f"/api/lights/{lid}")
        assert fastapi_test_client.get("/api/lights").json() == []
        unfav = fastapi_test_client.delete("/configurations/favorites/relax")
        assert unfav.status_code == 204

        files = {
            "file": ("backup.zip", exported.content, "application/zip"),
        }
        data = {"strategy": "merge"}
        imp = fastapi_test_client.post("/api/backup/import", files=files, data=data)
        assert imp.status_code == 200, imp.text
        body = imp.json()
        assert body["strategy"] == "merge"
        assert "lights" in body
        assert body["favorites"] == {"added": 1, "removed": 0, "total": 1}
        # Import rewrote the isolated copies, never the repo's .res
        assert (_isolate_res_files_dir(tmp_path) / "light_physical_locations.json.bak").exists()
        assert not (_REAL_PHYSICAL.parent / "light_physical_locations.json.bak").exists()
        active = fastapi_test_client.get("/api/lights").json()
        names = {x["name"] for x in active}
        assert "Roundtrip" in names

    def test_import_invalid_zip_400(self, fastapi_test_client):
        files = {"file": ("bad.zip", b"not-zip-content", "application/zip")}
        r = fastapi_test_client.post(
            "/api/backup/import", files=files, data={"strategy": "merge"}
        )
        assert r.status_code == 400

    def test_import_empty_file_400(self, fastapi_test_client):
        files = {"file": ("empty.zip", b"", "application/zip")}
        r = fastapi_test_client.post(
            "/api/backup/import", files=files, data={"strategy": "merge"}
        )
        assert r.status_code == 400

    def test_export_does_not_open_extra_sqlite_repos(
        self, fastapi_test_client, monkeypatch
    ):
        from marvin_hue.persistence.favorites_repository import (
            SqliteSceneFavoritesRepository,
        )
        from marvin_hue.persistence.group_repository import SqliteGroupRepository
        from marvin_hue.persistence.schedule_repository import SqliteScheduleRepository

        async def _forbid_open(*args, **kwargs):
            raise AssertionError(
                "BackupService must reuse lifespan repos; "
                "do not call Sqlite*Repository.open"
            )

        monkeypatch.setattr(SqliteGroupRepository, "open", _forbid_open)
        monkeypatch.setattr(SqliteSceneFavoritesRepository, "open", _forbid_open)
        monkeypatch.setattr(SqliteScheduleRepository, "open", _forbid_open)
        r = fastapi_test_client.get("/api/backup/export")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("application/zip")

    def test_import_reloads_setups_manager(
        self, fastapi_test_client, tmp_path, monkeypatch
    ):
        from marvin_hue.api import dependencies

        setups = tmp_path / "setups.json"
        positions = tmp_path / "positions.json"
        setups.write_text(json.dumps({"setups": []}), encoding="utf-8")
        positions.write_text(json.dumps({"lights": []}), encoding="utf-8")
        monkeypatch.setattr(
            "marvin_hue.api.routes.backup.settings.setups_file", str(setups)
        )
        monkeypatch.setattr(
            "marvin_hue.api.routes.backup.settings.positions_file", str(positions)
        )

        exported = fastapi_test_client.get("/api/backup/export")
        assert exported.status_code == 200

        manager = dependencies.get_manager()
        load_calls: list[bool] = []
        orig_load = manager.load

        def _spy_load():
            load_calls.append(True)
            return orig_load()

        monkeypatch.setattr(manager, "load", _spy_load)

        files = {"file": ("backup.zip", exported.content, "application/zip")}
        imp = fastapi_test_client.post(
            "/api/backup/import", files=files, data={"strategy": "merge"}
        )
        assert imp.status_code == 200, imp.text
        assert load_calls, "LightSetupsManager.load() must run after setups import"
