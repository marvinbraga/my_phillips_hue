"""Light registry repository: Protocol + aiosqlite adapter."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from typing import Optional, Protocol, runtime_checkable

import aiosqlite

from marvin_hue.domain.lights import (
    LightNotFoundError,
    LightValidationError,
    RegisteredLight,
)


def _dt_to_iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _iso_to_dt(value: Optional[str]) -> Optional[datetime]:
    if value is None or value == "":
        return None
    text = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _row_to_light(row: aiosqlite.Row) -> RegisteredLight:
    return RegisteredLight(
        id=row["id"],
        name=row["name"],
        nickname=row["nickname"],
        room=row["room"],
        notes=row["notes"],
        bridge_light_id=row["bridge_light_id"],
        eye_safety_limit_pct=row["eye_safety_limit_pct"],
        enabled_for_app=bool(row["enabled_for_app"]),
        deleted_at=_iso_to_dt(row["deleted_at"]),
        created_at=_iso_to_dt(row["created_at"]) or datetime.now(timezone.utc),
        updated_at=_iso_to_dt(row["updated_at"]) or datetime.now(timezone.utc),
    )


@runtime_checkable
class LightRegistryRepository(Protocol):
    async def create(self, light: RegisteredLight) -> RegisteredLight: ...

    async def get_by_id(
        self, light_id: str, *, include_deleted: bool = False
    ) -> RegisteredLight: ...

    async def get_by_name(
        self, name: str, *, include_deleted: bool = False
    ) -> Optional[RegisteredLight]: ...

    async def get_by_bridge_light_id(
        self, bridge_light_id: str, *, include_deleted: bool = False
    ) -> Optional[RegisteredLight]: ...

    async def list_all(self, *, include_deleted: bool = False) -> list[RegisteredLight]: ...

    async def update(self, light: RegisteredLight) -> RegisteredLight: ...

    async def soft_delete(self, light_id: str) -> RegisteredLight: ...

    async def close(self) -> None: ...


class SqliteLightRegistryRepository:
    """aiosqlite-backed light catalog repository.

    One shared connection per instance, serialized with asyncio.Lock for
    safe concurrent use under FastAPI.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    @classmethod
    async def open(cls, db_path: str) -> "SqliteLightRegistryRepository":
        repo = cls(db_path)
        await repo._get_conn()
        return repo

    async def _get_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            self._conn = await aiosqlite.connect(self._db_path)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA foreign_keys = ON")
        return self._conn

    async def close(self) -> None:
        async with self._lock:
            if self._conn is not None:
                await self._conn.close()
                self._conn = None

    async def create(self, light: RegisteredLight) -> RegisteredLight:
        async with self._lock:
            conn = await self._get_conn()
            try:
                await conn.execute(
                    """
                    INSERT INTO lights (
                        id, bridge_light_id, name, nickname, room, notes,
                        eye_safety_limit_pct, enabled_for_app, deleted_at,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        light.id,
                        light.bridge_light_id,
                        light.name,
                        light.nickname,
                        light.room,
                        light.notes,
                        light.eye_safety_limit_pct,
                        1 if light.enabled_for_app else 0,
                        _dt_to_iso(light.deleted_at),
                        _dt_to_iso(light.created_at),
                        _dt_to_iso(light.updated_at),
                    ),
                )
                await conn.commit()
            except (sqlite3.IntegrityError, aiosqlite.IntegrityError) as exc:
                raise LightValidationError(
                    f"Active light with name {light.name!r} already exists"
                ) from exc
            return await self._get_by_id_unlocked(light.id, include_deleted=True)

    async def _get_by_id_unlocked(
        self, light_id: str, *, include_deleted: bool = False
    ) -> RegisteredLight:
        conn = await self._get_conn()
        sql = "SELECT * FROM lights WHERE id = ?"
        params: list[object] = [light_id]
        if not include_deleted:
            sql += " AND deleted_at IS NULL"
        async with conn.execute(sql, params) as cur:
            row = await cur.fetchone()
        if row is None:
            raise LightNotFoundError(f"Light id={light_id!r} not found")
        return _row_to_light(row)

    async def get_by_id(
        self, light_id: str, *, include_deleted: bool = False
    ) -> RegisteredLight:
        async with self._lock:
            return await self._get_by_id_unlocked(
                light_id, include_deleted=include_deleted
            )

    async def get_by_name(
        self, name: str, *, include_deleted: bool = False
    ) -> Optional[RegisteredLight]:
        """Deterministic: prefer active, then most recently updated."""
        async with self._lock:
            conn = await self._get_conn()
            sql = """
                SELECT * FROM lights
                WHERE name = ?
            """
            params: list[object] = [name]
            if not include_deleted:
                sql += " AND deleted_at IS NULL"
            sql += " ORDER BY deleted_at IS NULL DESC, updated_at DESC LIMIT 1"
            async with conn.execute(sql, params) as cur:
                row = await cur.fetchone()
            if row is None:
                return None
            return _row_to_light(row)

    async def get_by_bridge_light_id(
        self, bridge_light_id: str, *, include_deleted: bool = False
    ) -> Optional[RegisteredLight]:
        """Deterministic: prefer active, then most recently updated."""
        async with self._lock:
            conn = await self._get_conn()
            sql = """
                SELECT * FROM lights
                WHERE bridge_light_id = ?
            """
            params: list[object] = [bridge_light_id]
            if not include_deleted:
                sql += " AND deleted_at IS NULL"
            sql += " ORDER BY deleted_at IS NULL DESC, updated_at DESC LIMIT 1"
            async with conn.execute(sql, params) as cur:
                row = await cur.fetchone()
            if row is None:
                return None
            return _row_to_light(row)

    async def list_all(self, *, include_deleted: bool = False) -> list[RegisteredLight]:
        async with self._lock:
            conn = await self._get_conn()
            sql = "SELECT * FROM lights"
            if not include_deleted:
                sql += " WHERE deleted_at IS NULL"
            sql += " ORDER BY name COLLATE NOCASE"
            async with conn.execute(sql) as cur:
                rows = await cur.fetchall()
            return [_row_to_light(r) for r in rows]

    async def update(self, light: RegisteredLight) -> RegisteredLight:
        async with self._lock:
            conn = await self._get_conn()
            await self._get_by_id_unlocked(light.id, include_deleted=True)
            now = datetime.now(timezone.utc)
            light.updated_at = now
            try:
                await conn.execute(
                    """
                    UPDATE lights SET
                        bridge_light_id = ?,
                        name = ?,
                        nickname = ?,
                        room = ?,
                        notes = ?,
                        eye_safety_limit_pct = ?,
                        enabled_for_app = ?,
                        deleted_at = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        light.bridge_light_id,
                        light.name,
                        light.nickname,
                        light.room,
                        light.notes,
                        light.eye_safety_limit_pct,
                        1 if light.enabled_for_app else 0,
                        _dt_to_iso(light.deleted_at),
                        _dt_to_iso(light.updated_at),
                        light.id,
                    ),
                )
                await conn.commit()
            except (sqlite3.IntegrityError, aiosqlite.IntegrityError) as exc:
                raise LightValidationError(
                    f"Active light with name {light.name!r} already exists"
                ) from exc
            return await self._get_by_id_unlocked(light.id, include_deleted=True)

    async def soft_delete(self, light_id: str) -> RegisteredLight:
        async with self._lock:
            light = await self._get_by_id_unlocked(light_id, include_deleted=False)
            light.deleted_at = datetime.now(timezone.utc)
            light.updated_at = light.deleted_at
            # inline update without re-entering lock
            conn = await self._get_conn()
            await conn.execute(
                """
                UPDATE lights SET
                    deleted_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    _dt_to_iso(light.deleted_at),
                    _dt_to_iso(light.updated_at),
                    light.id,
                ),
            )
            await conn.commit()
            return await self._get_by_id_unlocked(light.id, include_deleted=True)
