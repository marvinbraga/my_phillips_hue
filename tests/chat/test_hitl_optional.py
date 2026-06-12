"""HITL opcional: HumanInTheLoopMiddleware só entra na pilha com require_approval."""
from __future__ import annotations


def _build(monkeypatch, fake_controller, fake_manager, bindable_model_factory, **cfg):
    import marvin_hue.chat.agents.react_agent as ra

    seen = {}

    def fake_create_agent(**kw):
        seen.update(kw)
        return object()

    monkeypatch.setattr(ra, "create_agent", fake_create_agent, raising=False)

    class _FakeProvider:
        model = bindable_model_factory()

    monkeypatch.setattr(
        ra.LLMProviderFactory, "create",
        classmethod(lambda cls, **kw: _FakeProvider()),
    )
    ra.HueLightAgent(fake_controller, fake_manager, config=ra.AgentConfig(**cfg))
    return [type(m).__name__ for m in seen["middleware"]]


def test_hitl_absent_by_default(monkeypatch, fake_controller, fake_manager, bindable_model_factory):
    names = _build(monkeypatch, fake_controller, fake_manager, bindable_model_factory)
    assert "HumanInTheLoopMiddleware" not in names


def test_hitl_present_when_enabled(monkeypatch, fake_controller, fake_manager, bindable_model_factory):
    names = _build(
        monkeypatch, fake_controller, fake_manager, bindable_model_factory,
        require_approval=True,
    )
    assert "HumanInTheLoopMiddleware" in names
