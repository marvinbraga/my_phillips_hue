"""Light group repository: Protocol + aiosqlite adapter."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from typing import Optional, Protocol, runtime_checkable

import aiosqlite

from marvin_hue.domain.groups import (
    GroupNotFoundError,
    GroupValidationError,
    LightGroup,
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


@runtime_checkable
class GroupRepository(Protocol):
    async def create(self, group: LightGroup) -> LightGroup: ...

    async def get_by_id(
        self, group_id: str, *, include_deleted: bool = False
    ) -> LightGroup: ...

    async def list_all(self, *, include_deleted: bool = False) -> list[LightGroup]: ...

    async def update(self, group: LightGroup) -> LightGroup: ...

    async def soft_delete(self, group_id: str) -> LightGroup: ...

    async def set_members(self, group_id: str, light_ids: list[str]) -> LightGroup: ...

    async def list_member_light_names(self, group_id: str) -> list[str]: ...

    async def close(self) -> None: ...


class SqliteGroupRepository:
    """aiosqlite-backed light group repository.

    One shared connection per instance, serialized with asyncio.Lock for
    safe concurrent use under FastAPI.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    @classmethod
    async def open(cls, db_path: str) -> "SqliteGroupRepository":
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

    async def _member_ids(self, conn: aiosqlite.Connection, group_id: str) -> list[str]:
        async with conn.execute(
            """
            SELECT light_id FROM light_group_members
            WHERE group_id = ?
            ORDER BY light_id
            """,
            (group_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [str(r["light_id"]) for r in rows]

    def _row_to_group(
        self, row: aiosqlite.Row, light_ids: Optional[list[str]] = None
    ) -> LightGroup:
        return LightGroup(
            id=row["id"],
            name=row["name"],
            room=row["room"],
            notes=row["notes"],
            light_ids=list(light_ids) if light_ids is not None else [],
            deleted_at=_iso_to_dt(row["deleted_at"]),
            created_at=_iso_to_dt(row["created_at"]) or datetime.now(timezone.utc),
            updated_at=_iso_to_dt(row["updated_at"]) or datetime.now(timezone.utc),
        )

    async def _get_by_id_unlocked(
        self, group_id: str, *, include_deleted: bool = False
    ) -> LightGroup:
        conn = await self._get_conn()
        sql = "SELECT * FROM light_groups WHERE id = ?"
        params: list[object] = [group_id]
        if not include_deleted:
            sql += " AND deleted_at IS NULL"
        async with conn.execute(sql, params) as cur:
            row = await cur.fetchone()
        if row is None:
            raise GroupNotFoundError(f"Group id={group_id!r} not found")
        members = await self._member_ids(conn, group_id)
        return self._row_to_group(row, members)

    async def create(self, group: LightGroup) -> LightGroup:
        async with self._lock:
            conn = await self._get_conn()
            try:
                await conn.execute(
                    """
                    INSERT INTO light_groups (
                        id, name, room, notes, deleted_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        group.id,
                        group.name,
                        group.room,
                        group.notes,
                        _dt_to_iso(group.deleted_at),
                        _dt_to_iso(group.created_at),
                        _dt_to_iso(group.updated_at),
                    ),
                )
                if group.light_ids:
                    await self._replace_members_unlocked(conn, group.id, group.light_ids)
                await conn.commit()
            except (sqlite3.IntegrityError, aiosqlite.IntegrityError) as exc:
                await conn.rollback()
                msg = str(exc).lower()
                if "foreign key" in msg:
                    raise GroupValidationError(
                        "One or more light_ids do not exist in lights registry"
                    ) from exc
                raise GroupValidationError(
                    f"Active group with name {group.name!r} already exists"
                ) from exc
            return await self._get_by_id_unlocked(group.id, include_deleted=True)

    async def get_by_id(
        self, group_id: str, *, include_deleted: bool = False
    ) -> LightGroup:
        async with self._lock:
            return await self._get_by_id_unlocked(
                group_id, include_deleted=include_deleted
            )

    async def list_all(self, *, include_deleted: bool = False) -> list[LightGroup]:
        async with self._lock:
            conn = await self._get_conn()
            sql = "SELECT * FROM light_groups"
            if not include_deleted:
                sql += " WHERE deleted_at IS NULL"
            sql += " ORDER BY name COLLATE NOCASE"
            async with conn.execute(sql) as cur:
                rows = await cur.fetchall()
            result: list[LightGroup] = []
            for row in rows:
                members = await self._member_ids(conn, row["id"])
                result.append(self._row_to_group(row, members))
            return result

    async def update(self, group: LightGroup) -> LightGroup:
        async with self._lock:
            conn = await self._get_conn()
            await self._get_by_id_unlocked(group.id, include_deleted=True)
            now = datetime.now(timezone.utc)
            group.updated_at = now
            try:
                await conn.execute(
                    """
                    UPDATE light_groups SET
                        name = ?,
                        room = ?,
                        notes = ?,
                        deleted_at = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        group.name,
                        group.room,
                        group.notes,
                        _dt_to_iso(group.deleted_at),
                        _dt_to_iso(group.updated_at),
                        group.id,
                    ),
                )
                await self._replace_members_unlocked(conn, group.id, group.light_ids)
                await conn.commit()
            except (sqlite3.IntegrityError, aiosqlite.IntegrityError) as exc:
                await conn.rollback()
                msg = str(exc).lower()
                if "foreign key" in msg:
                    raise GroupValidationError(
                        "One or more light_ids do not exist in lights registry"
                    ) from exc
                raise GroupValidationError(
                    f"Active group with name {group.name!r} already exists"
                ) from exc
            return await self._get_by_id_unlocked(group.id, include_deleted=True)

    async def soft_delete(self, group_id: str) -> LightGroup:
        async with self._lock:
            group = await self._get_by_id_unlocked(group_id, include_deleted=False)
            now = datetime.now(timezone.utc)
            group.deleted_at = now
            group.updated_at = now
            conn = await self._get_conn()
            await conn.execute(
                """
                UPDATE light_groups SET
                    deleted_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    _dt_to_iso(group.deleted_at),
                    _dt_to_iso(group.updated_at),
                    group.id,
                ),
            )
            await conn.commit()
            return await self._get_by_id_unlocked(group.id, include_deleted=True)

    async def _replace_members_unlocked(
        self,
        conn: aiosqlite.Connection,
        group_id: str,
        light_ids: list[str],
    ) -> None:
        await conn.execute(
            "DELETE FROM light_group_members WHERE group_id = ?",
            (group_id,),
        )
        seen: set[str] = set()
        for light_id in light_ids:
            lid = str(light_id).strip()
            if not lid or lid in seen:
                continue
            seen.add(lid)
            await conn.execute(
                """
                INSERT INTO light_group_members (group_id, light_id)
                VALUES (?, ?)
                """,
                (group_id, lid),
            )

    async def set_members(self, group_id: str, light_ids: list[str]) -> LightGroup:
        async with self._lock:
            await self._get_by_id_unlocked(group_id, include_deleted=False)
            conn = await self._get_conn()
            now = datetime.now(timezone.utc)
            try:
                await self._replace_members_unlocked(conn, group_id, light_ids)
                await conn.execute(
                    """
                    UPDATE light_groups SET updated_at = ? WHERE id = ?
                    """,
                    (_dt_to_iso(now), group_id),
                )
                await conn.commit()
            except (sqlite3.IntegrityError, aiosqlite.IntegrityError) as exc:
                await conn.rollback()
                raise GroupValidationError(
                    "One or more light_ids do not exist in lights registry"
                ) from exc
            return await self._get_by_id_unlocked(group_id, include_deleted=False)

    async def list_member_light_names(self, group_id: str) -> list[str]:
        async with self._lock:
            await self._get_by_id_unlocked(group_id, include_deleted=False)
            conn = await self._get_conn()
            async with conn.execute(
                """
                SELECT l.name AS name
                FROM light_group_members m
                INNER JOIN lights l ON l.id = m.light_id
                WHERE m.group_id = ?
                  AND l.deleted_at IS NULL
                ORDER BY l.name COLLATE NOCASE
                """,
                (group_id,),
            ) as cur:
                rows = await cur.fetchall()
            return [str(r["name"]) for r in rows]
