"""Service tests for backup export/import (temp SQLite + temp JSON files)."""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from uuid import uuid4

import pytest

from marvin_hue.domain.groups import LightGroup
from marvin_hue.domain.lights import RegisteredLight
from marvin_hue.domain.schedules import Schedule
from marvin_hue.persistence.favorites_repository import SqliteSceneFavoritesRepository
from marvin_hue.persistence.group_repository import SqliteGroupRepository
from marvin_hue.persistence.light_repository import SqliteLightRegistryRepository
from marvin_hue.persistence.schedule_repository import SqliteScheduleRepository
from marvin_hue.persistence.schema import init_db
from marvin_hue.services.backup import (
    BUNDLE_FORMAT_VERSION,
    BackupService,
    BackupValidationError,
)


@pytest.fixture
async def backup_env(tmp_path):
    db_path = str(tmp_path / "app.sqlite")
    await init_db(db_path)
    light_repo = await SqliteLightRegistryRepository.open(db_path)
    group_repo = await SqliteGroupRepository.open(db_path)
    schedule_repo = await SqliteScheduleRepository.open(db_path)
    favorites_repo = await SqliteSceneFavoritesRepository.open(db_path)

    setups = tmp_path / "setups.json"
    positions = tmp_path / "light_positions.json"
    physical = tmp_path / "light_physical_locations.json"
    setups.write_text(
        json.dumps({"setups": [{"name": "focus", "settings": []}]}),
        encoding="utf-8",
    )
    positions.write_text(
        json.dumps({"lights": [{"name": "Lâmpada 1", "position": "none", "enabled": True}]}),
        encoding="utf-8",
    )
    physical.write_text(
        json.dumps({"lights": [{"name": "Lâmpada 1", "location": "ceiling"}]}),
        encoding="utf-8",
    )

    refreshed: list[bool] = []

    async def on_changed() -> None:
        refreshed.append(True)

    svc = BackupService(
        light_repo,
        group_repo=group_repo,
        schedule_repo=schedule_repo,
        favorites_repo=favorites_repo,
        setups_path=setups,
        positions_path=positions,
        physical_locations_path=physical,
        on_lights_changed=on_changed,
        app_version="test",
    )
    yield {
        "svc": svc,
        "light_repo": light_repo,
        "group_repo": group_repo,
        "schedule_repo": schedule_repo,
        "favorites_repo": favorites_repo,
        "setups": setups,
        "positions": positions,
        "physical": physical,
        "refreshed": refreshed,
        "tmp_path": tmp_path,
    }
    await light_repo.close()
    await group_repo.close()
    await schedule_repo.close()
    await favorites_repo.close()


def _light(**kwargs) -> RegisteredLight:
    defaults = dict(
        id=str(uuid4()),
        name="Lâmpada 1",
        nickname="Mesa",
        room="Escritório",
        notes=None,
        bridge_light_id="bridge-1",
        eye_safety_limit_pct=40,
        enabled_for_app=True,
    )
    defaults.update(kwargs)
    return RegisteredLight(**defaults)


@pytest.mark.asyncio
async def test_export_dict_contains_expected_members(backup_env):
    env = backup_env
    light = await env["light_repo"].create(_light())
    group = await env["group_repo"].create(
        LightGroup(id=str(uuid4()), name="Sala", light_ids=[light.id])
    )
    await env["schedule_repo"].create(
        Schedule(
            id=str(uuid4()),
            name="Manhã",
            time_hhmm="07:30",
            action_type="apply_config",
            action_payload={"config_name": "focus"},
        )
    )

    payload = await env["svc"].export_dict()
    assert payload["manifest.json"]["format_version"] == BUNDLE_FORMAT_VERSION
    assert payload["lights.json"][0]["id"] == light.id
    assert payload["groups.json"][0]["id"] == group.id
    assert payload["schedules.json"][0]["name"] == "Manhã"
    assert payload["setups.json"]["setups"][0]["name"] == "focus"
    assert "light_positions.json" in payload
    assert "light_physical_locations.json" in payload


