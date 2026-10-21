"""Unit tests for MirrorControlService start/stop/settings orchestration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from marvin_hue.entertainment.models import ChannelInfo, EntertainmentAreaInfo
from marvin_hue.services.mirror_control import MirrorControlService


def _mirror(*, running: bool = False, transport: str = "rest") -> MagicMock:
    mirror = MagicMock()
    mirror.is_running.return_value = running
    mirror.load_light_positions.return_value = []
    mirror.transition_time = 0
    mirror.get_status.return_value = {
        "running": running,
        "colors": {},
        "transport": transport,
    }
    mirror.output_port = MagicMock(transport=transport)
    mirror.entertainment_area_id = None
    mirror.entertainment_enabled = False
    return mirror


def _service(
    screen: MagicMock,
    audio: MagicMock,
    *,
    ent: MagicMock | None = None,
    hue: MagicMock | None = None,
    manager: MagicMock | None = None,
    history: MagicMock | None = None,
) -> MirrorControlService:
    return MirrorControlService(
        get_screen=lambda: screen,
        get_audio=lambda: audio,
        get_hue=lambda: hue if hue is not None else MagicMock(),
        get_manager=lambda: manager if manager is not None else MagicMock(),
        get_entertainment=lambda: ent,
        get_history=lambda: history,
    )


def _ready_entertainment(
    *,
    area_id: str = "area-1",
    channel_name: str = "Hue Play 1",
) -> MagicMock:
    area = EntertainmentAreaInfo(
        id=area_id,
        name="Sala",
        channels=(ChannelInfo(0, name=channel_name),),
    )
    ent = MagicMock()
    ent.is_ready = True
    ent.is_streaming = False
    ent.list_areas = AsyncMock(return_value=[area])
    ent.start_stream = AsyncMock()
    ent.stop_stream = AsyncMock()
    return ent


def _assert_stop_never_ends_output(mirror: MagicMock) -> None:
    assert mirror.stop.called
    for called in mirror.stop.call_args_list:
        assert called.kwargs.get("end_output") is False, (
            f"stop() must use end_output=False, got {called}"
        )


@pytest.mark.asyncio
async def test_start_screen_sets_port_and_never_starts_audio() -> None:
    screen = _mirror()
    audio = _mirror()
    svc = _service(screen, audio, ent=_ready_entertainment())

    result = await svc.start(mode="screen")

    screen.set_output_port.assert_called()
    screen.start.assert_called_once()
    audio.start.assert_not_called()
    assert "status" in result
    assert "message" in result


@pytest.mark.asyncio
async def test_start_screen_prestarts_entertainment_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "marvin_hue.config.settings.entertainment_enabled",
        True,
    )
    screen = _mirror()
    screen.load_light_positions.return_value = [
        {"name": "Hue Play 1", "position": "left"}
    ]
    audio = _mirror()
    ent = _ready_entertainment()
    svc = _service(screen, audio, ent=ent, hue=MagicMock())

    await svc.start(
        mode="screen",
        area_id="area-1",
        transport_preference="auto",
    )

    ent.start_stream.assert_awaited()
    screen.set_output_port.assert_called()
    screen.start.assert_called_once()
    audio.start.assert_not_called()


@pytest.mark.asyncio
async def test_start_audio_never_starts_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "marvin_hue.config.settings.entertainment_enabled",
        True,
    )
    screen = _mirror()
    audio = _mirror()
    audio.load_light_positions.return_value = [
        {"name": "Hue Play 1", "position": "left"}
    ]
    ent = _ready_entertainment()
    svc = _service(screen, audio, ent=ent, hue=MagicMock())

    await svc.start(mode="audio", profile="party")

    audio.set_output_port.assert_called()
    audio.start.assert_called_once()
    screen.start.assert_not_called()
    ent.start_stream.assert_awaited()


@pytest.mark.asyncio
async def test_stop_uses_end_output_false_and_awaits_stop_stream() -> None:
    screen = _mirror(running=True)
    audio = _mirror(running=False)
    ent = MagicMock()
    ent.is_streaming = True
    ent.stop_stream = AsyncMock()
    history = MagicMock()
    history.snapshot = AsyncMock()
    svc = _service(screen, audio, ent=ent, hue=MagicMock(), history=history)

    result = await svc.stop()

    _assert_stop_never_ends_output(screen)
    _assert_stop_never_ends_output(audio)
    for called in screen.stop.call_args_list + audio.stop.call_args_list:
        assert called.kwargs.get("end_output") is not True
    ent.stop_stream.assert_awaited()
    history.snapshot.assert_awaited()
    assert "message" in result


@pytest.mark.asyncio
async def test_stop_never_calls_stop_with_end_output_true() -> None:
    screen = _mirror(running=True)
    audio = _mirror(running=True)
    ent = MagicMock()
    ent.is_streaming = True
    ent.stop_stream = AsyncMock()
    history = MagicMock()
    history.snapshot = AsyncMock()
    svc = _service(screen, audio, ent=ent, hue=MagicMock(), history=history)

    await svc.stop()

    for mirror in (screen, audio):
        _assert_stop_never_ends_output(mirror)
        for called in mirror.stop.call_args_list:
            positional_end = called.args[0] if called.args else None
            assert positional_end is not True
            assert called.kwargs.get("end_output") is False


@pytest.mark.asyncio
async def test_stop_awaits_stop_stream_when_client_exists_even_if_idle() -> None:
    screen = _mirror(running=True)
    audio = _mirror()
    ent = MagicMock()
    ent.is_streaming = False
    ent.stop_stream = AsyncMock()
    svc = _service(screen, audio, ent=ent, hue=MagicMock())

    await svc.stop()

    ent.stop_stream.assert_awaited()


@pytest.mark.asyncio
async def test_start_rejects_already_running_screen() -> None:
    from marvin_hue.services.mirror_control import MirrorAlreadyActiveError

    screen = _mirror(running=True)
    audio = _mirror()
    svc = _service(screen, audio)

    with pytest.raises(MirrorAlreadyActiveError):
        await svc.start(mode="screen")
    screen.start.assert_not_called()


@pytest.mark.asyncio
async def test_stop_rejects_when_idle() -> None:
    from marvin_hue.services.mirror_control import MirrorNotActiveError

    svc = _service(_mirror(), _mirror())
    with pytest.raises(MirrorNotActiveError):
        await svc.stop()


@pytest.mark.asyncio
async def test_apply_settings_updates_pending_transport_and_profile() -> None:
    screen = _mirror()
    audio = _mirror()
    svc = _service(screen, audio)

    result = await svc.apply_settings(
        mode="screen",
        profile="cinema",
        transport_preference="rest",
        entertainment_area_id="area-9",
    )

    screen.apply_profile.assert_called_once_with("cinema")
    assert svc.pending_transport_preference == "rest"
    assert svc.pending_area_id == "area-9"
    assert "status" in result


def test_unified_status_audio_mode_includes_spectrum() -> None:
    screen = _mirror()
    audio = _mirror(running=True)
    audio.get_status.return_value = {
        "running": True,
        "fps": 30,
        "bass": 0.8,
        "mid": 0.4,
        "treble": 0.2,
        "colors": {},
        "transport": "rest",
    }
    svc = _service(screen, audio)

    status = svc.unified_status()

    assert status["mode"] == "audio"
    assert status["bass"] == 0.8
    assert "spectrum" in status
    assert "entertainment_ready" in status


# --- last applied scene (issue #14) -------------------------------------


class _FakeLastApplied:
    def __init__(self) -> None:
        self.cleared: list[str] = []

    async def record(self, name: str, *, source: str) -> None:  # pragma: no cover
        raise AssertionError("mirror never records")

    async def clear(self, *, source: str) -> None:
        self.cleared.append(source)


def _service_with_last_applied(screen, audio, provider) -> MirrorControlService:
    return MirrorControlService(
        get_screen=lambda: screen,
        get_audio=lambda: audio,
        get_hue=MagicMock,
        get_manager=MagicMock,
        get_entertainment=lambda: None,
        get_last_applied=provider,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["screen", "audio"])
async def test_start_clears_last_applied_with_mirror_source(mode: str) -> None:
    last_applied = _FakeLastApplied()
    svc = _service_with_last_applied(_mirror(), _mirror(), lambda: last_applied)
    await svc.start(mode)
    assert last_applied.cleared == ["mirror"]


@pytest.mark.asyncio
async def test_failed_start_does_not_clear_last_applied() -> None:
    from marvin_hue.services.mirror_control import MirrorAlreadyActiveError

    last_applied = _FakeLastApplied()
    svc = _service_with_last_applied(
        _mirror(running=True), _mirror(), lambda: last_applied
    )
    with pytest.raises(MirrorAlreadyActiveError):
        await svc.start("screen")
    assert last_applied.cleared == []


@pytest.mark.asyncio
async def test_start_with_broken_last_applied_provider_still_starts() -> None:
    def broken():
        raise RuntimeError("not initialized")

    screen = _mirror()
    svc = _service_with_last_applied(screen, _mirror(), broken)
    result = await svc.start("screen")
    assert "iniciado" in result["message"]
    screen.start.assert_called_once()
