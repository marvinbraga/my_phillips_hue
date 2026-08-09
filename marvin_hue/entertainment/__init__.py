"""Hue Entertainment (DTLS / HueStream) integration package."""

from marvin_hue.entertainment.credentials import (
    EntertainmentCredentials,
    load_entertainment_credentials,
    save_entertainment_credentials,
)

__all__ = [
    "EntertainmentCredentials",
    "load_entertainment_credentials",
    "save_entertainment_credentials",
]
