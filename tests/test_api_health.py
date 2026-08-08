"""Tests for health dashboard API and HTML page."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import Mock


class TestHealthApi:
    """GET /api/health aggregation."""

    def test_api_health_ok_shape(self, fastapi_test_client):
        response = fastapi_test_client.get("/api/health")
        assert response.status_code == 200
        data = response.json()

        assert "bridge" in data
        assert "lights" in data
        assert "mirror" in data
        assert "chat" in data
        assert "registry" in data
        assert "schedules" in data
        assert "timestamp" in data

        bridge = data["bridge"]
        assert "connected" in bridge
        assert "bridge_ip" in bridge
        assert "light_count" in bridge
        assert isinstance(bridge["connected"], bool)
        assert isinstance(bridge["light_count"], int)

        lights = data["lights"]
        assert "total" in lights
        assert "unreachable" in lights
        assert "disabled_in_app" in lights

        mirror = data["mirror"]
        assert "running" in mirror
        assert mirror["running"] is False  # mock_screen_mirror default

        chat = data["chat"]
        assert chat["available"] is False  # fixture disables chat agent
        assert chat["reason"] is not None

        registry = data["registry"]
        assert "count" in registry
        assert "db_path" in registry
        assert "last_sync_at" in registry
        assert isinstance(registry["count"], int)

        schedules = data["schedules"]
        assert "enabled_count" in schedules
        assert "runner_alive" in schedules

        # ISO-like timestamp
        datetime.fromisoformat(data["timestamp"])

    def test_api_health_bridge_connected_with_mock(self, fastapi_test_client):
        response = fastapi_test_client.get("/api/health")
        data = response.json()
        assert data["bridge"]["connected"] is True
        assert data["bridge"]["light_count"] >= 1

    def test_api_health_unreachable_count(
        self, fastapi_test_client, mock_hue_controller
    ):
        # Make one light unreachable via get_lights_status
        mock_hue_controller.get_lights_status = Mock(
            return_value=[
                {
                    "name": "Lâmpada 1",
                    "on": True,
                    "brightness": 100,
                    "reachable": True,
                    "color": {"r": 1, "g": 2, "b": 3},
                },
                {
                    "name": "Lâmpada 2",
                    "on": False,
                    "brightness": 0,
                    "reachable": False,
                    "color": {"r": 50, "g": 50, "b": 50},
                },
            ]
        )
        response = fastapi_test_client.get("/api/health")
        assert response.status_code == 200
        lights = response.json()["lights"]
        assert lights["total"] == 2
        assert lights["unreachable"] == 1

    def test_api_health_mirror_running(self, fastapi_test_client, mock_screen_mirror):
        mock_screen_mirror.get_status.return_value = {
            "running": True,
            "fps": 30,
            "brightness": 200,
            "colors": {},
            "profile": None,
        }
        response = fastapi_test_client.get("/api/health")
        assert response.status_code == 200
        mirror = response.json()["mirror"]
        assert mirror["running"] is True
        assert mirror["fps"] == 30

    def test_api_health_registry_last_sync(
        self, fastapi_test_client, monkeypatch
    ):
        from marvin_hue.api import dependencies

        svc = dependencies.get_light_registry_service()
        stamp = datetime(2026, 8, 8, 12, 0, 0, tzinfo=timezone.utc)
        svc.last_sync_at = stamp
        response = fastapi_test_client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["registry"]["last_sync_at"] == stamp.isoformat()


class TestHealthPage:
    """GET /health HTML dashboard."""

    def test_health_page_200(self, fastapi_test_client):
        response = fastapi_test_client.get("/health")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        body = response.text
        assert "Saúde" in body
        assert "navbar" in body
        assert "Controle" in body
        assert "Lâmpadas" in body
        assert "/api/health" in body or "health.js" in body

    def test_nav_on_index(self, fastapi_test_client):
        response = fastapi_test_client.get("/")
        assert response.status_code == 200
        body = response.text
        assert "navbar" in body
        assert 'href="/health"' in body
        assert 'href="/groups"' in body
        assert 'href="/schedules"' in body
        assert 'href="/chat"' in body
        assert 'href="/mirror"' in body
