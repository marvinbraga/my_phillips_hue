"""API tests for /api/lights registry CRUD + bridge sync."""


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

    def test_sync_name_conflict_returns_409(
        self, fastapi_test_client, mock_hue_controller
    ):
        """Rename-on-bridge into an existing active name must surface as 409."""
        from types import SimpleNamespace

        fastapi_test_client.post("/api/lights", json={"name": "Target"})
        fastapi_test_client.post(
            "/api/lights",
            json={"name": "Other", "bridge_light_id": "conflict-uid"},
        )
        # Bridge reports the uid formerly "Other" now named "Target".
        # Update get_light_objects so refresh_and_sync does not restore defaults.
        conflict_light = SimpleNamespace(
            name="Target",
            uniqueid="conflict-uid",
            light_id=99,
        )
        mock_hue_controller.bridge.get_light_objects.return_value = [conflict_light]
        mock_hue_controller.lights = [conflict_light]
        r = fastapi_test_client.post("/api/lights/sync")
        assert r.status_code == 409, r.text
        assert "conflict" in r.json()["detail"].lower()
