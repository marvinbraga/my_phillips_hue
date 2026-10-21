"""Room helpers públicos (chat/tools/rooms.py): normalização e casamento por token."""
from __future__ import annotations

ROOMS = {
    "Teto, à direita": ["Lâmpada 1", "Lâmpada 2"],
    "Teto, à esquerda": ["Lâmpada 3", "Lâmpada 4"],
    "Frente, parte de baixo do monitor": ["Fita Led"],
    "À direita, um pouco atrás do usuário": ["Hue Iris"],
}


def test_match_rooms_exact_wins():
    from marvin_hue.chat.tools.rooms import match_rooms

    assert match_rooms(ROOMS, "teto, À DIREITA") == ["Teto, à direita"]


def test_match_rooms_token_prefix_returns_all_candidates():
    from marvin_hue.chat.tools.rooms import match_rooms

    assert match_rooms(ROOMS, "teto") == ["Teto, à direita", "Teto, à esquerda"]
    assert match_rooms(ROOMS, "monitor") == ["Frente, parte de baixo do monitor"]
    assert match_rooms(ROOMS, "teto esq") == ["Teto, à esquerda"]


def test_match_rooms_accent_insensitive():
    from marvin_hue.chat.tools.rooms import match_rooms

    assert match_rooms(ROOMS, "a direita um pouco") == [
        "À direita, um pouco atrás do usuário"
    ]


def test_match_rooms_none():
    from marvin_hue.chat.tools.rooms import match_rooms

    assert match_rooms(ROOMS, "cozinha") == []
    assert match_rooms(ROOMS, "  ") == []


def test_resolve_room_lights_union_and_label():
    from marvin_hue.chat.tools.rooms import resolve_room_lights

    label, names = resolve_room_lights(ROOMS, "teto")
    assert names == ["Lâmpada 1", "Lâmpada 2", "Lâmpada 3", "Lâmpada 4"]
    assert label == "salas 'Teto, à direita', 'Teto, à esquerda'"
    assert resolve_room_lights(ROOMS, "cozinha") is None


def test_normalize_room_index_is_idempotent(tmp_path):
    from marvin_hue.chat.tools.rooms import RegistryRoomIndex, normalize_room_index

    path = tmp_path / "loc.json"
    path.write_text('{"lights": [{"name": "L1", "location": "Teto"}]}', encoding="utf-8")
    once = normalize_room_index(None, str(path))
    assert isinstance(once, RegistryRoomIndex)
    assert dict(once) == {"Teto": ["L1"]}
    assert once.locations is None  # JSON fallback: get_light_locations lê o JSON
    assert normalize_room_index(once, str(path)) is once


def test_set_room_power_teto_turns_on_both_ceiling_rooms(fake_controller):
    from marvin_hue.chat.tools.light_tools import build_light_tools

    fake_controller.turn_on.return_value = True
    tools = {t.name: t for t in build_light_tools(fake_controller, None, room_index=ROOMS)}
    out = tools["set_room_power"].invoke({"room": "teto", "on": True})
    called = [c.args[0] for c in fake_controller.turn_on.call_args_list]
    assert called == ["Lâmpada 1", "Lâmpada 2", "Lâmpada 3", "Lâmpada 4"]
    assert out == (
        "Salas 'Teto, à direita', 'Teto, à esquerda': 4 lâmpada(s) ligadas."
    )


def test_set_room_brightness_unknown_room_lists_rooms(fake_controller):
    from marvin_hue.chat.tools.light_tools import build_light_tools

    tools = {t.name: t for t in build_light_tools(fake_controller, None, room_index=ROOMS)}
    out = tools["set_room_brightness"].invoke({"room": "cozinha", "brightness": 50})
    assert out.startswith("Sala 'cozinha' não encontrada. Salas: ")
    fake_controller.set_brightness.assert_not_called()


def test_list_lights_by_room_prefix(fake_controller):
    from marvin_hue.chat.tools.light_tools import build_light_tools

    tools = {t.name: t for t in build_light_tools(fake_controller, None, room_index=ROOMS)}
    out = tools["list_lights_by_room"].invoke({"room": "teto"})
    assert "Lâmpada 1" in out and "Lâmpada 4" in out and "Fita Led" not in out
