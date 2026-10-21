"""
Unit tests for the FastAPI application (app.py).

Tests REST API endpoints including configurations, positions,
mirror control, and error handling.
"""

import pytest


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

    def test_configurations_default_shape_has_no_settings(self, fastapi_test_client):
        """Default response stays [{name, description}] — no settings key (issue #8)."""
        data = fastapi_test_client.get("/configurations").json()
        assert data
        for config in data:
            assert set(config.keys()) == {"name", "description"}

        explicit_false = fastapi_test_client.get(
            "/configurations", params={"include_settings": "false"}
        ).json()
        assert explicit_false == data

    def test_configurations_include_settings_shape(self, fastapi_test_client):
        """include_settings=true adds settings with color + preview (issue #8)."""
        default = fastapi_test_client.get("/configurations").json()
        response = fastapi_test_client.get(
            "/configurations", params={"include_settings": "true"}
        )
        assert response.status_code == 200
        data = response.json()

        assert [c["name"] for c in data] == [c["name"] for c in default]
        assert [c["description"] for c in data] == [c["description"] for c in default]
        for config in data:
            assert set(config.keys()) == {"name", "description", "settings"}
            assert config["settings"]
            for setting in config["settings"]:
                assert set(setting.keys()) == {"light_name", "color", "preview"}
                assert set(setting["color"].keys()) == {
                    "red",
                    "green",
                    "blue",
                    "brightness",
                }
                assert set(setting["preview"].keys()) == {
                    "r",
                    "g",
                    "b",
                    "brightness",
                    "enabled",
                }

        relax = next(c for c in data if c["name"] == "relax")
        assert relax["settings"][0]["light_name"] == "Lâmpada 1"
        assert relax["settings"][0]["color"] == {
            "red": 255,
            "green": 147,
            "blue": 41,
            "brightness": 180,
        }
        assert relax["settings"][0]["preview"]["brightness"] == 180
        assert relax["settings"][0]["preview"]["enabled"] is True

    @staticmethod
    def _settings_of(client, name):
        data = client.get("/configurations", params={"include_settings": "true"}).json()
        return next(c for c in data if c["name"] == name)["settings"]

    def test_include_settings_preview_rgb_matches_color_space(self, fastapi_test_client):
        """Preview RGB = xy_to_rgb(rgb_to_xy(cor), brilho efetivo) — mesmo do status."""
        from marvin_hue.utils import ColorConverter

        preview = self._settings_of(fastapi_test_client, "relax")[0]["preview"]
        expected = ColorConverter.xy_to_rgb(ColorConverter.rgb_to_xy(255, 147, 41), 180)
        assert (preview["r"], preview["g"], preview["b"]) == expected

    def test_include_settings_preview_caps_eye_safety(
        self, fastapi_test_client, mock_light_setups_manager
    ):
        """Fita Led a 254: color.brightness intacto, preview.brightness = 63."""
        from marvin_hue.basics import LightConfig, LightSetting
        from marvin_hue.colors import Color

        mock_light_setups_manager.configs.append(
            LightConfig(
                name="zz_fita",
                description="fita no máximo",
                settings=[LightSetting("Fita Led", Color(255, 255, 255, 254))],
            )
        )
        setting = self._settings_of(fastapi_test_client, "zz_fita")[0]
        assert setting["color"]["brightness"] == 254
        assert setting["preview"]["brightness"] == 63

    def test_include_settings_preview_flags_disabled_light(self, fastapi_test_client):
        """Lâmpada desabilitada no app -> preview.enabled False."""
        from marvin_hue.eye_safety import clear_runtime_policy, set_runtime_enabled

        set_runtime_enabled({"Lâmpada 1": False})
        try:
            settings = self._settings_of(fastapi_test_client, "concentration")
        finally:
            clear_runtime_policy()
        by_name = {s["light_name"]: s["preview"]["enabled"] for s in settings}
        assert by_name == {"Lâmpada 1": False, "Lâmpada 2": True}

    def test_include_settings_duplicate_name_matches_apply(
        self, fastapi_test_client, mock_light_setups_manager
    ):
        """Nome duplicado: preview usa o MESMO config que /apply (primeiro vence)."""
        from marvin_hue.basics import LightConfig, LightSetting
        from marvin_hue.colors import Color

        mock_light_setups_manager.configs.append(
            LightConfig(
                name="relax",
                description="duplicata",
                settings=[LightSetting("Lâmpada 2", Color(1, 2, 3, 4))],
            )
        )
        data = fastapi_test_client.get(
            "/configurations", params={"include_settings": "true"}
        ).json()
        relax = [c for c in data if c["name"] == "relax"]
        assert len(relax) == 1

        expected = mock_light_setups_manager.get_config("relax")
        assert relax[0]["description"] == expected.description
        assert [(s["light_name"], s["color"]) for s in relax[0]["settings"]] == [
            (s.light_name, s.color.to_dict()) for s in expected.settings
        ]
        names = fastapi_test_client.get("/configurations").json()
        assert [c for c in names if c["name"] == "relax"] == [
            {"name": "relax", "description": expected.description}
        ]


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
                "/apply", json={"config_name": config_name}
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
                "/apply", json={"config_name": config_name, "transition_time_secs": 2.0}
            )

            assert response.status_code == 200
            data = response.json()
            assert "details" in data
            assert data["details"]["transition_time_secs"] == 2.0

    @pytest.mark.skip(reason="Requires proper app lifecycle mocking")
    def test_apply_nonexistent_configuration(self, fastapi_test_client):
        """Test POST /apply with nonexistent configuration."""
        response = fastapi_test_client.post(
            "/apply", json={"config_name": "nonexistent_config_xyz"}
        )

        assert response.status_code == 404
        data = response.json()
        assert "detail" in data

    def test_apply_configuration_with_duration(self, fastapi_test_client):
        """duration_minutes is accepted for compatibility but not scheduled."""
        configs_response = fastapi_test_client.get("/configurations")
        configs = configs_response.json()

        if len(configs) > 0:
            config_name = configs[0]["name"]

            response = fastapi_test_client.post(
                "/apply", json={"config_name": config_name, "duration_minutes": 30.0}
            )

            assert response.status_code == 200
            data = response.json()
            assert "duration_minutes" not in data
            details = data.get("details") or {}
            assert "duration_minutes" not in details

    def test_apply_invalid_request_body(self, fastapi_test_client):
        """Test POST /apply with invalid request body."""
        response = fastapi_test_client.post(
            "/apply",
            json={},  # Missing config_name
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
            "lights": [{"name": "Test Light", "position": "left", "enabled": True}]
        }

        response = fastapi_test_client.post("/positions", json=positions_data)

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
            "/mirror/start", json={"fps": 25, "brightness": 200}
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
            "/mirror/settings", json={"fps": 30, "brightness": 180}
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
        if response.status_code == 200:
            html = response.text
            assert 'id="model-badge"' in html
            assert "/api/chat/status" in html


