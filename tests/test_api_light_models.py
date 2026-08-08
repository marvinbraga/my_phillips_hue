"""Validation tests for lights registry API models."""

import pytest
from pydantic import ValidationError

from marvin_hue.api.models import (
    LightCreateRequest,
    LightResponse,
    LightUpdateRequest,
    LightsSyncResponse,
)


def test_create_request_requires_name():
    with pytest.raises(ValidationError):
        LightCreateRequest()


def test_create_request_ok():
    m = LightCreateRequest(name="Lâmpada 1", nickname="Mesa", room="Escritório")
    assert m.name == "Lâmpada 1"
    assert m.enabled_for_app is True


def test_create_request_strips_name():
    m = LightCreateRequest(name="  Hue Iris  ")
    assert m.name == "Hue Iris"


def test_create_request_rejects_blank_name():
    with pytest.raises(ValidationError):
        LightCreateRequest(name="   ")


def test_create_request_eye_safety_bounds():
    with pytest.raises(ValidationError):
        LightCreateRequest(name="x", eye_safety_limit_pct=-1)
    with pytest.raises(ValidationError):
        LightCreateRequest(name="x", eye_safety_limit_pct=101)
    m = LightCreateRequest(name="x", eye_safety_limit_pct=0)
    assert m.eye_safety_limit_pct == 0
    m = LightCreateRequest(name="x", eye_safety_limit_pct=100)
    assert m.eye_safety_limit_pct == 100


def test_update_request_all_optional():
    m = LightUpdateRequest(nickname="X")
    assert m.nickname == "X"
    assert m.name is None
    # exclude_unset distinguishes missing vs null
    assert "nickname" in m.model_dump(exclude_unset=True)
    assert "name" not in m.model_dump(exclude_unset=True)


def test_update_request_explicit_null_is_set():
    m = LightUpdateRequest.model_validate({"nickname": None})
    dumped = m.model_dump(exclude_unset=True)
    assert "nickname" in dumped
    assert dumped["nickname"] is None


def test_update_request_rejects_blank_name():
    with pytest.raises(ValidationError):
        LightUpdateRequest(name="   ")


def test_light_response_from_fields():
    m = LightResponse(
        id="11111111-1111-1111-1111-111111111111",
        name="Hue Iris",
        nickname=None,
        room=None,
        notes=None,
        bridge_light_id="2",
        eye_safety_limit_pct=None,
        enabled_for_app=True,
        deleted_at=None,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    assert m.bridge_light_id == "2"


def test_sync_response():
    m = LightsSyncResponse(
        created=1, updated=0, unchanged=2, skipped_deleted=0, total_bridge=3
    )
    assert m.total_bridge == 3
