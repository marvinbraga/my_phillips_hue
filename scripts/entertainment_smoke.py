#!/usr/bin/env python3
"""Smoke test live-oriented para Hue Entertainment (sem PAIR automático).

Exit codes:
  0 — pronto para stream (credenciais + áreas OK; stream opcional OK)
  2 — configuração incompleta (BRIDGE_IP / credenciais)
  3 — sem entertainment areas na bridge
  4 — falha ao iniciar/parar stream (SMOKE_STREAM=1)
  5 — bridge inacessível

Uso:
  uv run python scripts/entertainment_smoke.py
  SMOKE_STREAM=1 uv run python scripts/entertainment_smoke.py
"""
from __future__ import annotations

import asyncio
import os
import ssl
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Repo root on path for `marvin_hue` when run as script
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _ok(msg: str) -> None:
    print(f"PASS  {msg}")


def _fail(msg: str) -> None:
    print(f"FAIL  {msg}", file=sys.stderr)


def _info(msg: str) -> None:
    print(f"INFO  {msg}")


def _check_bridge_http(host: str, timeout: float = 3.0) -> bool:
    """GET https://{host}/api/config (self-signed cert)."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    url = f"https://{host}/api/config"
    req = Request(url, method="GET", headers={"Accept": "application/json"})
    try:
        with urlopen(req, timeout=timeout, context=ctx) as resp:  # noqa: S310
            code = getattr(resp, "status", None) or resp.getcode()
            return 200 <= int(code) < 500
    except HTTPError as e:
        # 401/403 still mean the bridge answered
        return e.code is not None and e.code < 500
    except (URLError, TimeoutError, OSError):
        return False


async def _list_areas(host: str, username: str, clientkey: str) -> list[Any]:
    from marvin_hue.entertainment.client import EntertainmentClient
    from marvin_hue.entertainment.credentials import EntertainmentCredentials

    client = EntertainmentClient(
        host=host,
        credentials=EntertainmentCredentials(username=username, clientkey=clientkey),
    )
    try:
        return await client.list_areas()
    finally:
        if client._session is not None:
            await client.stop_stream()


async def _smoke_stream(host: str, username: str, clientkey: str, area_id: str) -> None:
    """Flash white ~2s then stop (same idea as entertainment_poc)."""
    from marvin_hue.entertainment.client import EntertainmentClient
    from marvin_hue.entertainment.credentials import EntertainmentCredentials
    from marvin_hue.entertainment.models import ChannelColor

    client = EntertainmentClient(
        host=host,
        credentials=EntertainmentCredentials(username=username, clientkey=clientkey),
    )
    areas = await client.list_areas()
    area = next((a for a in areas if a.id == area_id), areas[0] if areas else None)
    if area is None:
        raise RuntimeError("área sumiu entre list e stream")
    await client.start_stream(area.id)
    try:
        n_frames = 80  # ~2s @ 40 FPS
        for _ in range(n_frames):
            client.send_frame(
                [ChannelColor(channel_id=ch.channel_id, r=255, g=255, b=255) for ch in area.channels]
            )
            await asyncio.sleep(1 / 40)
    finally:
        await client.stop_stream()


async def main() -> int:
    print("=== Hue Entertainment smoke ===")

    # Lazy settings so missing BRIDGE_IP can be reported as FAIL step 1
    try:
        from marvin_hue.config import settings
    except Exception as e:  # noqa: BLE001 — smoke must not stack-trace on config
        _fail(f"Não foi possível carregar settings: {e}")
        _info("Defina BRIDGE_IP no .env (copie de .env.example).")
        return 2

    host = (settings.bridge_ip or "").strip()
    if not host:
        _fail("BRIDGE_IP ausente")
        _info("Defina BRIDGE_IP no .env ou no ambiente.")
        return 2
    _ok(f"BRIDGE_IP presente ({host})")

    if not _check_bridge_http(host, timeout=float(min(settings.bridge_timeout, 5))):
        _fail(f"Bridge HTTP inacessível em https://{host}/api/config")
        _info("Confira IP, rede local e se a bridge está ligada.")
        return 5
    _ok("Bridge HTTP alcançável")

    from marvin_hue.entertainment.credentials import load_entertainment_credentials

    creds = load_entertainment_credentials(
        settings.entertainment_creds_file,
        settings.hue_app_key,
        settings.hue_client_key,
    )
    if creds is None:
        _fail("Credenciais Entertainment ausentes (arquivo ou env)")
        creds_path = settings.entertainment_creds_file
        print(
            "\nPróximos passos para emparelhar (pressione o botão da bridge primeiro):\n"
            f"  1) PAIR=1 BRIDGE_IP={host} uv run python scripts/entertainment_poc.py\n"
            "     (salva em .res/hue_entertainment_creds.json)\n"
            "  2) Ou: POST /mirror/entertainment/pair com a API no ar\n"
            "  3) Defina ENTERTAINMENT_ENABLED=true no .env e reinicie o servidor\n"
            f"  Arquivo esperado: {creds_path}\n"
            "  Env alternativas: HUE_APP_KEY + HUE_CLIENT_KEY\n",
            file=sys.stderr,
        )
        return 2
    suffix = creds.username[-4:] if len(creds.username) >= 4 else "****"
    _ok(f"Credenciais carregadas (username …{suffix})")

    try:
        areas = await _list_areas(host, creds.username, creds.clientkey)
    except Exception as e:  # noqa: BLE001
        _fail(f"Falha ao listar entertainment areas: {e}")
        return 5

    if not areas:
        _fail("Nenhuma entertainment area na bridge")
        _info(
            "Abra o app oficial Hue → Configurações → Entertainment areas "
            "e crie uma área com as lâmpadas desejadas."
        )
        return 3

    for a in areas:
        n_ch = len(a.channels)
        _ok(f"Área: {a.name!r} id={a.id} canais={n_ch}")

    preferred = (settings.entertainment_area_id or "").strip()
    if preferred:
        if any(a.id == preferred for a in areas):
            _ok(f"ENTERTAINMENT_AREA_ID confere ({preferred})")
        else:
            _info(
                f"ENTERTAINMENT_AREA_ID={preferred} não está na lista; "
                f"a app usará a primeira área se omitido."
            )

    do_stream = os.environ.get("SMOKE_STREAM", "").strip() == "1"
    if not do_stream:
        _info("SMOKE_STREAM não é 1 — pulando flash de stream (OK para readiness)")
        if settings.entertainment_enabled:
            _ok("ENTERTAINMENT_ENABLED=true — pronto para usar no app")
        else:
            _info(
                "ENTERTAINMENT_ENABLED=false — defina true no .env para ativar "
                "transporte entertainment no espelhamento"
            )
        print("=== smoke OK (ready for stream) ===")
        return 0

    area_id = preferred or areas[0].id
    _info(f"SMOKE_STREAM=1 — flash branco ~2s na área {area_id}")
    try:
        await _smoke_stream(host, creds.username, creds.clientkey, area_id)
    except Exception as e:  # noqa: BLE001
        _fail(f"Stream falhou: {e}")
        return 4
    _ok("Stream start/send/stop OK")
    print("=== smoke OK (stream verified) ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
