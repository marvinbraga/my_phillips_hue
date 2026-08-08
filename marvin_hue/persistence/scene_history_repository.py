"""Scene history repository: Protocol + aiosqlite adapter."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Optional, Protocol, runtime_checkable

import aiosqlite

from marvin_hue.domain.scene_history import (
    SceneHistoryNotFoundError,
    SceneHistoryValidationError,
    SceneSnapshot,
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


def _row_to_snapshot(row: aiosqlite.Row) -> SceneSnapshot:
    raw = row["payload_json"]
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise SceneHistoryValidationError(
            f"Corrupt payload_json for snapshot id={row['id']}"
        ) from exc
    if not isinstance(payload, list):
        raise SceneHistoryValidationError(
            f"payload_json must be a JSON list for snapshot id={row['id']}"
        )
    return SceneSnapshot(
        id=int(row["id"]),
        label=row["label"],
        source=row["source"],
        payload=payload,
        created_at=_iso_to_dt(row["created_at"]) or datetime.now(timezone.utc),
    )


@runtime_checkable
class SceneHistoryRepository(Protocol):
    async def create(self, snapshot: SceneSnapshot) -> SceneSnapshot: ...

    async def get_by_id(self, snapshot_id: int) -> SceneSnapshot: ...

    async def get_latest(self) -> Optional[SceneSnapshot]: ...

    async def list_recent(self, limit: int = 10) -> list[SceneSnapshot]: ...

    async def prune_keep_latest(self, keep: int) -> int: ...

    async def close(self) -> None: ...


class SqliteSceneHistoryRepository:
    """aiosqlite-backed scene snapshot repository.

    One shared connection per instance, serialized with asyncio.Lock.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    @classmethod
    async def open(cls, db_path: str) -> "SqliteSceneHistoryRepository":
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

    async def create(self, snapshot: SceneSnapshot) -> SceneSnapshot:
        async with self._lock:
            conn = await self._get_conn()
            payload_json = json.dumps(snapshot.payload, ensure_ascii=False)
            created_at = _dt_to_iso(snapshot.created_at)
            cursor = await conn.execute(
                """
                INSERT INTO scene_snapshots (label, source, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (snapshot.label, snapshot.source, payload_json, created_at),
            )
            await conn.commit()
            new_id = cursor.lastrowid
            if new_id is None:
                raise SceneHistoryValidationError("Failed to insert scene snapshot")
            return await self._get_by_id_unlocked(int(new_id))

    async def _get_by_id_unlocked(self, snapshot_id: int) -> SceneSnapshot:
        conn = await self._get_conn()
        async with conn.execute(
            "SELECT * FROM scene_snapshots WHERE id = ?",
            (snapshot_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            raise SceneHistoryNotFoundError(f"Scene snapshot id={snapshot_id} not found")
        return _row_to_snapshot(row)

    async def get_by_id(self, snapshot_id: int) -> SceneSnapshot:
        async with self._lock:
            return await self._get_by_id_unlocked(snapshot_id)

    async def get_latest(self) -> Optional[SceneSnapshot]:
        async with self._lock:
            conn = await self._get_conn()
            async with conn.execute(
                """
                SELECT * FROM scene_snapshots
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                return None
            return _row_to_snapshot(row)

    async def list_recent(self, limit: int = 10) -> list[SceneSnapshot]:
        if limit < 1:
            raise SceneHistoryValidationError("limit must be >= 1")
        async with self._lock:
            conn = await self._get_conn()
            async with conn.execute(
                """
                SELECT * FROM scene_snapshots
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ) as cur:
                rows = await cur.fetchall()
            return [_row_to_snapshot(r) for r in rows]

    async def prune_keep_latest(self, keep: int) -> int:
        """Delete older snapshots beyond `keep` most recent. Returns deleted count."""
        if keep < 0:
            raise SceneHistoryValidationError("keep must be >= 0")
        async with self._lock:
            conn = await self._get_conn()
            if keep == 0:
                cursor = await conn.execute("DELETE FROM scene_snapshots")
                await conn.commit()
                return int(cursor.rowcount or 0)

            async with conn.execute(
                """
                SELECT id FROM scene_snapshots
                ORDER BY created_at DESC, id DESC
                LIMIT -1 OFFSET ?
                """,
                (keep,),
            ) as cur:
                rows = await cur.fetchall()
            ids = [int(r["id"]) for r in rows]
            if not ids:
                return 0
            placeholders = ",".join("?" for _ in ids)
            cursor = await conn.execute(
                f"DELETE FROM scene_snapshots WHERE id IN ({placeholders})",
                ids,
            )
            await conn.commit()
            return int(cursor.rowcount or 0)
