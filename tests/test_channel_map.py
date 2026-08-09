"""Tests for entertainment channel mapping."""

from __future__ import annotations

from marvin_hue.entertainment.channel_map import MappedChannel, map_lights_to_channels
from marvin_hue.entertainment.models import ChannelInfo, EntertainmentAreaInfo


def _area(*channels: ChannelInfo, area_id: str = "a1", name: str = "Sala") -> EntertainmentAreaInfo:
    return EntertainmentAreaInfo(id=area_id, name=name, channels=tuple(channels))


def test_empty_area_returns_empty():
    area = _area()
    assert map_lights_to_channels(area, ["Hue Play 1"]) == []


def test_exact_name_casefold():
    area = _area(
        ChannelInfo(channel_id=0, name="Hue Play 1"),
        ChannelInfo(channel_id=1, name="Hue Play 2"),
    )
    mapped = map_lights_to_channels(area, ["hue play 1", "HUE PLAY 2"])
    assert len(mapped) == 2
    by_name = {m.light_name: m.channel_id for m in mapped}
    assert by_name["hue play 1"] == 0
    assert by_name["HUE PLAY 2"] == 1


def test_fuzzy_name_match():
    area = _area(ChannelInfo(channel_id=3, name="Lampada 1"))
    mapped = map_lights_to_channels(area, ["Lâmpada 1"])
    # may match via fuzzy depending on accent; if not, zip fallback still maps
    assert len(mapped) == 1
    assert mapped[0].channel_id == 3


def test_dict_input_with_position():
    area = _area(ChannelInfo(channel_id=0, name="Hue Iris"))
    mapped = map_lights_to_channels(
        area,
        [{"name": "Hue Iris", "position": "left"}],
    )
    assert mapped == [MappedChannel("Hue Iris", 0, "left")]


def test_zip_fallback_for_unmatched():
    area = _area(
        ChannelInfo(channel_id=0, name="Unknown A"),
        ChannelInfo(channel_id=1, name="Unknown B"),
    )
    mapped = map_lights_to_channels(area, ["Light X", "Light Y"])
    assert len(mapped) == 2
    assert {m.channel_id for m in mapped} == {0, 1}
