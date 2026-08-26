"""LightRegistryService.refresh_runtime_policy pushes eye_safety cache."""

from datetime import UTC, datetime
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
    now = datetime.now(UTC)
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


def _light(
    light_id: str,
    name: str,
    pct: int | None,
    *,
    enabled: bool = True,
) -> RegisteredLight:
    now = datetime.now(UTC)
    return RegisteredLight(
        id=light_id,
        name=name,
        eye_safety_limit_pct=pct,
        enabled_for_app=enabled,
        created_at=now,
        updated_at=now,
    )


class _MemoryLightRepo:
    def __init__(self, lights: list[RegisteredLight]) -> None:
        self.items = {light.id: light for light in lights}
        self.updated_ids: list[str] = []

    async def list_all(self, *, include_deleted: bool = False) -> list[RegisteredLight]:
        return list(self.items.values())

    async def update(self, light: RegisteredLight) -> RegisteredLight:
        self.updated_ids.append(light.id)
        self.items[light.id] = light
        return light

    async def get_by_id(
        self, light_id: str, *, include_deleted: bool = False
    ) -> RegisteredLight:
        return self.items[light_id]


@pytest.mark.asyncio
async def test_refresh_seeds_null_eye_safety_for_named_lights() -> None:
    repo = _MemoryLightRepo(
        [
            _light("1", "Fita Led", None),
            _light("2", "Led cima", None),
            _light("3", "Lâmpada 1", None),
        ]
    )
    svc = LightRegistryService(repo)
    await svc.refresh_runtime_policy()

    fita = await repo.get_by_id("1")
    cima = await repo.get_by_id("2")
    lamp = await repo.get_by_id("3")
    assert fita.eye_safety_limit_pct == 25
    assert cima.eye_safety_limit_pct == 25
    assert lamp.eye_safety_limit_pct is None
    assert set(repo.updated_ids) == {"1", "2"}

    assert es.eye_safety_limit_pct("Fita Led") == 25
    assert es.eye_safety_limit_pct("Led cima") == 25
    assert es.eye_safety_limit_pct("Lâmpada 1") is None
    assert es.EYE_SAFETY_LIMITS == {"Fita Led": 25, "Led cima": 25}


@pytest.mark.asyncio
async def test_refresh_does_not_overwrite_existing_eye_safety_pct() -> None:
    repo = _MemoryLightRepo(
        [
            _light("1", "Fita Led", 40),
            _light("2", "Led cima", None),
        ]
    )
    svc = LightRegistryService(repo)
    await svc.refresh_runtime_policy()

    fita = await repo.get_by_id("1")
    cima = await repo.get_by_id("2")
    assert fita.eye_safety_limit_pct == 40
    assert cima.eye_safety_limit_pct == 25
    assert repo.updated_ids == ["2"]
    assert es.eye_safety_limit_pct("Fita Led") == 40
    assert es.eye_safety_limit_pct("Led cima") == 25
