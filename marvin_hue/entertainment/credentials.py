"""Load/save Hue Entertainment credentials (app key + DTLS clientkey).

Never store these in chat SQLite or free-form app catalog rows.
Env vars (HUE_APP_KEY / HUE_CLIENT_KEY) override the JSON file.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from marvin_hue.logging_config import get_logger

logger = get_logger("entertainment.credentials")


@dataclass(frozen=True, slots=True)
class EntertainmentCredentials:
    """Pairing material for CLIP + DTLS Entertainment stream."""

    username: str  # app key
    clientkey: str  # DTLS PSK material as hex string from bridge


def load_entertainment_credentials(
    creds_file: str,
    env_app_key: str | None,
    env_client_key: str | None,
) -> EntertainmentCredentials | None:
    """Merge env over file. Returns None if incomplete."""
    username = (env_app_key or "").strip() or None
    clientkey = (env_client_key or "").strip() or None

    if username is None or clientkey is None:
        path = Path(creds_file)
        if path.is_file():
            try:
                data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"Could not read entertainment creds file {path}: {e}")
                data = {}
            username = username or (
                str(data.get("username") or data.get("app_key") or "").strip() or None
            )
            clientkey = clientkey or (
                str(data.get("clientkey") or data.get("client_key") or "").strip()
                or None
            )

    if not username or not clientkey:
        return None
    return EntertainmentCredentials(username=username, clientkey=clientkey)


def save_entertainment_credentials(
    creds_file: str,
    *,
    username: str,
    clientkey: str,
) -> None:
    """Write credentials JSON with restrictive permissions when possible."""
    path = Path(creds_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"username": username, "clientkey": clientkey}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        logger.debug("chmod 600 not applied on credentials file")
