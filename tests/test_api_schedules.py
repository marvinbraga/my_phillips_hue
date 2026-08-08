"""API smoke tests for /api/schedules."""


class TestSchedulesAPI:
    def test_list_empty(self, fastapi_test_client):
        r = fastapi_test_client.get("/api/schedules")
        assert r.status_code == 200
        assert r.json() == []

    def test_crud_and_run(self, fastapi_test_client):
        r = fastapi_test_client.post(
            "/api/schedules",
            json={
                "name": "Morning",
                "time_hhmm": "07:00",
                "action_type": "power_on",
                "days_of_week": "0,1,2,3,4",
                "enabled": True,
                "action_payload": {},
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        sid = body["id"]
        assert body["time_hhmm"] == "07:00"

        r2 = fastapi_test_client.get(f"/api/schedules/{sid}")
        assert r2.status_code == 200

        r3 = fastapi_test_client.patch(
            f"/api/schedules/{sid}",
            json={"enabled": False, "time_hhmm": "07:30"},
        )
        assert r3.status_code == 200
        assert r3.json()["enabled"] is False
        assert r3.json()["time_hhmm"] == "07:30"

        # re-enable for run
        fastapi_test_client.patch(f"/api/schedules/{sid}", json={"enabled": True})
        run = fastapi_test_client.post(f"/api/schedules/{sid}/run")
        assert run.status_code == 200, run.text
        assert run.json()["status"] == "ok"

        r4 = fastapi_test_client.delete(f"/api/schedules/{sid}")
        assert r4.status_code == 204

        r5 = fastapi_test_client.get(f"/api/schedules/{sid}")
        assert r5.status_code == 404

    def test_apply_config_schedule(self, fastapi_test_client):
        r = fastapi_test_client.post(
            "/api/schedules",
            json={
                "name": "Night",
                "time_hhmm": "22:00",
                "action_type": "apply_config",
                "action_payload": {"config_name": "concentration"},
            },
        )
        assert r.status_code == 201, r.text
        sid = r.json()["id"]
        run = fastapi_test_client.post(f"/api/schedules/{sid}/run")
        assert run.status_code == 200, run.text

    def test_schedules_html(self, fastapi_test_client):
        r = fastapi_test_client.get("/schedules")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")
