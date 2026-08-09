"""Build LightOutputPort for audio/screen mirror based on settings + client."""

from __future__ import annotations

from marvin_hue.controllers import HueController
from marvin_hue.entertainment.channel_map import MappedChannel
from marvin_hue.entertainment.client import EntertainmentClient
from marvin_hue.logging_config import get_logger
from marvin_hue.output.entertainment_adapter import EntertainmentStreamAdapter
from marvin_hue.output.fallback import FallbackOutputPort
from marvin_hue.output.port import LightOutputPort
from marvin_hue.output.rest_adapter import RestPhueAdapter

logger = get_logger("output.factory")


def build_audio_output_port(
    hue: HueController,
    *,
    entertainment_enabled: bool,
    client: EntertainmentClient | None,
    area_id: str | None,
    mapped_channels: list[MappedChannel] | None,
    transition_time: int = 0,
    transport_preference: str = "auto",
) -> LightOutputPort:
    """
    Build output port for audio mirror.

    transport_preference:
      - auto: entertainment when enabled+ready, else REST
      - rest: force REST
      - entertainment: require entertainment or raise ValueError
    """
    rest = RestPhueAdapter(hue, transition_time=transition_time)
    pref = (transport_preference or "auto").strip().lower()

    if pref == "rest":
        return rest

    can_ent = (
        entertainment_enabled
        and client is not None
        and client.is_ready
        and bool(area_id)
        and bool(mapped_channels)
    )

    if pref == "entertainment" and not can_ent:
        raise ValueError(
            "Transporte entertainment indisponível: habilite ENTERTAINMENT_ENABLED, "
            "faça o pair (botão da bridge) e selecione uma área com canais mapeados."
        )

    if can_ent and pref in {"auto", "entertainment"}:
        assert client is not None
        assert area_id is not None
        assert mapped_channels is not None
        ent = EntertainmentStreamAdapter(
            client=client,
            area_id=area_id,
            channels=mapped_channels,
        )
        logger.info(
            f"Building FallbackOutputPort entertainment area={area_id} "
            f"channels={len(mapped_channels)}"
        )
        return FallbackOutputPort(ent, rest)

    return rest


def build_mirror_output_port(
    hue: HueController,
    *,
    entertainment_enabled: bool,
    client: EntertainmentClient | None,
    area_id: str | None,
    mapped_channels: list[MappedChannel] | None,
    transition_time: int = 0,
    transport_preference: str = "auto",
) -> LightOutputPort:
    """Alias for screen/audio — same dual-transport rules."""
    return build_audio_output_port(
        hue,
        entertainment_enabled=entertainment_enabled,
        client=client,
        area_id=area_id,
        mapped_channels=mapped_channels,
        transition_time=transition_time,
        transport_preference=transport_preference,
    )