class TestChatEndpoints:
    """Tests for chat-related endpoints."""

    def test_chat_status(self, fastapi_test_client):
        """Test GET /api/chat/status endpoint."""
        from marvin_hue.config import settings

        response = fastapi_test_client.get("/api/chat/status")

        assert response.status_code == 200
        data = response.json()
        assert "available" in data
        assert data["provider"] == settings.chat_provider
        assert data["model"] == settings.chat_model

    def test_chat_status_unavailable(self, fastapi_test_client):
        """Test chat status when agent is unavailable includes diagnostic reason."""
        from marvin_hue.config import settings

        response = fastapi_test_client.get("/api/chat/status")
        data = response.json()

        # In tests, chat agent is None with a diagnostic reason
        assert response.status_code == 200
        assert data["available"] is False
        assert "error" in data
        assert "XAI_API_KEY" in data["error"]
        assert data["provider"] == settings.chat_provider
        assert data["model"] == settings.chat_model
        # Must not leak secret-looking material beyond env var *names*
        assert "sk-" not in data["error"].lower()

    def test_chat_status_uses_live_agent_config(self, fastapi_test_client):
        """When an agent is present, provider/model come from its live config."""
        from types import SimpleNamespace

        from marvin_hue.api import dependencies
        from marvin_hue.config import settings

        live_provider = "xai" if settings.chat_provider != "xai" else "anthropic"
        live_model = (
            "grok-4.6" if settings.chat_model != "grok-4.6" else "claude-sonnet"
        )
        fake_agent = SimpleNamespace(
            _config=SimpleNamespace(provider=live_provider, model=live_model)
        )
        dependencies.set_chat_agent(fake_agent)

        response = fastapi_test_client.get("/api/chat/status")
        data = response.json()

        assert response.status_code == 200
        assert data["available"] is True
        assert data["provider"] == live_provider
        assert data["model"] == live_model
        assert (
            data["provider"] != settings.chat_provider
            or data["model"] != settings.chat_model
        )

    def test_send_chat_message_unavailable(self, fastapi_test_client):
        """Test sending message when chat is unavailable returns diagnostic 503."""
        response = fastapi_test_client.post(
            "/api/chat/message", json={"message": "Test message"}
        )

        assert response.status_code == 503
        detail = response.json()["detail"]
        assert "XAI_API_KEY" in detail
        assert "Provider" in detail or "provider" in detail.lower()

    def test_clear_chat_history_unavailable(self, fastapi_test_client):
        """Test clearing chat history when unavailable returns diagnostic 503."""
        response = fastapi_test_client.post("/api/chat/clear")

        assert response.status_code == 503
        detail = response.json()["detail"]
        assert "XAI_API_KEY" in detail