@pytest.mark.asyncio
async def test_export_zip_roundtrip_merge(backup_env):
    env = backup_env
    light = await env["light_repo"].create(_light(name="Hue Iris", bridge_light_id="b-iris"))
    await env["group_repo"].create(
        LightGroup(id=str(uuid4()), name="Corner", light_ids=[light.id])
    )

    zbytes = await env["svc"].export_zip()
    assert zipfile.is_zipfile(BytesIO(zbytes))

    # Wipe and re-import
    await env["light_repo"].soft_delete(light.id)
    summary = await env["svc"].import_zip(zbytes, strategy="merge")
    assert summary["lights"]["created"] >= 1 or summary["lights"]["updated"] >= 1
    active = await env["light_repo"].list_all(include_deleted=False)
    names = {x.name for x in active}
    assert "Hue Iris" in names
    assert env["refreshed"]  # policy refresh callback fired


@pytest.mark.asyncio
async def test_import_upserts_light_by_bridge_id(backup_env):
    env = backup_env
    existing = await env["light_repo"].create(
        _light(name="Old Name", bridge_light_id="same-bridge", nickname="A")
    )
    zbytes = await env["svc"].export_zip()

    # Mutate export: change name for same bridge id, different id
    members = env["svc"]._unzip_json_members(zbytes)  # noqa: SLF001
    members["lights.json"] = [
        {
            "id": str(uuid4()),
            "name": "New Name",
            "nickname": "B",
            "room": "Sala",
            "notes": None,
            "bridge_light_id": "same-bridge",
            "eye_safety_limit_pct": 10,
            "enabled_for_app": True,
            "deleted_at": None,
            "created_at": existing.created_at.isoformat(),
            "updated_at": existing.updated_at.isoformat(),
        }
    ]
    # rebuild zip

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, json.dumps(data))
    summary = await env["svc"].import_zip(buf.getvalue(), strategy="merge")
    assert summary["lights"]["updated"] == 1
    found = await env["light_repo"].get_by_id(existing.id)
    assert found.name == "New Name"
    assert found.nickname == "B"
    assert found.eye_safety_limit_pct == 10


@pytest.mark.asyncio
async def test_import_replace_soft_deletes_missing_lights(backup_env):
    env = backup_env
    keep = await env["light_repo"].create(_light(name="Keep", bridge_light_id="k1"))
    drop = await env["light_repo"].create(_light(name="Drop", bridge_light_id="d1"))
    zbytes = await env["svc"].export_zip()

    # Rebuild zip with only Keep
    members = env["svc"]._unzip_json_members(zbytes)  # noqa: SLF001
    members["lights.json"] = [x for x in members["lights.json"] if x["id"] == keep.id]
    members["groups.json"] = []
    members["schedules.json"] = []
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, json.dumps(data))

    summary = await env["svc"].import_zip(buf.getvalue(), strategy="replace")
    assert summary["lights"]["deleted"] == 1
    active = await env["light_repo"].list_all(include_deleted=False)
    assert {x.id for x in active} == {keep.id}
    deleted = await env["light_repo"].get_by_id(drop.id, include_deleted=True)
    assert deleted.deleted_at is not None


@pytest.mark.asyncio
async def test_import_writes_json_files_with_bak(backup_env):
    env = backup_env
    zbytes = await env["svc"].export_zip()
    members = env["svc"]._unzip_json_members(zbytes)  # noqa: SLF001
    members["setups.json"] = {"setups": [{"name": "imported", "settings": []}]}
    members["light_positions.json"] = {
        "lights": [{"name": "X", "position": "left", "enabled": True}]
    }
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, json.dumps(data))

    await env["svc"].import_zip(buf.getvalue(), strategy="merge")
    assert json.loads(env["setups"].read_text(encoding="utf-8"))["setups"][0]["name"] == (
        "imported"
    )
    bak = env["setups"].with_suffix(env["setups"].suffix + ".bak")
    assert bak.exists()
    assert "focus" in bak.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_import_rejects_bad_manifest(backup_env):
    env = backup_env
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"format_version": 99}))
        zf.writestr("lights.json", "[]")
    with pytest.raises(BackupValidationError, match="Unsupported"):
        await env["svc"].import_zip(buf.getvalue())


