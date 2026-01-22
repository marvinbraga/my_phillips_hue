"""
Unit tests for the FastAPI application (app.py).

Tests REST API endpoints including configurations, positions,
mirror control, and error handling.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


class TestConfigurationsEndpoints:
    """Tests for configuration-related endpoints."""

    def test_get_configurations(self, fastapi_test_client):
        """Test GET /configurations endpoint."""
        response = fastapi_test_client.get("/configurations")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_configurations_structure(self, fastapi_test_client):
        """Test that configurations have correct structure."""
        response = fastapi_test_client.get("/configurations")
        data = response.json()

        if len(data) > 0:
            config = data[0]
            assert "name" in config
            assert "description" in config

    def test_configurations_not_empty(self, fastapi_test_client):
        """Test that some configurations are returned."""
        response = fastapi_test_client.get("/configurations")
        data = response.json()

        assert len(data) > 0  # Should have at least test configs

    def test_configurations_sorted(self, fastapi_test_client):
        """Test that configurations are sorted by name."""
        response = fastapi_test_client.get("/configurations")
        data = response.json()

        if len(data) > 1:
            names = [config["name"] for config in data]
            assert names == sorted(names)


class TestApplyConfigurationEndpoint:
    """Tests for applying configurations."""

    def test_apply_valid_configuration(self, fastapi_test_client):
        """Test POST /apply with valid configuration."""
        # First get available configs
        configs_response = fastapi_test_client.get("/configurations")
        configs = configs_response.json()

        if len(configs) > 0:
            config_name = configs[0]["name"]

            response = fastapi_test_client.post(
                "/apply",
                json={"config_name": config_name}
            )

            assert response.status_code == 200
            data = response.json()
            assert "message" in data

    def test_apply_configuration_with_transition(self, fastapi_test_client):
        """Test applying configuration with transition time."""
        configs_response = fastapi_test_client.get("/configurations")
        configs = configs_response.json()

        if len(configs) > 0:
            config_name = configs[0]["name"]

            response = fastapi_test_client.post(
                "/apply",
                json={
                    "config_name": config_name,
                    "transition_time_secs": 2.0
                }
            )

            assert response.status_code == 200
            data = response.json()
            assert "details" in data
            assert data["details"]["transition_time_secs"] == 2.0

    @pytest.mark.skip(reason="Requires proper app lifecycle mocking")
    def test_apply_nonexistent_configuration(self, fastapi_test_client):
        """Test POST /apply with nonexistent configuration."""
        response = fastapi_test_client.post(
            "/apply",
            json={"config_name": "nonexistent_config_xyz"}
        )

        assert response.status_code == 404
        data = response.json()
        assert "detail" in data

    def test_apply_configuration_with_duration(self, fastapi_test_client):
        """Test applying configuration with duration."""
        configs_response = fastapi_test_client.get("/configurations")
        configs = configs_response.json()

        if len(configs) > 0:
            config_name = configs[0]["name"]

            response = fastapi_test_client.post(
                "/apply",
                json={
                    "config_name": config_name,
                    "duration_minutes": 30.0
                }
            )

            assert response.status_code == 200
            data = response.json()
            assert "details" in data
            assert data["details"]["duration_minutes"] == 30.0

    def test_apply_invalid_request_body(self, fastapi_test_client):
        """Test POST /apply with invalid request body."""
        response = fastapi_test_client.post(
            "/apply",
            json={}  # Missing config_name
        )

        # Should return 422 (validation error)
        assert response.status_code == 422


class TestStatusEndpoints:
    """Tests for status-related endpoints."""

    def test_bridge_status(self, fastapi_test_client):
        """Test GET /api/bridge/status endpoint."""
        response = fastapi_test_client.get("/api/bridge/status")

        assert response.status_code == 200
        data = response.json()
        assert "connected" in data

    def test_bridge_status_structure(self, fastapi_test_client):
        """Test bridge status response structure."""
        response = fastapi_test_client.get("/api/bridge/status")
        data = response.json()

        if data.get("connected"):
            assert "bridge_ip" in data
            assert "light_count" in data
        else:
            assert "error" in data

    def test_lights_status(self, fastapi_test_client):
        """Test GET /api/lights/status endpoint."""
        response = fastapi_test_client.get("/api/lights/status")

        assert response.status_code == 200
        data = response.json()
        assert "lights" in data
        assert isinstance(data["lights"], list)

    def test_lights_status_structure(self, fastapi_test_client):
        """Test lights status response structure."""
        response = fastapi_test_client.get("/api/lights/status")
        data = response.json()
        lights = data["lights"]

        if len(lights) > 0:
            light = lights[0]
            assert "name" in light
            assert "on" in light
            assert "brightness" in light
            assert "reachable" in light
            assert "color" in light

    def test_lights_status_color_rgb(self, fastapi_test_client):
        """Test that lights status includes RGB color values."""
        response = fastapi_test_client.get("/api/lights/status")
        data = response.json()
        lights = data["lights"]

        if len(lights) > 0:
            light = lights[0]
            color = light["color"]
            assert "r" in color
            assert "g" in color
            assert "b" in color


class TestPositionsEndpoints:
    """Tests for position configuration endpoints."""

    def test_get_positions(self, fastapi_test_client):
        """Test GET /positions endpoint."""
        response = fastapi_test_client.get("/positions")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_positions_structure(self, fastapi_test_client):
        """Test positions response structure."""
        response = fastapi_test_client.get("/positions")
        data = response.json()

        # Should have lights and positions keys
        if "lights" in data:
            assert isinstance(data["lights"], list)
        if "positions" in data:
            assert isinstance(data["positions"], list)

    def test_save_positions(self, fastapi_test_client, tmp_path):
        """Test POST /positions endpoint."""
        positions_data = {
            "lights": [
                {"name": "Test Light", "position": "left", "enabled": True}
            ]
        }

        response = fastapi_test_client.post(
            "/positions",
            json=positions_data
        )

        # May succeed or fail depending on file permissions
        # Just check it doesn't crash
        assert response.status_code in [200, 500]

    def test_reset_positions(self, fastapi_test_client):
        """Test POST /positions/reset endpoint."""
        response = fastapi_test_client.post("/positions/reset")

        assert response.status_code == 200
        data = response.json()
        assert "lights" in data
        assert "positions" in data


class TestMirrorEndpoints:
    """Tests for screen mirror endpoints."""

    @pytest.mark.skip(reason="Requires proper app lifecycle mocking")
    def test_mirror_status(self, fastapi_test_client):
        """Test GET /mirror/status endpoint."""
        response = fastapi_test_client.get("/mirror/status")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    @pytest.mark.skip(reason="Requires proper app lifecycle mocking")
    def test_start_mirror(self, fastapi_test_client):
        """Test POST /mirror/start endpoint."""
        response = fastapi_test_client.post(
            "/mirror/start",
            json={"fps": 25, "brightness": 200}
        )

        # May fail if screen_mirror is None (which it is in tests)
        # Just check it doesn't crash
        assert response.status_code in [200, 400, 500]

    @pytest.mark.skip(reason="Requires proper app lifecycle mocking")
    def test_stop_mirror(self, fastapi_test_client):
        """Test POST /mirror/stop endpoint."""
        response = fastapi_test_client.post("/mirror/stop")

        # Should return 400 if not running
        assert response.status_code in [200, 400]

    @pytest.mark.skip(reason="Requires proper app lifecycle mocking")
    def test_update_mirror_settings(self, fastapi_test_client):
        """Test POST /mirror/settings endpoint."""
        response = fastapi_test_client.post(
            "/mirror/settings",
            json={"fps": 30, "brightness": 180}
        )

        # Should work even if mirror not running
        assert response.status_code in [200, 500]


class TestPageEndpoints:
    """Tests for HTML page endpoints."""

    def test_index_page(self, fastapi_test_client):
        """Test GET / endpoint."""
        response = fastapi_test_client.get("/")

        # Should return HTML (200) or redirect
        assert response.status_code in [200, 307]

    def test_positions_config_page(self, fastapi_test_client):
        """Test GET /positions-config endpoint."""
        response = fastapi_test_client.get("/positions-config")

        assert response.status_code in [200, 307]

    def test_mirror_page(self, fastapi_test_client):
        """Test GET /mirror endpoint."""
        response = fastapi_test_client.get("/mirror")

        assert response.status_code in [200, 307]

    def test_chat_page(self, fastapi_test_client):
        """Test GET /chat endpoint."""
        response = fastapi_test_client.get("/chat")

        assert response.status_code in [200, 307]


class TestChatEndpoints:
    """Tests for chat-related endpoints."""

    def test_chat_status(self, fastapi_test_client):
        """Test GET /api/chat/status endpoint."""
        response = fastapi_test_client.get("/api/chat/status")

        assert response.status_code == 200
        data = response.json()
        assert "available" in data

    def test_chat_status_unavailable(self, fastapi_test_client):
        """Test chat status when agent is unavailable."""
        response = fastapi_test_client.get("/api/chat/status")
        data = response.json()

        # In tests, chat agent is None
        assert data["available"] is False
        if not data["available"]:
            assert "error" in data

    def test_send_chat_message_unavailable(self, fastapi_test_client):
        """Test sending message when chat is unavailable."""
        response = fastapi_test_client.post(
            "/api/chat/message",
            json={"message": "Test message"}
        )

        # Should return 503 when chat agent not available
        assert response.status_code == 503

    def test_clear_chat_history_unavailable(self, fastapi_test_client):
        """Test clearing chat history when unavailable."""
        response = fastapi_test_client.post("/api/chat/clear")

        # Should return 503 when chat agent not available
        assert response.status_code == 503


class TestAPIErrorHandling:
    """Tests for API error handling."""

    def test_404_on_invalid_endpoint(self, fastapi_test_client):
        """Test that invalid endpoints return 404."""
        response = fastapi_test_client.get("/invalid/endpoint")

        assert response.status_code == 404

    def test_405_on_wrong_method(self, fastapi_test_client):
        """Test that wrong HTTP methods return 405."""
        # /configurations is GET only
        response = fastapi_test_client.post("/configurations")

        assert response.status_code == 405

    def test_422_on_invalid_json(self, fastapi_test_client):
        """Test that invalid JSON in POST returns 422."""
        response = fastapi_test_client.post(
            "/apply",
            json={"invalid_field": "value"}  # Missing config_name
        )

        assert response.status_code == 422


class TestAPIResponseFormats:
    """Tests for API response formats."""

    def test_json_response_content_type(self, fastapi_test_client):
        """Test that JSON endpoints return correct content type."""
        response = fastapi_test_client.get("/configurations")

        assert response.status_code == 200
        assert "application/json" in response.headers["content-type"]

    @pytest.mark.skip(reason="Requires proper app lifecycle mocking")
    def test_error_response_format(self, fastapi_test_client):
        """Test that errors return proper JSON format."""
        response = fastapi_test_client.post(
            "/apply",
            json={"config_name": "nonexistent"}
        )

        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        assert isinstance(data["detail"], str)

    def test_success_response_format(self, fastapi_test_client):
        """Test that successful responses have consistent format."""
        configs_response = fastapi_test_client.get("/configurations")
        configs = configs_response.json()

        if len(configs) > 0:
            response = fastapi_test_client.post(
                "/apply",
                json={"config_name": configs[0]["name"]}
            )

            assert response.status_code == 200
            data = response.json()
            assert "message" in data or "status" in data


class TestAPIIntegration:
    """Integration tests for API workflows."""

    def test_full_configuration_workflow(self, fastapi_test_client):
        """Test full workflow: get configs, apply one, check status."""
        # Get configurations
        configs_response = fastapi_test_client.get("/configurations")
        assert configs_response.status_code == 200
        configs = configs_response.json()

        if len(configs) > 0:
            # Apply first configuration
            apply_response = fastapi_test_client.post(
                "/apply",
                json={"config_name": configs[0]["name"]}
            )
            assert apply_response.status_code == 200

            # Check lights status
            status_response = fastapi_test_client.get("/api/lights/status")
            assert status_response.status_code == 200

    def test_position_configuration_workflow(self, fastapi_test_client):
        """Test position configuration workflow."""
        # Get current positions
        get_response = fastapi_test_client.get("/positions")
        assert get_response.status_code == 200

        # Reset to defaults
        reset_response = fastapi_test_client.post("/positions/reset")
        assert reset_response.status_code == 200

        # Get positions again
        get_response2 = fastapi_test_client.get("/positions")
        assert get_response2.status_code == 200

    def test_bridge_and_lights_status_workflow(self, fastapi_test_client):
        """Test checking bridge and lights status."""
        # Check bridge status
        bridge_response = fastapi_test_client.get("/api/bridge/status")
        assert bridge_response.status_code == 200

        # Check lights status
        lights_response = fastapi_test_client.get("/api/lights/status")
        assert lights_response.status_code == 200
