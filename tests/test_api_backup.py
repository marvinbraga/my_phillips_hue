"""API tests for /api/backup/export and /api/backup/import."""

from __future__ import annotations

import io
import json
import zipfile


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

        files = {
            "file": ("backup.zip", exported.content, "application/zip"),
        }
        data = {"strategy": "merge"}
        imp = fastapi_test_client.post("/api/backup/import", files=files, data=data)
        assert imp.status_code == 200, imp.text
        body = imp.json()
        assert body["strategy"] == "merge"
        assert "lights" in body
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
