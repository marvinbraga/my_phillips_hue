"""API smoke tests for /api/history."""


class TestHistoryAPI:
    def test_list_empty(self, fastapi_test_client):
        r = fastapi_test_client.get("/api/history")
        assert r.status_code == 200
        assert r.json() == []

    def test_manual_snapshot_and_undo(self, fastapi_test_client):
        r = fastapi_test_client.post(
            "/api/history/snapshot",
            json={"label": "manual test", "source": "manual"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["source"] == "manual"
        assert body["id"] is not None

        listed = fastapi_test_client.get("/api/history").json()
        assert len(listed) >= 1

        undo = fastapi_test_client.post("/api/history/undo")
        assert undo.status_code == 200, undo.text
        assert "restored_count" in undo.json()

    def test_apply_hooks_snapshot(self, fastapi_test_client):
        before = fastapi_test_client.get("/api/history").json()
        r = fastapi_test_client.post(
            "/apply",
            json={"config_name": "concentration", "transition_time_secs": 0},
        )
        assert r.status_code == 200, r.text
        after = fastapi_test_client.get("/api/history").json()
        assert len(after) >= len(before) + 1
        assert any(x["source"] == "apply" for x in after)

    def test_undo_empty_404(self, fastapi_test_client):
        # Fresh DB already may have snapshots from other tests in same client —
        # use empty history only when list is empty after nothing ran.
        # This client is fresh per fixture.
        listed = fastapi_test_client.get("/api/history").json()
        if listed:
            return
        r = fastapi_test_client.post("/api/history/undo")
        assert r.status_code == 404
