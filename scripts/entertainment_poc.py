"""One-shot PoC: pair (optional) and flash white on all channels ~2.5s.

Usage:
  HUE_HOST=192.168.x.x HUE_APP_KEY=... HUE_CLIENT_KEY=... uv run python scripts/entertainment_poc.py
  # First time: press bridge button, set PAIR=1
  PAIR=1 HUE_HOST=... uv run python scripts/entertainment_poc.py
"""
from __future__ import annotations

import asyncio
import os
import sys


async def main() -> int:
    host = os.environ.get("HUE_HOST") or os.environ.get("BRIDGE_IP")
    if not host:
        print("Set HUE_HOST or BRIDGE_IP", file=sys.stderr)
        return 2

    from hue_entertainment import EntertainmentSession, HueEntertainmentAPI, LightColorCommand

    app_key = os.environ.get("HUE_APP_KEY")
    client_key = os.environ.get("HUE_CLIENT_KEY")

    if os.environ.get("PAIR") == "1":
        api = HueEntertainmentAPI(host)
        creds = await api.pair()
        await api.close()
        print("PAIR_OK", {"username_suffix": creds["username"][-4:], "has_clientkey": bool(creds.get("clientkey"))})
        app_key = creds["username"]
        client_key = creds["clientkey"]

    if not app_key or not client_key:
        print("Need HUE_APP_KEY + HUE_CLIENT_KEY or PAIR=1", file=sys.stderr)
        return 2

    session = EntertainmentSession(host, app_key, client_key)
    areas = await session.get_entertainment_areas()
    if not areas:
        print("No entertainment areas — create one in the Hue app", file=sys.stderr)
        await session.aclose()
        return 3
    area = areas[0]
    print("AREA", area.id, getattr(area, "name", ""), "channels", len(area.channels))
    await session.start(area.id)
    try:
        for _ in range(100):
            session.send(
                [
                    LightColorCommand(
                        channel_id=ch.channel_id,
                        red=40000,
                        green=40000,
                        blue=40000,
                    )
                    for ch in area.channels
                ]
            )
            await asyncio.sleep(1 / 40)
    finally:
        await session.aclose()
    print("DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
