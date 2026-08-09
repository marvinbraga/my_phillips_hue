"""Unit tests for entertainment credentials load/save."""

from __future__ import annotations

import json
import stat

from marvin_hue.entertainment.credentials import (
    load_entertainment_credentials,
    save_entertainment_credentials,
)


def test_load_prefers_env_over_file(tmp_path, monkeypatch):
    path = tmp_path / "creds.json"
    path.write_text(
        json.dumps({"username": "file-user", "clientkey": "file-key"}),
        encoding="utf-8",
    )
    creds = load_entertainment_credentials(
        creds_file=str(path),
        env_app_key="env-user",
        env_client_key="env-key",
    )
    assert creds is not None
    assert creds.username == "env-user"
    assert creds.clientkey == "env-key"


def test_load_from_file_when_env_missing(tmp_path):
    path = tmp_path / "creds.json"
    path.write_text(
        json.dumps({"username": "u", "clientkey": "k"}),
        encoding="utf-8",
    )
    creds = load_entertainment_credentials(
        creds_file=str(path),
        env_app_key=None,
        env_client_key=None,
    )
    assert creds is not None
    assert creds.username == "u"
    assert creds.clientkey == "k"


def test_load_returns_none_when_incomplete(tmp_path):
    path = tmp_path / "creds.json"
    path.write_text("{}", encoding="utf-8")
    assert load_entertainment_credentials(str(path), None, None) is None


def test_load_accepts_app_key_aliases(tmp_path):
    path = tmp_path / "creds.json"
    path.write_text(
        json.dumps({"app_key": "a", "client_key": "b"}),
        encoding="utf-8",
    )
    creds = load_entertainment_credentials(str(path), None, None)
    assert creds is not None
    assert creds.username == "a"
    assert creds.clientkey == "b"


def test_save_roundtrip(tmp_path):
    path = tmp_path / "creds.json"
    save_entertainment_credentials(str(path), username="u", clientkey="k")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["username"] == "u"
    assert data["clientkey"] == "k"
    mode = path.stat().st_mode
    # not group/world readable if chmod applied
    assert mode & (stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH) == 0
