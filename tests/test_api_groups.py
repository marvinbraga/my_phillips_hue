"""API smoke tests for /api/groups."""


class TestGroupsAPI:
    def test_list_empty(self, fastapi_test_client):
        r = fastapi_test_client.get("/api/groups")
        assert r.status_code == 200
        assert r.json() == []

    def test_create_get_patch_delete(self, fastapi_test_client):
        light = fastapi_test_client.post(
            "/api/lights", json={"name": "Hue Iris"}
        ).json()
        r = fastapi_test_client.post(
            "/api/groups",
            json={
                "name": "Sala",
                "room": "Living",
                "light_ids": [light["id"]],
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["name"] == "Sala"
        assert body["light_ids"] == [light["id"]]
        gid = body["id"]

        r2 = fastapi_test_client.get(f"/api/groups/{gid}")
        assert r2.status_code == 200
        assert r2.json()["room"] == "Living"

        r3 = fastapi_test_client.patch(
            f"/api/groups/{gid}", json={"notes": "main"}
        )
        assert r3.status_code == 200
        assert r3.json()["notes"] == "main"

        r4 = fastapi_test_client.delete(f"/api/groups/{gid}")
        assert r4.status_code == 200
        assert r4.json()["deleted_at"] is not None

        r5 = fastapi_test_client.get(f"/api/groups/{gid}")
        assert r5.status_code == 404

    def test_power_and_apply(self, fastapi_test_client, mock_hue_controller):
        light = fastapi_test_client.post(
            "/api/lights", json={"name": "Lâmpada 1"}
        ).json()
        group = fastapi_test_client.post(
            "/api/groups",
            json={"name": "Desk", "light_ids": [light["id"]]},
        ).json()

        r = fastapi_test_client.post(
            f"/api/groups/{group['id']}/power", json={"on": True}
        )
        assert r.status_code == 200, r.text
        assert r.json()["on"] is True

        r2 = fastapi_test_client.post(
            f"/api/groups/{group['id']}/apply",
            json={"config_name": "concentration", "transition_time_secs": 0},
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["config_name"] == "concentration"

    def test_groups_html_page(self, fastapi_test_client):
        r = fastapi_test_client.get("/groups")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")