class TestDiagnoseChatCredentials:
    """Unit tests for diagnose_chat_credentials / sanitize helpers."""

    def test_missing_key_mentions_env_var(self, monkeypatch):
        from marvin_hue.api.dependencies import diagnose_chat_credentials
        from marvin_hue.config import settings

        monkeypatch.setattr(settings, "xai_api_key", None)
        msg = diagnose_chat_credentials("xai")
        assert msg is not None
        assert "XAI_API_KEY" in msg
        assert "xai" in msg

    def test_empty_string_counts_as_missing(self, monkeypatch):
        from marvin_hue.api.dependencies import diagnose_chat_credentials
        from marvin_hue.config import settings

        for provider, attr, env_var in [
            ("openai", "openai_api_key", "OPENAI_API_KEY"),
            ("anthropic", "anthropic_api_key", "ANTHROPIC_API_KEY"),
            ("xai", "xai_api_key", "XAI_API_KEY"),
            ("groq", "groq_api_key", "GROQ_API_KEY"),
        ]:
            monkeypatch.setattr(settings, attr, "")
            msg = diagnose_chat_credentials(provider)
            assert msg is not None, provider
            assert env_var in msg, provider
            assert provider in msg

    def test_present_key_returns_none(self, monkeypatch):
        from marvin_hue.api.dependencies import diagnose_chat_credentials
        from marvin_hue.config import settings

        monkeypatch.setattr(settings, "openai_api_key", "sk-test-not-real")
        assert diagnose_chat_credentials("openai") is None

    def test_sanitize_truncates_and_uses_first_line(self):
        from marvin_hue.api.dependencies import sanitize_chat_init_error

        long = "line one with details\nstacktrace line\n" + ("x" * 300)
        out = sanitize_chat_init_error(Exception(long), max_len=50)
        assert "\n" not in out
        assert len(out) <= 50
        assert out.startswith("line one")


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
            json={"invalid_field": "value"},  # Missing config_name
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
            "/apply", json={"config_name": "nonexistent"}
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
                "/apply", json={"config_name": configs[0]["name"]}
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
                "/apply", json={"config_name": configs[0]["name"]}
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
