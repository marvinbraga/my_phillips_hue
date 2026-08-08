"""Schedule repository: Protocol + aiosqlite adapter."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional, Protocol, runtime_checkable

import aiosqlite

from marvin_hue.domain.schedules import (
    Schedule,
    ScheduleNotFoundError,
    ScheduleValidationError,
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


def _row_to_schedule(row: aiosqlite.Row) -> Schedule:
    raw = row["action_payload_json"] or "{}"
    try:
        payload: Any = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ScheduleValidationError(
            f"Corrupt action_payload_json for schedule id={row['id']}"
        ) from exc
    if not isinstance(payload, dict):
        raise ScheduleValidationError(
            f"action_payload_json must be a JSON object for schedule id={row['id']}"
        )
    return Schedule(
        id=row["id"],
        name=row["name"],
        enabled=bool(row["enabled"]),
        time_hhmm=row["time_hhmm"],
        days_of_week=row["days_of_week"] or "",
        action_type=row["action_type"],
        action_payload=payload,
        last_run_at=_iso_to_dt(row["last_run_at"]),
        created_at=_iso_to_dt(row["created_at"]) or datetime.now(timezone.utc),
        updated_at=_iso_to_dt(row["updated_at"]) or datetime.now(timezone.utc),
    )


@runtime_checkable
class ScheduleRepository(Protocol):
    async def create(self, schedule: Schedule) -> Schedule: ...

    async def get_by_id(self, schedule_id: str) -> Schedule: ...

    async def list_all(self) -> list[Schedule]: ...

    async def list_enabled(self) -> list[Schedule]: ...

    async def update(self, schedule: Schedule) -> Schedule: ...

    async def delete(self, schedule_id: str) -> None: ...

    async def mark_last_run(
        self, schedule_id: str, when: Optional[datetime] = None
    ) -> Schedule: ...

    async def close(self) -> None: ...


class SqliteScheduleRepository:
    """aiosqlite-backed schedule repository.

    One shared connection per instance, serialized with asyncio.Lock.
    Hard-delete is used for schedules (no soft-delete column).
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    @classmethod
    async def open(cls, db_path: str) -> "SqliteScheduleRepository":
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

    async def _get_by_id_unlocked(self, schedule_id: str) -> Schedule:
        conn = await self._get_conn()
        async with conn.execute(
            "SELECT * FROM schedules WHERE id = ?",
            (schedule_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            raise ScheduleNotFoundError(f"Schedule id={schedule_id!r} not found")
        return _row_to_schedule(row)

    async def create(self, schedule: Schedule) -> Schedule:
        async with self._lock:
            conn = await self._get_conn()
            try:
                await conn.execute(
                    """
                    INSERT INTO schedules (
                        id, name, enabled, time_hhmm, days_of_week,
                        action_type, action_payload_json, last_run_at,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        schedule.id,
                        schedule.name,
                        1 if schedule.enabled else 0,
                        schedule.time_hhmm,
                        schedule.days_of_week,
                        schedule.action_type,
                        json.dumps(schedule.action_payload, ensure_ascii=False),
                        _dt_to_iso(schedule.last_run_at),
                        _dt_to_iso(schedule.created_at),
                        _dt_to_iso(schedule.updated_at),
                    ),
                )
                await conn.commit()
            except (sqlite3.IntegrityError, aiosqlite.IntegrityError) as exc:
                raise ScheduleValidationError(
                    f"Could not create schedule id={schedule.id!r}"
                ) from exc
            return await self._get_by_id_unlocked(schedule.id)

    async def get_by_id(self, schedule_id: str) -> Schedule:
        async with self._lock:
            return await self._get_by_id_unlocked(schedule_id)

    async def list_all(self) -> list[Schedule]:
        async with self._lock:
            conn = await self._get_conn()
            async with conn.execute(
                """
                SELECT * FROM schedules
                ORDER BY name COLLATE NOCASE
                """
            ) as cur:
                rows = await cur.fetchall()
            return [_row_to_schedule(r) for r in rows]

    async def list_enabled(self) -> list[Schedule]:
        async with self._lock:
            conn = await self._get_conn()
            async with conn.execute(
                """
                SELECT * FROM schedules
                WHERE enabled = 1
                ORDER BY time_hhmm, name COLLATE NOCASE
                """
            ) as cur:
                rows = await cur.fetchall()
            return [_row_to_schedule(r) for r in rows]

    async def update(self, schedule: Schedule) -> Schedule:
        async with self._lock:
            conn = await self._get_conn()
            await self._get_by_id_unlocked(schedule.id)
            schedule.updated_at = datetime.now(timezone.utc)
            try:
                await conn.execute(
                    """
                    UPDATE schedules SET
                        name = ?,
                        enabled = ?,
                        time_hhmm = ?,
                        days_of_week = ?,
                        action_type = ?,
                        action_payload_json = ?,
                        last_run_at = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        schedule.name,
                        1 if schedule.enabled else 0,
                        schedule.time_hhmm,
                        schedule.days_of_week,
                        schedule.action_type,
                        json.dumps(schedule.action_payload, ensure_ascii=False),
                        _dt_to_iso(schedule.last_run_at),
                        _dt_to_iso(schedule.updated_at),
                        schedule.id,
                    ),
                )
                await conn.commit()
            except (sqlite3.IntegrityError, aiosqlite.IntegrityError) as exc:
                raise ScheduleValidationError(
                    f"Could not update schedule id={schedule.id!r}"
                ) from exc
            return await self._get_by_id_unlocked(schedule.id)

    async def delete(self, schedule_id: str) -> None:
        async with self._lock:
            await self._get_by_id_unlocked(schedule_id)
            conn = await self._get_conn()
            await conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
            await conn.commit()

    async def mark_last_run(
        self, schedule_id: str, when: Optional[datetime] = None
    ) -> Schedule:
        async with self._lock:
            schedule = await self._get_by_id_unlocked(schedule_id)
            now = when or datetime.now(timezone.utc)
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
            schedule.last_run_at = now
            schedule.updated_at = datetime.now(timezone.utc)
            conn = await self._get_conn()
            await conn.execute(
                """
                UPDATE schedules SET
                    last_run_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    _dt_to_iso(schedule.last_run_at),
                    _dt_to_iso(schedule.updated_at),
                    schedule.id,
                ),
            )
            await conn.commit()
            return await self._get_by_id_unlocked(schedule.id)
