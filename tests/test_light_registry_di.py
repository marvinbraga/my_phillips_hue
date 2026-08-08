"""Dependency injection smoke for light registry service."""

import pytest
from marvin_hue.api import dependencies
from marvin_hue.services.light_registry import LightRegistryService


def test_get_light_registry_service_raises_if_unset():
    original = getattr(dependencies, "_light_registry_service", None)
    dependencies._light_registry_service = None
    try:
        with pytest.raises(RuntimeError):
            dependencies.get_light_registry_service()
    finally:
        dependencies._light_registry_service = original


@pytest.mark.asyncio
async def test_set_and_get_light_registry_service(tmp_path):
    from marvin_hue.persistence.schema import init_db
    from marvin_hue.persistence.light_repository import SqliteLightRegistryRepository

    path = str(tmp_path / "di.sqlite")
    await init_db(path)
    repo = await SqliteLightRegistryRepository.open(path)
    svc = LightRegistryService(repo)
    dependencies.set_light_registry_service(svc)
    try:
        got = dependencies.get_light_registry_service()
        assert got is svc
    finally:
        dependencies.set_light_registry_service(None)
        await repo.close()
