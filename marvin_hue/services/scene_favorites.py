"""Scene favorites use cases: marcar/desmarcar cenas e listar as que existem."""

from __future__ import annotations

from collections.abc import Callable

from marvin_hue.logging_config import get_logger
from marvin_hue.persistence.favorites_repository import SceneFavoritesRepository
from marvin_hue.services.apply_config import LightConfigLookup

logger = get_logger("services.scene_favorites")


class FavoriteConfigNotFoundError(LookupError):
    """A cena pedida não existe no LightSetupsManager atual."""


class SceneFavoritesService:
    """Favoritos de cena guardados no SQLite do app.

    ``manager_lookup`` é chamado a cada operação (nunca capturado), para
    acompanhar recargas/trocas do manager (ex.: import de backup).
    """

    def __init__(
        self,
        repo: SceneFavoritesRepository,
        manager_lookup: Callable[[], LightConfigLookup],
    ) -> None:
        self._repo = repo
        self._manager_lookup = manager_lookup

    @property
    def repository(self) -> SceneFavoritesRepository:
        return self._repo

    async def aclose(self) -> None:
        await self._repo.close()

    async def list_existing(self) -> list[str]:
        """Nomes favoritos que existem no manager agora (D4: órfãos ocultos)."""
        manager = self._manager_lookup()
        names = await self._repo.list_names()
        return sorted(name for name in names if manager.get_config(name) is not None)

    async def add(self, name: str) -> None:
        """Marca a cena como favorita (idempotente).

        Raises:
            FavoriteConfigNotFoundError: a cena não existe no manager.
        """
        if self._manager_lookup().get_config(name) is None:
            raise FavoriteConfigNotFoundError(f"Configuração '{name}' não encontrada")
        await self._repo.add(name)
        logger.info("scene_favorite_added name={!r}", name)

    async def remove(self, name: str) -> None:
        """Desmarca a cena (idempotente; não exige que a cena exista)."""
        await self._repo.remove(name)
        logger.info("scene_favorite_removed name={!r}", name)
