"""LightSetupsManager.save atômico + add_config com lock (Gate 8 #16, item 6)."""
from __future__ import annotations

import json
import threading

import pytest

from marvin_hue.basics import (
    ConfigNotFoundError,
    DuplicateConfigError,
    LightConfig,
    LightSetting,
    LightSetupsManager,
    ReservedConfigNameError,
)
from marvin_hue.colors import Color


def _cfg(name: str) -> LightConfig:
    return LightConfig(name, [LightSetting("Lâmpada 1", Color(1, 2, 3, 100))], "d")


def _failing_write(monkeypatch) -> None:
    """Falha só a escrita do manager (não ``os.replace`` global)."""

    def boom(path, payload):
        raise OSError("ro")

    monkeypatch.setattr("marvin_hue.basics.write_json_atomic", boom)


def test_save_replaces_file_atomically(sample_setups_json, monkeypatch):
    import marvin_hue.atomic_io as aio

    calls = []
    real = aio.os.replace
    monkeypatch.setattr(aio.os, "replace", lambda a, b: (calls.append((a, b)), real(a, b)))
    manager = LightSetupsManager(str(sample_setups_json))
    manager.save()
    assert calls and calls[0][1] == str(sample_setups_json)
    assert len(json.loads(sample_setups_json.read_text("utf-8"))["setups"]) == 2
    leftovers = [p for p in sample_setups_json.parent.iterdir() if p.name.startswith(".tmp")]
    assert leftovers == []


def test_save_failure_raises_and_keeps_original(sample_setups_json, monkeypatch):
    import marvin_hue.atomic_io as aio

    original = sample_setups_json.read_text("utf-8")

    def boom(a, b):
        raise OSError("disk full")

    monkeypatch.setattr(aio.os, "replace", boom)
    manager = LightSetupsManager(str(sample_setups_json))
    manager.configs.append(_cfg("x"))
    with pytest.raises(OSError):
        manager.save()
    assert sample_setups_json.read_text("utf-8") == original
    assert [p for p in sample_setups_json.parent.iterdir() if ".tmp" in p.name] == []


def test_add_config_appends_and_persists(sample_setups_json):
    manager = LightSetupsManager(str(sample_setups_json))
    manager.add_config(_cfg("nova_cena"))
    names = [s["name"] for s in json.loads(sample_setups_json.read_text("utf-8"))["setups"]]
    assert "nova_cena" in names


def test_add_config_refuses_case_insensitive_duplicate(sample_setups_json):
    manager = LightSetupsManager(str(sample_setups_json))
    with pytest.raises(DuplicateConfigError):
        manager.add_config(_cfg("RELAX"))
    assert len(manager.configs) == 2


def test_add_config_rolls_back_on_save_failure(sample_setups_json, monkeypatch):
    _failing_write(monkeypatch)
    manager = LightSetupsManager(str(sample_setups_json))
    with pytest.raises(OSError):
        manager.add_config(_cfg("nova"))
    assert manager.get_config("nova") is None


def test_add_config_is_serialized_across_threads(sample_setups_json):
    manager = LightSetupsManager(str(sample_setups_json))
    errors: list[Exception] = []

    def worker():
        try:
            manager.add_config(_cfg("corrida"))
        except DuplicateConfigError as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert [c.name for c in manager.configs].count("corrida") == 1
    assert len(errors) == 7


def test_backup_json_writer_is_atomic(tmp_path, monkeypatch):
    import marvin_hue.atomic_io as aio
    from marvin_hue.services.backup import _write_json_file_with_bak

    target = tmp_path / "setups.json"
    target.write_text('{"setups": []}', encoding="utf-8")
    calls = []
    real = aio.os.replace
    monkeypatch.setattr(aio.os, "replace", lambda a, b: (calls.append(b), real(a, b)))
    _write_json_file_with_bak(target, {"setups": [1]})
    assert calls == [str(target)]
    assert json.loads(target.read_text("utf-8")) == {"setups": [1]}
    assert (tmp_path / "setups.json.bak").exists()


def _names_on_disk(path) -> list[str]:
    return [s["name"] for s in json.loads(path.read_text("utf-8"))["setups"]]


def test_remove_config_removes_and_persists(sample_setups_json):
    manager = LightSetupsManager(str(sample_setups_json))
    configs_ref = manager.configs
    assert manager.remove_config("relax") == 1
    assert manager.get_config("relax") is None
    assert configs_ref is manager.configs  # mesma lista (referências continuam válidas)
    assert _names_on_disk(sample_setups_json) == ["concentration"]


