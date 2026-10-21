"""Last applied scene repository: Protocol + aiosqlite adapter.

Single-row table (``id = 1``, migration v6). Stores the scene name as given;
whether the scene still exists is the service's concern.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional, Protocol, runtime_checkable

import aiosqlite

from marvin_hue.domain.last_applied_scene import LastAppliedScene

_UPSERT = (
    "INSERT INTO last_applied_scene (id, config_name, source, applied_at) "
    "VALUES (1, ?, ?, ?) "
    "ON CONFLICT(id) DO UPDATE SET "
    "config_name = excluded.config_name, "
    "source = excluded.source, "
    "applied_at = excluded.applied_at"
)


@runtime_checkable
class LastAppliedSceneRepository(Protocol):
    async def get(self) -> LastAppliedScene | None: ...

    async def record(self, config_name: str, source: str) -> LastAppliedScene: ...

    async def clear(self, source: str) -> None: ...

    async def close(self) -> None: ...


class SqliteLastAppliedSceneRepository:
    """aiosqlite-backed single-row store.

    One shared connection per instance, serialized with asyncio.Lock for
    safe concurrent use under FastAPI.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    @classmethod
    async def open(cls, db_path: str) -> "SqliteLastAppliedSceneRepository":
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

    async def get(self) -> LastAppliedScene | None:
        """The row (possibly cleared), or None if nothing was ever recorded."""
        async with self._lock:
            conn = await self._get_conn()
            async with conn.execute(
                "SELECT config_name, source, applied_at "
                "FROM last_applied_scene WHERE id = 1"
            ) as cur:
                row = await cur.fetchone()
        if row is None:
            return None
        name = row["config_name"]
        return LastAppliedScene(
            config_name=None if name is None else str(name),
            source=str(row["source"]),
            applied_at=datetime.fromisoformat(str(row["applied_at"])),
        )

    async def record(self, config_name: str, source: str) -> LastAppliedScene:
        """Replace the row with this scene (UTC timestamp)."""
        scene = LastAppliedScene(
            config_name=config_name,
            source=source,
            applied_at=datetime.now(timezone.utc),
        )
        await self._upsert(scene)
        return scene

    async def clear(self, source: str) -> None:
        """Keep the row but forget the scene (``config_name`` NULL)."""
        await self._upsert(
            LastAppliedScene(
                config_name=None,
                source=source,
                applied_at=datetime.now(timezone.utc),
            )
        )

    async def _upsert(self, scene: LastAppliedScene) -> None:
        async with self._lock:
            conn = await self._get_conn()
            await conn.execute(
                _UPSERT,
                (scene.config_name, scene.source, scene.applied_at.isoformat()),
            )
            await conn.commit()
