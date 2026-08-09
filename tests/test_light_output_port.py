"""Tests for LightOutputPort adapters (mocked, no bridge)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from marvin_hue.entertainment.channel_map import MappedChannel
from marvin_hue.entertainment.client import EntertainmentClient
from marvin_hue.entertainment.credentials import EntertainmentCredentials
from marvin_hue.entertainment.models import ChannelColor
from marvin_hue.eye_safety import clear_runtime_policy, set_runtime_policy
from marvin_hue.output.entertainment_adapter import EntertainmentStreamAdapter
from marvin_hue.output.fallback import FallbackOutputPort
from marvin_hue.output.port import LightFrameColor, LightOutputPort
from marvin_hue.output.rest_adapter import RestPhueAdapter


class FakePort:
    def __init__(self, name: str = "rest") -> None:
        self._name = name
        self.frames: list[list[LightFrameColor]] = []
        self.begun = 0
        self.ended = 0

    @property
    def transport(self):
        return self._name  # type: ignore[return-value]

    def begin_session(self) -> None:
        self.begun += 1

    def apply_frame(self, colors: list[LightFrameColor]) -> None:
        self.frames.append(list(colors))

    def end_session(self) -> None:
        self.ended += 1


def test_protocol_isinstance():
    fake = FakePort()
    assert isinstance(fake, LightOutputPort)


def test_rest_adapter_skips_disabled():
    clear_runtime_policy()
    set_runtime_policy(limits_pct={}, disabled_names={"Off Light"})
    hue = MagicMock()
    adapter = RestPhueAdapter(hue, transition_time=2)
    assert adapter.transport == "rest"
    adapter.begin_session()
    adapter.apply_frame(
        [
            LightFrameColor("Off Light", 255, 0, 0, 200),
            LightFrameColor("On Light", 0, 255, 0, 100),
        ]
    )
    hue.set_light_color.assert_called_once()
    args = hue.set_light_color.call_args[0]
    assert args[0] == "On Light"
    adapter.end_session()
    clear_runtime_policy()


def test_entertainment_adapter_maps_and_sends():
    clear_runtime_policy()
    # No spec=EntertainmentClient: Mock(spec=async class) auto-wraps start_stream /
    # stop_stream as AsyncMock and begin_session would leave those coros un-awaited
    # when run_coro is a plain MagicMock.
    client = MagicMock()
    client.is_streaming = False
    client.active_area = None
    client.start_stream = MagicMock(return_value="start-marker")
    client.stop_stream = MagicMock(return_value="stop-marker")

    def run_coro(coro, timeout=15.0):  # noqa: ARG001
        # Adapter passes the return value of start_stream/stop_stream (sync mocks).
        return None

    client.run_coro = MagicMock(side_effect=run_coro)
    client.send_frame = MagicMock()

    adapter = EntertainmentStreamAdapter(
        client=client,
        area_id="area-1",
        channels=[MappedChannel("Hue Play 1", 0), MappedChannel("Hue Play 2", 1)],
    )
    assert adapter.transport == "entertainment"
    adapter.begin_session()
    client.run_coro.assert_called()
    # simulate streaming after begin
    client.is_streaming = True
    adapter.apply_frame(
        [
            LightFrameColor("Hue Play 1", 255, 0, 0, 254),
            LightFrameColor("Hue Play 2", 0, 0, 255, 127),
            LightFrameColor("Unknown", 1, 1, 1, 100),
        ]
    )
    client.send_frame.assert_called_once()
    cmds: list[ChannelColor] = client.send_frame.call_args[0][0]
    assert len(cmds) == 2
    assert cmds[0].channel_id == 0
    assert cmds[1].channel_id == 1
    # bri 127 scales blue channel: 255 * 127 // 254
    assert cmds[1].b == 255 * 127 // 254
    adapter.end_session()
    assert client.run_coro.call_count >= 2  # begin + end
    clear_runtime_policy()


def test_fallback_degrades_on_begin_failure():
    primary = FakePort("entertainment")
    secondary = FakePort("rest")

    def boom() -> None:
        raise RuntimeError("dtls fail")

    primary.begin_session = boom  # type: ignore[method-assign]
    fb = FallbackOutputPort(primary, secondary)
    fb.begin_session()
    assert fb.transport == "rest"
    assert fb.degraded is True
    fb.apply_frame([LightFrameColor("L", 1, 2, 3, 10)])
    assert len(secondary.frames) == 1
    fb.end_session()
    assert secondary.ended == 1


def test_fallback_degrades_on_apply_failure():
    primary = FakePort("entertainment")
    secondary = FakePort("rest")
    calls = {"n": 0}

    def fail_once(colors):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("send fail")
        primary.frames.append(list(colors))

    primary.apply_frame = fail_once  # type: ignore[method-assign]
    fb = FallbackOutputPort(primary, secondary)
    fb.begin_session()
    fb.apply_frame([LightFrameColor("L", 1, 2, 3, 10)])
    assert fb.transport == "rest"
    assert len(secondary.frames) == 1


@pytest.mark.asyncio
async def test_entertainment_client_list_areas_maps_models():
    creds = EntertainmentCredentials(username="u", clientkey="k")
    client = EntertainmentClient(host="10.0.0.1", credentials=creds)

    fake_ch = MagicMock(channel_id=0, name="Play 1", service_id="svc", position=(0.0, 0.0, 0.0))
    fake_area = MagicMock(id="area-1", name="Sala", channels=[fake_ch])

    class _FakeSession:
        async def get_entertainment_areas(self) -> list:
            return [fake_area]

    async def ensure() -> _FakeSession:
        return _FakeSession()

    with patch.object(client, "_ensure_session", new=ensure):
        areas = await client.list_areas()
    assert len(areas) == 1
    assert areas[0].id == "area-1"
    assert areas[0].channels[0].channel_id == 0


@pytest.mark.asyncio
async def test_entertainment_client_start_send_stop():
    creds = EntertainmentCredentials(username="u", clientkey="k")
    client = EntertainmentClient(host="10.0.0.1", credentials=creds)

    # Real async defs (no AsyncMock) avoid "coroutine never awaited" from mock
    # machinery / library import side-effects under pytest.
    calls: dict[str, list] = {"start": [], "send": [], "stop": [], "aclose": []}

    class _FakeSession:
        is_streaming = False

        async def start(self, area_id: str) -> None:
            calls["start"].append(area_id)
            self.is_streaming = True

        def send(self, cmds: list) -> None:
            calls["send"].append(cmds)

        async def stop(self) -> None:
            calls["stop"].append(True)
            self.is_streaming = False

        async def aclose(self) -> None:
            calls["aclose"].append(True)

    fake_session = _FakeSession()

    async def ensure() -> _FakeSession:
        return fake_session

    # Replace with a real coroutine function — do not wrap in MagicMock/AsyncMock
    # (those leave un-awaited coroutines during hue_entertainment / aiohttp import).
    with patch.object(client, "_ensure_session", new=ensure):
        await client.start_stream("area-1")
        assert client.is_streaming is True
        client.send_frame([ChannelColor(0, 255, 0, 0)])
        await client.stop_stream()

    assert calls["start"] == ["area-1"]
    assert len(calls["send"]) == 1
    assert calls["stop"] == [True]
    assert calls["aclose"] == [True]
    assert client.is_streaming is False
    assert client._session is None
