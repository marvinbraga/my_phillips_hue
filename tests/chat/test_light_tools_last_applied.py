"""Chat ``apply_config`` goes through ApplyConfigService (issue #14).

The async ``coroutine`` (REST / WebSocket chat) takes the "before apply"
snapshot and records the last applied scene. The sync ``func`` keeps the old
behaviour and never touches the event-loop-bound services.
"""
from __future__ import annotations

import pytest

from marvin_hue.apply_result import ApplyResult


class _FakeRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def record(self, name: str, *, source: str) -> None:
        self.calls.append((name, source))

    async def clear(self, *, source: str) -> None:  # pragma: no cover
        raise AssertionError("apply never clears")


class _FakeHistory:
    def __init__(self) -> None:
        self.snapshots: list[tuple[str, str | None]] = []

    async def snapshot(self, hue, *, source: str, label: str | None = None) -> None:
        self.snapshots.append((source, label))


def _tools(controller, manager, provider, history_provider=lambda: None):
    from marvin_hue.chat.services import ChatServices
    from marvin_hue.chat.tools.light_tools import build_light_tools

    services = ChatServices(
        last_applied_provider=provider, history_provider=history_provider
    )
    return {
        t.name: t for t in build_light_tools(controller, manager, services=services)
    }


@pytest.mark.asyncio
async def test_ainvoke_records_with_chat_source(fake_controller, fake_manager):
    fake_controller.apply_light_config.return_value = ApplyResult(
        applied=("Lâmpada 1",), failed=()
    )
    recorder = _FakeRecorder()
    tools = _tools(fake_controller, fake_manager, lambda: recorder)

    out = await tools["apply_config"].ainvoke({"config_name": "noite_relaxante"})

    assert "aplicada" in out
    assert recorder.calls == [("noite_relaxante", "chat")]


@pytest.mark.asyncio
async def test_ainvoke_partial_records(fake_controller, fake_manager):
    fake_controller.apply_light_config.return_value = ApplyResult(
        applied=("Lâmpada 1",), failed=(("Fita Led", "timeout"),)
    )
    recorder = _FakeRecorder()
    tools = _tools(fake_controller, fake_manager, lambda: recorder)

    out = await tools["apply_config"].ainvoke({"config_name": "noite_relaxante"})

    assert "parcialmente" in out
    assert recorder.calls == [("noite_relaxante", "chat")]


@pytest.mark.asyncio
async def test_ainvoke_all_failed_does_not_record(fake_controller, fake_manager):
    fake_controller.apply_light_config.return_value = ApplyResult(
        applied=(), failed=(("Lâmpada 1", "x"),)
    )
    recorder = _FakeRecorder()
    tools = _tools(fake_controller, fake_manager, lambda: recorder)

    out = await tools["apply_config"].ainvoke({"config_name": "noite_relaxante"})

    assert "Falha" in out
    assert recorder.calls == []


@pytest.mark.asyncio
async def test_ainvoke_unknown_scene_does_not_record(fake_controller, fake_manager):
    recorder = _FakeRecorder()
    tools = _tools(fake_controller, fake_manager, lambda: recorder)

    out = await tools["apply_config"].ainvoke({"config_name": "inexistente"})

    assert "não encontrada" in out
    assert recorder.calls == []


@pytest.mark.asyncio
async def test_ainvoke_takes_snapshot_before_apply(fake_controller, fake_manager):
    fake_controller.apply_light_config.return_value = ApplyResult(
        applied=("Lâmpada 1",), failed=()
    )
    recorder = _FakeRecorder()
    history = _FakeHistory()
    tools = _tools(fake_controller, fake_manager, lambda: recorder, lambda: history)

    await tools["apply_config"].ainvoke({"config_name": "noite_relaxante"})

    assert history.snapshots == [("chat", "before apply noite_relaxante")]
    assert recorder.calls == [("noite_relaxante", "chat")]


@pytest.mark.asyncio
async def test_ainvoke_storage_failure_is_fail_open(fake_controller, fake_manager):
    """A broken store behind the real service never breaks the chat apply."""
    from unittest.mock import AsyncMock, MagicMock

    from marvin_hue.services.last_applied_scene import LastAppliedSceneService

    fake_controller.apply_light_config.return_value = ApplyResult(
        applied=("Lâmpada 1",), failed=()
    )
    repo = MagicMock()
    repo.record = AsyncMock(side_effect=RuntimeError("db locked"))
    service = LastAppliedSceneService(repo, lambda: fake_manager)
    tools = _tools(fake_controller, fake_manager, lambda: service)

    out = await tools["apply_config"].ainvoke({"config_name": "noite_relaxante"})

    assert "aplicada" in out
    repo.record.assert_awaited_once()


@pytest.mark.asyncio
async def test_ainvoke_history_provider_raising_still_applies(
    fake_controller, fake_manager
):
    fake_controller.apply_light_config.return_value = ApplyResult(
        applied=("Lâmpada 1",), failed=()
    )

    def broken():
        raise RuntimeError("history not initialized")

    tools = _tools(fake_controller, fake_manager, lambda: None, broken)
    out = await tools["apply_config"].ainvoke({"config_name": "noite_relaxante"})
    assert "aplicada" in out


@pytest.mark.asyncio
async def test_ainvoke_controller_error_message(fake_controller, fake_manager):
    fake_controller.apply_light_config.side_effect = RuntimeError("bridge down")
    tools = _tools(fake_controller, fake_manager, lambda: None)
    out = await tools["apply_config"].ainvoke({"config_name": "noite_relaxante"})
    assert out == "Erro ao aplicar 'noite_relaxante': bridge down"


@pytest.mark.asyncio
@pytest.mark.parametrize("broken", ["none", "raises"])
async def test_ainvoke_without_service_still_applies(
    fake_controller, fake_manager, broken
):
    fake_controller.apply_light_config.return_value = ApplyResult(
        applied=("Lâmpada 1",), failed=()
    )

    def provider():
        if broken == "raises":
            raise RuntimeError("not initialized")
        return None

    tools = _tools(fake_controller, fake_manager, provider)
    out = await tools["apply_config"].ainvoke({"config_name": "noite_relaxante"})
    assert "aplicada" in out
    fake_controller.apply_light_config.assert_called_once()


def test_sync_invoke_does_not_record(fake_controller, fake_manager):
    fake_controller.apply_light_config.return_value = ApplyResult(
        applied=("Lâmpada 1",), failed=()
    )
    recorder = _FakeRecorder()
    tools = _tools(fake_controller, fake_manager, lambda: recorder)

    out = tools["apply_config"].invoke({"config_name": "noite_relaxante"})

    assert "aplicada" in out
    assert recorder.calls == []


def test_default_history_provider_returns_none_without_service():
    from marvin_hue.api import dependencies
    from marvin_hue.chat.services import default_history_provider

    original = dependencies._scene_history_service
    dependencies.set_scene_history_service(None)
    try:
        assert default_history_provider() is None
    finally:
        dependencies.set_scene_history_service(original)


def test_default_provider_returns_none_without_service():
    from marvin_hue.api import dependencies
    from marvin_hue.chat.services import default_last_applied_provider

    original = dependencies.get_last_applied_scene_service_optional()
    dependencies.set_last_applied_scene_service(None)
    try:
        assert default_last_applied_provider() is None
    finally:
        dependencies.set_last_applied_scene_service(original)