@pytest.mark.asyncio
async def test_import_rejects_non_zip(backup_env):
    env = backup_env
    with pytest.raises(BackupValidationError):
        await env["svc"].import_zip(b"not-a-zip")


@pytest.mark.asyncio
async def test_import_schedules_and_groups(backup_env):
    env = backup_env
    light = await env["light_repo"].create(_light(name="Play", bridge_light_id="p1"))
    gid = str(uuid4())
    sid = str(uuid4())
    members = {
        "manifest.json": {
            "format_version": BUNDLE_FORMAT_VERSION,
            "exported_at": "2026-01-01T00:00:00+00:00",
            "app_version": "test",
        },
        "lights.json": [
            {
                "id": light.id,
                "name": light.name,
                "bridge_light_id": light.bridge_light_id,
                "enabled_for_app": True,
            }
        ],
        "groups.json": [
            {
                "id": gid,
                "name": "Desk",
                "light_ids": [light.id],
            }
        ],
        "schedules.json": [
            {
                "id": sid,
                "name": "Night",
                "time_hhmm": "22:00",
                "action_type": "power_off",
                "action_payload": {},
                "enabled": True,
                "days_of_week": "0,1,2,3,4",
            }
        ],
        "setups.json": {"setups": []},
        "light_positions.json": {"lights": []},
    }
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, json.dumps(data))

    summary = await env["svc"].import_zip(buf.getvalue(), strategy="merge")
    assert summary["groups"]["created"] == 1
    assert summary["schedules"]["created"] == 1
    group = await env["group_repo"].get_by_id(gid)
    assert group.light_ids == [light.id]
    schedule = await env["schedule_repo"].get_by_id(sid)
    assert schedule.time_hhmm == "22:00"


# --- Scene favorites (D5) -------------------------------------------------


def _bundle(**members):
    base = {"manifest.json": {"format_version": BUNDLE_FORMAT_VERSION}}
    base.update(members)
    return base


@pytest.mark.asyncio
async def test_export_includes_all_favorites_including_orphans(backup_env):
    env = backup_env
    # "ghost" não existe em setups.json: órfão continua no export.
    await env["favorites_repo"].add("focus")
    await env["favorites_repo"].add("ghost")

    payload = await env["svc"].export_dict()
    assert payload["favorites.json"] == ["focus", "ghost"]


@pytest.mark.asyncio
async def test_export_zip_contains_favorites_member(backup_env):
    env = backup_env
    await env["favorites_repo"].add("focus")
    zbytes = await env["svc"].export_zip()
    with zipfile.ZipFile(BytesIO(zbytes)) as zf:
        assert json.loads(zf.read("favorites.json")) == ["focus"]


@pytest.mark.asyncio
async def test_import_favorites_merge_is_union(backup_env):
    env = backup_env
    await env["favorites_repo"].add("local_only")
    await env["favorites_repo"].add("shared")

    summary = await env["svc"].import_dict(
        _bundle(**{"favorites.json": ["shared", "from_bundle"]}), strategy="merge"
    )
    assert await env["favorites_repo"].list_names() == [
        "from_bundle",
        "local_only",
        "shared",
    ]
    assert summary["favorites"] == {"added": 1, "removed": 0, "total": 3}


@pytest.mark.asyncio
async def test_import_favorites_replace_overwrites(backup_env):
    env = backup_env
    await env["favorites_repo"].add("local_only")
    await env["favorites_repo"].add("shared")

    summary = await env["svc"].import_dict(
        _bundle(**{"favorites.json": ["shared", "from_bundle"]}), strategy="replace"
    )
    assert await env["favorites_repo"].list_names() == ["from_bundle", "shared"]
    assert summary["favorites"] == {"added": 1, "removed": 1, "total": 2}


