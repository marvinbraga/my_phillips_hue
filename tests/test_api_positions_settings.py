"""Positions routes must honor settings.positions_file (not a hardcoded path)."""

from __future__ import annotations

import json
from pathlib import Path

from marvin_hue.config import settings

_SAMPLE_LIGHTS = [
    {"name": "Lâmpada 1", "position": "none", "enabled": True},
]


def _patch_positions_file(monkeypatch, path: Path) -> None:
    monkeypatch.setattr(settings, "positions_file", str(path))


class TestPositionsUsesSettingsFile:
    def test_post_writes_to_settings_path_not_default(
        self, fastapi_test_client, tmp_path, monkeypatch
    ):
        dest = tmp_path / "custom_light_positions.json"
        default_path = Path(".res/light_positions.json")
        before = (
            default_path.read_text(encoding="utf-8") if default_path.exists() else None
        )
        _patch_positions_file(monkeypatch, dest)

        response = fastapi_test_client.post(
            "/positions", json={"lights": _SAMPLE_LIGHTS}
        )
        assert response.status_code == 200, response.text
        assert dest.exists()
        saved = json.loads(dest.read_text(encoding="utf-8"))
        assert saved["lights"][0]["name"] == "Lâmpada 1"
        assert saved["lights"][0]["position"] == "none"

        if before is not None:
            after = default_path.read_text(encoding="utf-8")
            assert after == before

    def test_get_reads_from_settings_path(
        self, fastapi_test_client, tmp_path, monkeypatch
    ):
        dest = tmp_path / "custom_light_positions.json"
        dest.write_text(
            json.dumps(
                {
                    "lights": [
                        {
                            "name": "FromTemp",
                            "position": "center",
                            "enabled": True,
                        }
                    ],
                    "positions": [],
                }
            ),
            encoding="utf-8",
        )
        _patch_positions_file(monkeypatch, dest)

        response = fastapi_test_client.get("/positions")
        assert response.status_code == 200
        names = [item["name"] for item in response.json()["lights"]]
        assert names == ["FromTemp"]

    def test_reset_includes_lampada_3_in_ceiling_order(
        self, fastapi_test_client, tmp_path, monkeypatch
    ):
        dest = tmp_path / "custom_light_positions.json"
        _patch_positions_file(monkeypatch, dest)

        response = fastapi_test_client.post("/positions/reset")
        assert response.status_code == 200
        lights = response.json()["lights"]
        names = [item["name"] for item in lights]
        assert "Lâmpada 3" in names
        assert names.index("Lâmpada 2") < names.index("Lâmpada 3")
        assert names.index("Lâmpada 3") < names.index("Lâmpada 4")
        lamp3 = next(item for item in lights if item["name"] == "Lâmpada 3")
        assert lamp3["position"] == "none"
        assert lamp3["enabled"] is True

        on_disk = json.loads(dest.read_text(encoding="utf-8"))
        disk_names = [item["name"] for item in on_disk["lights"]]
        assert "Lâmpada 3" in disk_names

    def test_post_reloads_audio_mirror_positions(
        self, fastapi_test_client, tmp_path, monkeypatch, mock_audio_mirror
    ):
        dest = tmp_path / "custom_light_positions.json"
        _patch_positions_file(monkeypatch, dest)

        response = fastapi_test_client.post(
            "/positions", json={"lights": _SAMPLE_LIGHTS}
        )
        assert response.status_code == 200
        mock_audio_mirror.reload_light_positions.assert_called()

    def test_post_succeeds_when_audio_mirror_unavailable(
        self, fastapi_test_client, tmp_path, monkeypatch
    ):
        dest = tmp_path / "custom_light_positions.json"
        _patch_positions_file(monkeypatch, dest)

        def _missing_audio() -> None:
            raise RuntimeError("AudioMirror não inicializado")

        from marvin_hue.api.routes import positions as positions_routes

        monkeypatch.setattr(positions_routes.deps, "get_audio_mirror", _missing_audio)
        response = fastapi_test_client.post(
            "/positions", json={"lights": _SAMPLE_LIGHTS}
        )
        assert response.status_code == 200
        assert dest.exists()

    def test_get_delegates_to_repository(self, fastapi_test_client, monkeypatch):
        from marvin_hue.api.routes import positions as positions_routes

        class _FakeRepo:
            async def load(self) -> dict:
                return {
                    "lights": [
                        {
                            "name": "RepoLight",
                            "position": "center",
                            "enabled": True,
                        }
                    ],
                    "positions": [],
                }

            async def save(self, data: dict) -> None:
                raise AssertionError("save must not run on GET with data")

            def default_payload(self) -> dict:
                raise AssertionError("default_payload must not run on GET with data")

        monkeypatch.setattr(positions_routes, "_positions_repo", _FakeRepo())
        response = fastapi_test_client.get("/positions")
        assert response.status_code == 200
        assert response.json()["lights"][0]["name"] == "RepoLight"

    def test_get_empty_resets_via_repository_default(
        self, fastapi_test_client, monkeypatch
    ):
        from marvin_hue.api.routes import positions as positions_routes

        saved: list[dict] = []
        default = {
            "lights": [
                {"name": "Lâmpada 3", "position": "none", "enabled": True},
            ],
            "positions": [],
        }

        class _FakeRepo:
            async def load(self) -> dict:
                return {}

            async def save(self, data: dict) -> None:
                saved.append(data)

            def default_payload(self) -> dict:
                return default

        monkeypatch.setattr(positions_routes, "_positions_repo", _FakeRepo())
        response = fastapi_test_client.get("/positions")
        assert response.status_code == 200
        assert saved == [default]
        assert response.json()["lights"][0]["name"] == "Lâmpada 3"

    def test_post_delegates_save_to_repository(self, fastapi_test_client, monkeypatch):
        from marvin_hue.api.routes import positions as positions_routes

        saved: list[dict] = []

        class _FakeRepo:
            async def load(self) -> dict:
                return {"lights": [], "positions": [{"id": "none"}]}

            async def save(self, data: dict) -> None:
                saved.append(data)

            def default_payload(self) -> dict:
                raise AssertionError("default_payload must not run on POST")

        monkeypatch.setattr(positions_routes, "_positions_repo", _FakeRepo())
        response = fastapi_test_client.post(
            "/positions", json={"lights": _SAMPLE_LIGHTS}
        )
        assert response.status_code == 200
        assert saved
        assert saved[0]["lights"][0]["name"] == "Lâmpada 1"
        assert saved[0]["positions"][0]["id"] == "none"

    def test_reset_saves_repository_default_payload(
        self, fastapi_test_client, monkeypatch
    ):
        from marvin_hue.api.routes import positions as positions_routes

        saved: list[dict] = []
        default = {
            "lights": [
                {"name": "Lâmpada 3", "position": "none", "enabled": True},
            ],
            "positions": [{"id": "none"}],
        }

        class _FakeRepo:
            async def load(self) -> dict:
                return {}

            async def save(self, data: dict) -> None:
                saved.append(data)

            def default_payload(self) -> dict:
                return default

        monkeypatch.setattr(positions_routes, "_positions_repo", _FakeRepo())
        response = fastapi_test_client.post("/positions/reset")
        assert response.status_code == 200
        assert saved == [default]
        assert response.json()["lights"][0]["name"] == "Lâmpada 3"
