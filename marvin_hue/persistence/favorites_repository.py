"""Scene favorites repository: Protocol + aiosqlite adapter.

Guarda apenas o nome da cena (join key de ``.res/setups.json``). Não valida
se a cena existe: isso é responsabilidade do serviço (D4 mantém órfãos).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Optional, Protocol, runtime_checkable

import aiosqlite


_INSERT_OR_IGNORE = (
    "INSERT OR IGNORE INTO scene_favorites (config_name, created_at) VALUES (?, ?)"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@runtime_checkable
class SceneFavoritesRepository(Protocol):
    async def list_names(self) -> list[str]: ...

    async def add(self, name: str) -> None: ...

    async def remove(self, name: str) -> None: ...

    async def add_many(self, names: Iterable[str]) -> None: ...

    async def replace_all(self, names: Iterable[str]) -> None: ...

    async def close(self) -> None: ...


class SqliteSceneFavoritesRepository:
    """aiosqlite-backed scene favorites repository.

    One shared connection per instance, serialized with asyncio.Lock for
    safe concurrent use under FastAPI.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    @classmethod
    async def open(cls, db_path: str) -> "SqliteSceneFavoritesRepository":
        repo = cls(db_path)
        await repo._get_conn()
        return repo

    async def _get_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            self._conn = await aiosqlite.connect(self._db_path)
            self._conn.row_factory = aiosqlite.Row
        return self._conn

    async def close(self) -> None:
        async with self._lock:
            if self._conn is not None:
                await self._conn.close()
                self._conn = None

    async def list_names(self) -> list[str]:
        """Todos os nomes guardados (inclusive órfãos), em ordem de nome."""
        async with self._lock:
            conn = await self._get_conn()
            async with conn.execute(
                "SELECT config_name FROM scene_favorites ORDER BY config_name"
            ) as cur:
                rows = await cur.fetchall()
            return [str(r["config_name"]) for r in rows]

    async def add(self, name: str) -> None:
        """Marca como favorita; idempotente (mantém o ``created_at`` original)."""
        async with self._lock:
            conn = await self._get_conn()
            await conn.execute(_INSERT_OR_IGNORE, (name, _now_iso()))
            await conn.commit()

    async def remove(self, name: str) -> None:
        """Desmarca; idempotente (nome ausente não é erro)."""
        async with self._lock:
            conn = await self._get_conn()
            await conn.execute(
                "DELETE FROM scene_favorites WHERE config_name = ?",
                (name,),
            )
            await conn.commit()

    async def add_many(self, names: Iterable[str]) -> None:
        """Marca vários de uma vez (uma transação, um commit; idempotente).

        Nomes já favoritos mantêm o ``created_at`` original. Em erro, nada
        é gravado (rollback).
        """
        async with self._lock:
            conn = await self._get_conn()
            now = _now_iso()
            try:
                await conn.executemany(
                    _INSERT_OR_IGNORE, ((name, now) for name in names)
                )
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

    async def replace_all(self, names: Iterable[str]) -> None:
        """Substitui o conjunto inteiro numa única transação.

        Não normaliza nomes (é responsabilidade do chamador); duplicatas são
        ignoradas pelo ``INSERT OR IGNORE``.
        """
        async with self._lock:
            conn = await self._get_conn()
            now = _now_iso()
            try:
                await conn.execute("DELETE FROM scene_favorites")
                await conn.executemany(
                    _INSERT_OR_IGNORE, ((name, now) for name in names)
                )
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise
