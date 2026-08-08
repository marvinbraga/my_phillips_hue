"""Import/export backup bundle for registry data and config JSON files.

ZIP layout (format version 1)::

    manifest.json
    lights.json
    groups.json
    schedules.json
    setups.json
    light_positions.json
    light_physical_locations.json   # optional; omitted when path unset/missing

Import strategies
-----------------
- ``merge`` (default): upsert lights (id → bridge_id → name), groups (id → name),
  schedules (id); never deletes existing rows.
- ``replace``: same upserts, then soft-delete lights/groups not in the bundle
  and hard-delete schedules not in the bundle.

JSON config files (setups / positions / physical locations) are always
overwritten after writing a ``.bak`` sibling when the target already exists.
"""

from __future__ import annotations

import io
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal, Optional
from uuid import uuid4

from marvin_hue.domain.groups import GroupNotFoundError, LightGroup
from marvin_hue.domain.lights import LightNotFoundError, RegisteredLight
from marvin_hue.domain.schedules import Schedule, ScheduleNotFoundError
from marvin_hue.logging_config import get_logger
from marvin_hue.persistence.group_repository import GroupRepository
from marvin_hue.persistence.light_repository import LightRegistryRepository
from marvin_hue.persistence.schedule_repository import ScheduleRepository

logger = get_logger("services.backup")

BUNDLE_FORMAT_VERSION = 1
ImportStrategy = Literal["merge", "replace"]

_LIGHTS_NAME = "lights.json"
_GROUPS_NAME = "groups.json"
_SCHEDULES_NAME = "schedules.json"
_SETUPS_NAME = "setups.json"
_POSITIONS_NAME = "light_positions.json"
_PHYSICAL_NAME = "light_physical_locations.json"
_MANIFEST_NAME = "manifest.json"


class BackupError(Exception):
    """Base error for backup import/export."""


class BackupValidationError(BackupError, ValueError):
    """Invalid or unsupported backup payload."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _dt_to_iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _iso_to_dt(value: Optional[str]) -> Optional[datetime]:
    if value is None or value == "":
        return None
    text = str(value).replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _read_json_file(path: Path) -> Any:
    if not path.exists() or not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_json_file_with_bak(path: Path, data: Any) -> None:
    """Replace JSON file; keep previous content as ``path.bak`` when present."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.is_file():
        bak = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, bak)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def _light_to_dict(light: RegisteredLight) -> dict[str, Any]:
    return {
        "id": light.id,
        "name": light.name,
        "nickname": light.nickname,
        "room": light.room,
        "notes": light.notes,
        "bridge_light_id": light.bridge_light_id,
        "eye_safety_limit_pct": light.eye_safety_limit_pct,
        "enabled_for_app": light.enabled_for_app,
        "deleted_at": _dt_to_iso(light.deleted_at),
        "created_at": _dt_to_iso(light.created_at),
        "updated_at": _dt_to_iso(light.updated_at),
    }


def _group_to_dict(group: LightGroup) -> dict[str, Any]:
    return {
        "id": group.id,
        "name": group.name,
        "room": group.room,
        "notes": group.notes,
        "light_ids": list(group.light_ids),
        "deleted_at": _dt_to_iso(group.deleted_at),
        "created_at": _dt_to_iso(group.created_at),
        "updated_at": _dt_to_iso(group.updated_at),
    }


def _schedule_to_dict(schedule: Schedule) -> dict[str, Any]:
    return {
        "id": schedule.id,
        "name": schedule.name,
        "enabled": schedule.enabled,
        "time_hhmm": schedule.time_hhmm,
        "days_of_week": schedule.days_of_week,
        "action_type": schedule.action_type,
        "action_payload": dict(schedule.action_payload),
        "last_run_at": _dt_to_iso(schedule.last_run_at),
        "created_at": _dt_to_iso(schedule.created_at),
        "updated_at": _dt_to_iso(schedule.updated_at),
    }


class BackupService:
    """Export and import a home-features backup bundle."""

    def __init__(
        self,
        light_repo: LightRegistryRepository,
        *,
        group_repo: Optional[GroupRepository] = None,
        schedule_repo: Optional[ScheduleRepository] = None,
        setups_path: str | Path = ".res/setups.json",
        positions_path: str | Path = ".res/light_positions.json",
        physical_locations_path: Optional[str | Path] = (
            ".res/light_physical_locations.json"
        ),
        on_lights_changed: Optional[Callable[[], Awaitable[None]]] = None,
        app_version: str = "2.0.0",
    ) -> None:
        self._lights = light_repo
        self._groups = group_repo
        self._schedules = schedule_repo
        self._setups_path = Path(setups_path)
        self._positions_path = Path(positions_path)
        self._physical_path = (
            Path(physical_locations_path) if physical_locations_path else None
        )
        self._on_lights_changed = on_lights_changed
        self._app_version = app_version

    async def export_dict(self) -> dict[str, Any]:
        """Return mapping of archive member name → JSON-serializable payload."""
        lights = await self._lights.list_all(include_deleted=False)
        groups: list[LightGroup] = []
        if self._groups is not None:
            groups = await self._groups.list_all(include_deleted=False)
        schedules: list[Schedule] = []
        if self._schedules is not None:
            schedules = await self._schedules.list_all()

        payload: dict[str, Any] = {
            _MANIFEST_NAME: {
                "format_version": BUNDLE_FORMAT_VERSION,
                "exported_at": _dt_to_iso(_utc_now()),
                "app_version": self._app_version,
            },
            _LIGHTS_NAME: [_light_to_dict(x) for x in lights],
            _GROUPS_NAME: [_group_to_dict(x) for x in groups],
            _SCHEDULES_NAME: [_schedule_to_dict(x) for x in schedules],
            _SETUPS_NAME: _read_json_file(self._setups_path),
            _POSITIONS_NAME: _read_json_file(self._positions_path),
        }
        if self._physical_path is not None and self._physical_path.exists():
            payload[_PHYSICAL_NAME] = _read_json_file(self._physical_path)
        return payload

    async def export_zip(self) -> bytes:
        """Build an in-memory ZIP of the backup bundle."""
        members = await self.export_dict()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name, data in members.items():
                zf.writestr(
                    name,
                    json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                )
        logger.info(
            "backup_export_complete lights={} groups={} schedules={}",
            len(members.get(_LIGHTS_NAME, [])),
            len(members.get(_GROUPS_NAME, [])),
            len(members.get(_SCHEDULES_NAME, [])),
        )
        return buf.getvalue()

    async def import_zip(
        self,
        data: bytes,
        *,
        strategy: ImportStrategy = "merge",
    ) -> dict[str, Any]:
        """Import a ZIP bundle. Returns a summary of applied changes."""
        if not data:
            raise BackupValidationError("Empty backup file")
        try:
            members = self._unzip_json_members(data)
        except zipfile.BadZipFile as exc:
            raise BackupValidationError("File is not a valid ZIP archive") from exc
        return await self.import_dict(members, strategy=strategy)

    async def import_dict(
        self,
        members: dict[str, Any],
        *,
        strategy: ImportStrategy = "merge",
    ) -> dict[str, Any]:
        """Import from an already-parsed member map (same keys as ZIP)."""
        if strategy not in ("merge", "replace"):
            raise BackupValidationError(
                f"strategy must be 'merge' or 'replace', got {strategy!r}"
            )
        self._validate_manifest(members.get(_MANIFEST_NAME))

        lights_raw = members.get(_LIGHTS_NAME, [])
        groups_raw = members.get(_GROUPS_NAME, [])
        schedules_raw = members.get(_SCHEDULES_NAME, [])
        if not isinstance(lights_raw, list):
            raise BackupValidationError("lights.json must be a JSON array")
        if not isinstance(groups_raw, list):
            raise BackupValidationError("groups.json must be a JSON array")
        if not isinstance(schedules_raw, list):
            raise BackupValidationError("schedules.json must be a JSON array")

        light_stats = await self._import_lights(lights_raw, strategy=strategy)
        group_stats = await self._import_groups(groups_raw, strategy=strategy)
        schedule_stats = await self._import_schedules(schedules_raw, strategy=strategy)

        files_written: list[str] = []
        if _SETUPS_NAME in members:
            _write_json_file_with_bak(self._setups_path, members[_SETUPS_NAME])
            files_written.append(str(self._setups_path))
        if _POSITIONS_NAME in members:
            _write_json_file_with_bak(self._positions_path, members[_POSITIONS_NAME])
            files_written.append(str(self._positions_path))
        if _PHYSICAL_NAME in members and self._physical_path is not None:
            _write_json_file_with_bak(self._physical_path, members[_PHYSICAL_NAME])
            files_written.append(str(self._physical_path))

        if self._on_lights_changed is not None and (
            light_stats["created"] or light_stats["updated"] or light_stats["deleted"]
        ):
            await self._on_lights_changed()

        summary = {
            "strategy": strategy,
            "lights": light_stats,
            "groups": group_stats,
            "schedules": schedule_stats,
            "files_written": files_written,
        }
        logger.info("backup_import_complete summary={}", summary)
        return summary

    @staticmethod
    def _unzip_json_members(data: bytes) -> dict[str, Any]:
        members: dict[str, Any] = {}
        with zipfile.ZipFile(io.BytesIO(data), mode="r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = Path(info.filename).name
                if not name.endswith(".json"):
                    continue
                raw = zf.read(info)
                try:
                    members[name] = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise BackupValidationError(
                        f"Invalid JSON in archive member {name!r}"
                    ) from exc
        return members

    @staticmethod
    def _validate_manifest(manifest: Any) -> None:
        if manifest is None:
            raise BackupValidationError("manifest.json is required")
        if not isinstance(manifest, dict):
            raise BackupValidationError("manifest.json must be a JSON object")
        version = manifest.get("format_version")
        if version is None:
            raise BackupValidationError("manifest.format_version is required")
        try:
            version_int = int(version)
        except (TypeError, ValueError) as exc:
            raise BackupValidationError(
                f"manifest.format_version must be an integer, got {version!r}"
            ) from exc
        if version_int != BUNDLE_FORMAT_VERSION:
            raise BackupValidationError(
                f"Unsupported backup format_version {version_int}; "
                f"supported: {BUNDLE_FORMAT_VERSION}"
            )

    async def _import_lights(
        self, rows: list[Any], *, strategy: ImportStrategy
    ) -> dict[str, int]:
        created = updated = unchanged = deleted = 0
        kept_ids: set[str] = set()

        for raw in rows:
            if not isinstance(raw, dict):
                raise BackupValidationError("Each light entry must be an object")
            name = str(raw.get("name") or "").strip()
            if not name:
                raise BackupValidationError("Light entry missing name")
            light_id = str(raw.get("id") or "").strip() or str(uuid4())
            bridge_id_raw = raw.get("bridge_light_id")
            bridge_id = (
                str(bridge_id_raw).strip() or None
                if bridge_id_raw is not None
                else None
            )
            nickname = raw.get("nickname")
            room = raw.get("room")
            notes = raw.get("notes")
            eye = raw.get("eye_safety_limit_pct")
            if eye is not None and not isinstance(eye, int):
                try:
                    eye = int(eye)
                except (TypeError, ValueError) as exc:
                    raise BackupValidationError(
                        f"Invalid eye_safety_limit_pct for light {name!r}"
                    ) from exc
            enabled = raw.get("enabled_for_app", True)
            deleted_at = _iso_to_dt(raw.get("deleted_at"))
            created_at = _iso_to_dt(raw.get("created_at")) or _utc_now()
            updated_at = _iso_to_dt(raw.get("updated_at")) or _utc_now()

            existing = await self._find_light(
                light_id=light_id, bridge_id=bridge_id, name=name
            )
            if existing is None:
                light = RegisteredLight(
                    id=light_id,
                    name=name,
                    nickname=str(nickname).strip() if nickname else None,
                    room=str(room).strip() if room else None,
                    notes=str(notes).strip() if notes else None,
                    bridge_light_id=bridge_id,
                    eye_safety_limit_pct=eye,
                    enabled_for_app=bool(enabled),
                    deleted_at=deleted_at,
                    created_at=created_at,
                    updated_at=updated_at,
                )
                await self._lights.create(light)
                kept_ids.add(light.id)
                created += 1
                continue

            kept_ids.add(existing.id)
            # Apply imported metadata onto matched row (keep local id).
            changed = False
            new_name = name
            new_nick = str(nickname).strip() if nickname else None
            new_room = str(room).strip() if room else None
            new_notes = str(notes).strip() if notes else None
            new_enabled = bool(enabled)
            if existing.name != new_name:
                existing.name = new_name
                changed = True
            if existing.nickname != new_nick:
                existing.nickname = new_nick
                changed = True
            if existing.room != new_room:
                existing.room = new_room
                changed = True
            if existing.notes != new_notes:
                existing.notes = new_notes
                changed = True
            if existing.bridge_light_id != bridge_id and bridge_id is not None:
                existing.bridge_light_id = bridge_id
                changed = True
            if existing.eye_safety_limit_pct != eye:
                existing.eye_safety_limit_pct = eye
                changed = True
            if existing.enabled_for_app != new_enabled:
                existing.enabled_for_app = new_enabled
                changed = True
            if deleted_at is None and existing.deleted_at is not None:
                existing.deleted_at = None
                changed = True
            if changed:
                existing.updated_at = _utc_now()
                await self._lights.update(existing)
                updated += 1
            else:
                unchanged += 1

        if strategy == "replace":
            active = await self._lights.list_all(include_deleted=False)
            for light in active:
                if light.id not in kept_ids:
                    await self._lights.soft_delete(light.id)
                    deleted += 1

        return {
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
            "deleted": deleted,
        }

    async def _find_light(
        self,
        *,
        light_id: str,
        bridge_id: Optional[str],
        name: str,
    ) -> Optional[RegisteredLight]:
        try:
            return await self._lights.get_by_id(light_id, include_deleted=True)
        except LightNotFoundError:
            pass
        if bridge_id:
            by_bridge = await self._lights.get_by_bridge_light_id(
                bridge_id, include_deleted=True
            )
            if by_bridge is not None:
                return by_bridge
        return await self._lights.get_by_name(name, include_deleted=True)

    async def _import_groups(
        self, rows: list[Any], *, strategy: ImportStrategy
    ) -> dict[str, int]:
        created = updated = unchanged = deleted = 0
        if self._groups is None:
            return {
                "created": 0,
                "updated": 0,
                "unchanged": 0,
                "deleted": 0,
                "skipped": len(rows),
            }

        kept_ids: set[str] = set()
        for raw in rows:
            if not isinstance(raw, dict):
                raise BackupValidationError("Each group entry must be an object")
            name = str(raw.get("name") or "").strip()
            if not name:
                raise BackupValidationError("Group entry missing name")
            group_id = str(raw.get("id") or "").strip() or str(uuid4())
            room = raw.get("room")
            notes = raw.get("notes")
            light_ids_raw = raw.get("light_ids") or []
            if not isinstance(light_ids_raw, list):
                raise BackupValidationError(
                    f"group {name!r} light_ids must be an array"
                )
            light_ids = [str(x).strip() for x in light_ids_raw if str(x).strip()]
            deleted_at = _iso_to_dt(raw.get("deleted_at"))
            created_at = _iso_to_dt(raw.get("created_at")) or _utc_now()
            updated_at = _iso_to_dt(raw.get("updated_at")) or _utc_now()

            existing = await self._find_group(group_id=group_id, name=name)
            if existing is None:
                group = LightGroup(
                    id=group_id,
                    name=name,
                    room=str(room).strip() if room else None,
                    notes=str(notes).strip() if notes else None,
                    light_ids=light_ids,
                    deleted_at=deleted_at,
                    created_at=created_at,
                    updated_at=updated_at,
                )
                await self._groups.create(group)
                kept_ids.add(group.id)
                created += 1
                continue

            kept_ids.add(existing.id)
            new_room = str(room).strip() if room else None
            new_notes = str(notes).strip() if notes else None
            changed = (
                existing.name != name
                or existing.room != new_room
                or existing.notes != new_notes
                or list(existing.light_ids) != light_ids
                or (deleted_at is None and existing.deleted_at is not None)
            )
            if changed:
                existing.name = name
                existing.room = new_room
                existing.notes = new_notes
                existing.light_ids = light_ids
                if deleted_at is None:
                    existing.deleted_at = None
                existing.updated_at = _utc_now()
                await self._groups.update(existing)
                updated += 1
            else:
                unchanged += 1

        if strategy == "replace":
            active = await self._groups.list_all(include_deleted=False)
            for group in active:
                if group.id not in kept_ids:
                    await self._groups.soft_delete(group.id)
                    deleted += 1

        return {
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
            "deleted": deleted,
        }

    async def _find_group(
        self, *, group_id: str, name: str
    ) -> Optional[LightGroup]:
        assert self._groups is not None
        try:
            return await self._groups.get_by_id(group_id, include_deleted=True)
        except GroupNotFoundError:
            pass
        # No get_by_name on protocol — scan active+deleted
        all_groups = await self._groups.list_all(include_deleted=True)
        for g in all_groups:
            if g.name == name:
                return g
        return None

    async def _import_schedules(
        self, rows: list[Any], *, strategy: ImportStrategy
    ) -> dict[str, int]:
        created = updated = unchanged = deleted = 0
        if self._schedules is None:
            return {
                "created": 0,
                "updated": 0,
                "unchanged": 0,
                "deleted": 0,
                "skipped": len(rows),
            }

        kept_ids: set[str] = set()
        for raw in rows:
            if not isinstance(raw, dict):
                raise BackupValidationError("Each schedule entry must be an object")
            name = str(raw.get("name") or "").strip()
            if not name:
                raise BackupValidationError("Schedule entry missing name")
            schedule_id = str(raw.get("id") or "").strip() or str(uuid4())
            time_hhmm = str(raw.get("time_hhmm") or "").strip()
            action_type = str(raw.get("action_type") or "").strip()
            if not time_hhmm or not action_type:
                raise BackupValidationError(
                    f"Schedule {name!r} requires time_hhmm and action_type"
                )
            enabled = bool(raw.get("enabled", True))
            days = str(raw.get("days_of_week") or "")
            payload = raw.get("action_payload") or {}
            if not isinstance(payload, dict):
                raise BackupValidationError(
                    f"Schedule {name!r} action_payload must be an object"
                )
            last_run = _iso_to_dt(raw.get("last_run_at"))
            created_at = _iso_to_dt(raw.get("created_at")) or _utc_now()
            updated_at = _iso_to_dt(raw.get("updated_at")) or _utc_now()

            schedule = Schedule(
                id=schedule_id,
                name=name,
                enabled=enabled,
                time_hhmm=time_hhmm,
                days_of_week=days,
                action_type=action_type,
                action_payload=payload,
                last_run_at=last_run,
                created_at=created_at,
                updated_at=updated_at,
            )

            existing: Optional[Schedule] = None
            try:
                existing = await self._schedules.get_by_id(schedule_id)
            except ScheduleNotFoundError:
                existing = None

            if existing is None:
                await self._schedules.create(schedule)
                kept_ids.add(schedule.id)
                created += 1
            else:
                kept_ids.add(existing.id)
                # Replace fields by id (plan: schedules replace by id)
                schedule.id = existing.id
                await self._schedules.update(schedule)
                updated += 1

        if strategy == "replace":
            current = await self._schedules.list_all()
            for sched in current:
                if sched.id not in kept_ids:
                    await self._schedules.delete(sched.id)
                    deleted += 1

        return {
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
            "deleted": deleted,
        }
