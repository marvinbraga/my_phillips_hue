"""LightRegistryService.refresh_runtime_policy pushes eye_safety cache."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from marvin_hue import eye_safety as es
from marvin_hue.domain.lights import RegisteredLight
from marvin_hue.services.light_registry import LightRegistryService


@pytest.fixture(autouse=True)
def _clear_policy():
    es.clear_runtime_policy()
    yield
    es.clear_runtime_policy()


@pytest.mark.asyncio
async def test_refresh_runtime_policy_from_registry() -> None:
    now = datetime.now(timezone.utc)
    lights = [
        RegisteredLight(
            id="1",
            name="Fita Led",
            eye_safety_limit_pct=15,
            enabled_for_app=True,
            created_at=now,
            updated_at=now,
        ),
        RegisteredLight(
            id="2",
            name="Hue Play 1",
            eye_safety_limit_pct=None,
            enabled_for_app=False,
            created_at=now,
            updated_at=now,
        ),
    ]
    repo = AsyncMock()
    repo.list_all = AsyncMock(return_value=lights)
    svc = LightRegistryService(repo)
    await svc.refresh_runtime_policy()
    assert es.eye_safety_limit_pct("Fita Led") == 15
    assert es.is_enabled_for_app("Hue Play 1") is False
    assert es.is_enabled_for_app("Fita Led") is True