@pytest.mark.asyncio
@pytest.mark.parametrize("strategy", ["merge", "replace"])
async def test_import_old_bundle_without_favorites_keeps_local(backup_env, strategy):
    env = backup_env
    await env["favorites_repo"].add("local_only")

    summary = await env["svc"].import_dict(_bundle(), strategy=strategy)
    assert await env["favorites_repo"].list_names() == ["local_only"]
    assert summary["favorites"] == {
        "added": 0,
        "removed": 0,
        "total": 1,
        "skipped": True,
    }


@pytest.mark.asyncio
async def test_import_favorites_roundtrip_zip(backup_env):
    env = backup_env
    await env["favorites_repo"].add("focus")
    zbytes = await env["svc"].export_zip()
    await env["favorites_repo"].replace_all([])

    await env["svc"].import_zip(zbytes, strategy="merge")
    assert await env["favorites_repo"].list_names() == ["focus"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        None,
        {"a": 1},
        "focus",
        [1, 2],
        ["ok", None],
        ["x"] * 1001,
        ["a" * 201],
    ],
    ids=["null", "object", "string", "ints", "none-entry", "too-many", "too-long"],
)
async def test_import_favorites_rejects_invalid_payload(backup_env, bad):
    env = backup_env
    with pytest.raises(BackupValidationError):
        await env["svc"].import_dict(_bundle(**{"favorites.json": bad}))


@pytest.mark.asyncio
async def test_import_favorites_without_repo_is_skipped(tmp_path):
    db_path = str(tmp_path / "nofav.sqlite")
    await init_db(db_path)
    light_repo = await SqliteLightRegistryRepository.open(db_path)
    try:
        svc = BackupService(
            light_repo,
            setups_path=tmp_path / "s.json",
            positions_path=tmp_path / "p.json",
            physical_locations_path=None,
        )
        payload = await svc.export_dict()
        assert "favorites.json" not in payload
        summary = await svc.import_dict(_bundle(**{"favorites.json": ["x"]}))
        assert summary["favorites"] == {
            "added": 0,
            "removed": 0,
            "total": 0,
            "skipped": True,
        }
    finally:
        await light_repo.close()


@pytest.mark.asyncio
async def test_import_invalid_favorites_aborts_before_any_write(backup_env):
    """Validação acontece antes de qualquer escrita: nada é importado."""
    env = backup_env
    await env["favorites_repo"].add("local_only")
    bundle = _bundle(
        **{
            "lights.json": [
                {
                    "id": str(uuid4()),
                    "name": "Nova Lâmpada",
                    "bridge_light_id": "nb-1",
                }
            ],
            "favorites.json": None,
        }
    )
    with pytest.raises(BackupValidationError):
        await env["svc"].import_dict(bundle, strategy="replace")
    assert await env["favorites_repo"].list_names() == ["local_only"]
    assert await env["light_repo"].list_all(include_deleted=True) == []

    # Controle: a mesma linha de lâmpada é válida e importa quando o resto é ok.
    bundle["favorites.json"] = []
    await env["svc"].import_dict(bundle, strategy="merge")
    imported = await env["light_repo"].list_all(include_deleted=True)
    assert [x.name for x in imported] == ["Nova Lâmpada"]


@pytest.mark.asyncio
async def test_import_favorites_merge_normalizes_names(backup_env):
    env = backup_env
    summary = await env["svc"].import_dict(
        _bundle(**{"favorites.json": [" focus ", "focus", "", "   ", "focus\t"]}),
        strategy="merge",
    )
    assert await env["favorites_repo"].list_names() == ["focus"]
    assert summary["favorites"] == {"added": 1, "removed": 0, "total": 1}


@pytest.mark.asyncio
async def test_import_favorites_accepts_limits(backup_env):
    env = backup_env
    names = [f"s{i:04d}" for i in range(999)] + ["a" * 200]
    summary = await env["svc"].import_dict(
        _bundle(**{"favorites.json": names}), strategy="replace"
    )
    assert summary["favorites"]["total"] == 1000
