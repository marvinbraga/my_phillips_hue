"""Unit tests for RegisteredLight domain entity."""

from datetime import datetime, timezone

import pytest

from marvin_hue.domain.lights import (
    LightConflictError,
    LightNotFoundError,
    LightValidationError,
    RegisteredLight,
)


def test_registered_light_defaults():
    light = RegisteredLight(
        id="11111111-1111-1111-1111-111111111111",
        name="Lâmpada 1",
    )
    assert light.name == "Lâmpada 1"
    assert light.nickname is None
    assert light.room is None
    assert light.notes is None
    assert light.bridge_light_id is None
    assert light.eye_safety_limit_pct is None
    assert light.enabled_for_app is True
    assert light.deleted_at is None
    assert light.is_deleted is False


def test_registered_light_is_deleted_when_deleted_at_set():
    light = RegisteredLight(
        id="11111111-1111-1111-1111-111111111111",
        name="Fita Led",
        deleted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert light.is_deleted is True


def test_registered_light_rejects_empty_name():
    with pytest.raises(LightValidationError):
        RegisteredLight(id="x", name="  ")


def test_eye_safety_limit_range():
    with pytest.raises(LightValidationError):
        RegisteredLight(
            id="x",
            name="Fita Led",
            eye_safety_limit_pct=101,
        )
    with pytest.raises(LightValidationError):
        RegisteredLight(
            id="x",
            name="Fita Led",
            eye_safety_limit_pct=-1,
        )
    ok = RegisteredLight(id="x", name="Fita Led", eye_safety_limit_pct=25)
    assert ok.eye_safety_limit_pct == 25


def test_domain_errors_are_exceptions():
    assert issubclass(LightNotFoundError, Exception)
    assert issubclass(LightValidationError, Exception)
    assert issubclass(LightConflictError, LightValidationError)
