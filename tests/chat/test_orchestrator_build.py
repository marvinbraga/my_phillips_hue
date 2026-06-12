"""O orquestrador deve ser montado com create_agent + pilha de middleware."""
from __future__ import annotations


def test_orchestrator_uses_create_agent_with_middleware(monkeypatch, fake_controller, fake_manager):
    import marvin_hue.chat.agents.react_agent as ra

    seen = {}

    def fake_create_agent(**kw):
        seen.update(kw)
        return object()

    monkeypatch.setattr(ra, "create_agent", fake_create_agent, raising=False)

    class _FakeProvider:
        model = object()

    monkeypatch.setattr(
        ra.LLMProviderFactory, "create",
        classmethod(lambda cls, **kw: _FakeProvider()),
    )

    ra.HueLightAgent(fake_controller, fake_manager)

    assert "middleware" in seen and len(seen["middleware"]) >= 4
    assert "tools" in seen
    tool_names = {t.name for t in seen["tools"]}
    assert {"set_light_color", "set_brightness", "turn_off_lights", "apply_config"} <= tool_names
    assert len(seen["tools"]) >= 10  # sanity
    assert "checkpointer" in seen
    names = [type(m).__name__ for m in seen["middleware"]]
    assert "EyeSafetyMiddleware" in names
    assert "HueContextMiddleware" in names