def test_remove_config_removes_every_exact_duplicate(sample_setups_json):
    manager = LightSetupsManager(str(sample_setups_json))
    manager.configs.append(_cfg("relax"))  # duplicata legada vinda do JSON
    manager.configs.append(_cfg("Relax"))  # outro nome (comparação exata)
    assert manager.remove_config("relax") == 2
    assert [c.name for c in manager.configs] == ["concentration", "Relax"]
    assert _names_on_disk(sample_setups_json) == ["concentration", "Relax"]


def test_remove_config_unknown_raises_and_keeps_file(sample_setups_json):
    original = sample_setups_json.read_text("utf-8")
    manager = LightSetupsManager(str(sample_setups_json))
    with pytest.raises(ConfigNotFoundError):
        manager.remove_config("RELAX")  # nome exato: maiúsculas não casam
    assert len(manager.configs) == 2
    assert sample_setups_json.read_text("utf-8") == original


def test_remove_config_restores_on_save_failure(sample_setups_json, monkeypatch):
    original = sample_setups_json.read_text("utf-8")
    manager = LightSetupsManager(str(sample_setups_json))
    ref = manager.configs
    before = list(manager.configs)
    _failing_write(monkeypatch)
    with pytest.raises(OSError):
        manager.remove_config("relax")
    assert ref is manager.configs  # rollback por slice: mesma lista
    assert manager.configs == before
    assert manager.get_config("relax") is not None
    assert sample_setups_json.read_text("utf-8") == original


def test_new_instance_after_remove_does_not_see_scene(sample_setups_json):
    """Cache de classe populado por outra instância não ressuscita a cena."""
    m1 = LightSetupsManager(str(sample_setups_json))
    m2 = LightSetupsManager(str(sample_setups_json))  # popula/usa o cache de classe
    assert m2.get_config("relax") is not None
    assert m1.remove_config("relax") == 1

    m3 = LightSetupsManager(str(sample_setups_json))
    assert m3.get_config("relax") is None
    assert [c.name for c in m3.configs] == ["concentration"]


# ----- nomes reservados (favorites/...) -----


@pytest.mark.parametrize("name", ["favorites/x", "Favorites/x", " favorites/", "FAVORITES/a/b"])
def test_add_config_refuses_reserved_prefix(sample_setups_json, name):
    original = sample_setups_json.read_text("utf-8")
    manager = LightSetupsManager(str(sample_setups_json))
    with pytest.raises(ReservedConfigNameError):
        manager.add_config(_cfg(name))
    assert len(manager.configs) == 2
    assert sample_setups_json.read_text("utf-8") == original


@pytest.mark.parametrize("name", ["favorites", "my favorites/x", "favoritos/x"])
def test_add_config_accepts_non_reserved_names(sample_setups_json, name):
    manager = LightSetupsManager(str(sample_setups_json))
    manager.add_config(_cfg(name))
    assert name in _names_on_disk(sample_setups_json)


# ----- update()/reload() sob lock -----


def test_update_keeps_list_identity_and_reflects_new_file(sample_setups_json):
    manager = LightSetupsManager(str(sample_setups_json))
    ref = manager.configs
    sample_setups_json.write_text(
        json.dumps({"setups": [{"name": "nova", "description": "", "settings": []}]}),
        encoding="utf-8",
    )
    LightSetupsManager._cache.pop(str(sample_setups_json), None)
    manager.reload()
    assert ref is manager.configs
    assert [c.name for c in manager.configs] == ["nova"]


def test_update_waits_for_lock_held_by_other_thread(sample_setups_json):
    manager = LightSetupsManager(str(sample_setups_json))
    manager._data = {"setups": [{"name": "nova", "description": "", "settings": []}]}
    held = threading.Event()
    release = threading.Event()

    def holder():
        with manager._lock:
            held.set()
            release.wait(5)

    a = threading.Thread(target=holder)
    a.start()
    assert held.wait(5)
    b = threading.Thread(target=manager.update)
    b.start()
    b.join(timeout=0.2)
    try:
        assert b.is_alive(), "update() deveria esperar o lock"
        assert [c.name for c in manager.configs] == ["concentration", "relax"]
    finally:
        release.set()
        a.join(5)
        b.join(5)
    assert [c.name for c in manager.configs] == ["nova"]
