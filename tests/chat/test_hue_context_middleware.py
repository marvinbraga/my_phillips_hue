from unittest.mock import MagicMock

import pytest


def test_context_injected_into_system_prompt(fake_controller, fake_manager):
    from marvin_hue.chat.middleware.hue_context import HueContextMiddleware

    mw = HueContextMiddleware(fake_controller, fake_manager, locations_path=None)

    captured = {}

    def handler(req):
        captured["prompt"] = req.system_message.content
        return "resp"

    req = MagicMock()
    req.system_prompt = "BASE"

    def _override(**kw):
        for k, v in kw.items():
            setattr(req, k, v)
        return req

    req.override.side_effect = _override

    mw.wrap_model_call(req, handler)
    assert "BASE" in captured["prompt"]
    assert "Fita Led" in captured["prompt"]  # status vivo
    assert "noite_relaxante" in captured["prompt"]  # preset


def test_status_block_is_cached(fake_controller, fake_manager):
    """O status é cacheado por TTL: várias chamadas de modelo no mesmo turno
    não martelam a bridge."""
    from marvin_hue.chat.middleware.hue_context import HueContextMiddleware

    mw = HueContextMiddleware(
        fake_controller, fake_manager, locations_path=None, status_ttl_s=60.0
    )

    def handler(req):
        return "resp"

    for _ in range(3):
        req = MagicMock()
        req.system_prompt = "BASE"
        req.override.side_effect = lambda **kw: req
        mw.wrap_model_call(req, handler)

    # 3 chamadas de modelo, mas só 1 leitura na bridge (cache TTL).
    assert fake_controller.get_lights_status.call_count == 1


@pytest.mark.asyncio
async def test_awrap_model_call_injects_context(fake_controller, fake_manager):
    """O caminho async injeta contexto e não bloqueia (offload via to_thread)."""
    from marvin_hue.chat.middleware.hue_context import HueContextMiddleware

    mw = HueContextMiddleware(fake_controller, fake_manager, locations_path=None)
    captured = {}

    async def handler(req):
        captured["prompt"] = req.system_message.content
        return "resp"

    req = MagicMock()
    req.system_prompt = "BASE"
    req.override.side_effect = lambda **kw: type("R", (), kw)()

    await mw.awrap_model_call(req, handler)
    assert "BASE" in captured["prompt"]
    assert "Fita Led" in captured["prompt"]


def test_status_block_degrades_on_bridge_error(fake_controller, fake_manager):
    """Se a bridge falhar, o bloco de status vira "" e o turno NÃO quebra."""
    from marvin_hue.chat.middleware.hue_context import HueContextMiddleware

    fake_controller.get_lights_status.side_effect = RuntimeError("bridge down")
    mw = HueContextMiddleware(fake_controller, fake_manager, locations_path=None)
    captured = {}

    def handler(req):
        captured["prompt"] = req.system_message.content
        return "resp"

    req = MagicMock()
    req.system_prompt = "BASE"
    req.override.side_effect = lambda **kw: type("R", (), kw)()

    mw.wrap_model_call(req, handler)  # não levanta
    assert "BASE" in captured["prompt"]
    assert "Fita Led" not in captured["prompt"]  # status ausente, mas turno vivo


def test_locations_block_prefers_registry_rows(fake_controller, fake_manager):
    """Registry snapshot is source of truth; JSON is fallback only."""
    from marvin_hue.chat.middleware.hue_context import HueContextMiddleware

    class _Row:
        name = "Fita Led"
        eye_safety_limit_pct = 25
        room = "escritorio"
        notes = "próxima aos olhos"

    mw = HueContextMiddleware(
        fake_controller,
        fake_manager,
        locations_path="/nao/existe.json",
        registry_rows=[_Row()],
    )
    captured = {}

    def handler(req):
        captured["prompt"] = req.system_message.content
        return "resp"

    req = MagicMock()
    req.system_prompt = "BASE"
    req.override.side_effect = lambda **kw: type("R", (), kw)()

    mw.wrap_model_call(req, handler)
    assert "Fita Led" in captured["prompt"]
    assert "25%" in captured["prompt"]


def test_locations_block_falls_back_to_json_when_registry_none(
    fake_controller, fake_manager, tmp_path
):
    loc = tmp_path / "locs.json"
    loc.write_text(
        '{"lights": [{"name": "Led cima", "max_brightness_percent": 25}]}',
        encoding="utf-8",
    )
    from marvin_hue.chat.middleware.hue_context import HueContextMiddleware

    mw = HueContextMiddleware(fake_controller, fake_manager, locations_path=str(loc))
    captured = {}

    def handler(req):
        captured["prompt"] = req.system_message.content
        return "resp"

    req = MagicMock()
    req.system_prompt = "BASE"
    req.override.side_effect = lambda **kw: type("R", (), kw)()

    mw.wrap_model_call(req, handler)
    assert "Led cima" in captured["prompt"]
    assert "25%" in captured["prompt"]


def test_registry_restrictions_skip_invalid_rows(fake_controller, fake_manager):
    from marvin_hue.chat.middleware.hue_context import HueContextMiddleware

    class _Blank:
        name = "  "
        eye_safety_limit_pct = 25

    class _NoLimit:
        name = "Lâmpada 1"
        eye_safety_limit_pct = None

    mw = HueContextMiddleware(
        fake_controller,
        fake_manager,
        locations_path=None,
        registry_rows=[_Blank(), _NoLimit()],
    )
    captured = {}

    def handler(req):
        captured["prompt"] = req.system_message.content
        return "resp"

    req = MagicMock()
    req.system_prompt = "BASE"
    req.override.side_effect = lambda **kw: type("R", (), kw)()

    mw.wrap_model_call(req, handler)
    assert "Restrições físicas" not in captured["prompt"]


def test_json_restrictions_block_degrades_on_bad_json(
    fake_controller, fake_manager, tmp_path
):
    loc = tmp_path / "bad.json"
    loc.write_text("{not json", encoding="utf-8")
    from marvin_hue.chat.middleware.hue_context import HueContextMiddleware

    mw = HueContextMiddleware(fake_controller, fake_manager, locations_path=str(loc))
    captured = {}

    def handler(req):
        captured["prompt"] = req.system_message.content
        return "resp"

    req = MagicMock()
    req.system_prompt = "BASE"
    req.override.side_effect = lambda **kw: type("R", (), kw)()

    mw.wrap_model_call(req, handler)
    assert "BASE" in captured["prompt"]
    assert "Restrições físicas" not in captured["prompt"]


def test_live_status_block_is_last_for_prompt_caching(
    fake_controller, fake_manager, tmp_path
):
    """Prefixo estático (base + restrições + presets) primeiro, status vivo por
    último: o prefixo fica byte-estável entre turnos e o cache de prompt acerta."""
    import json

    from marvin_hue.chat.middleware.hue_context import HueContextMiddleware

    locations = tmp_path / "locations.json"
    locations.write_text(
        json.dumps({"lights": [{"name": "Fita Led", "max_brightness_percent": 25}]}),
        encoding="utf-8",
    )
    mw = HueContextMiddleware(
        fake_controller, fake_manager, locations_path=str(locations), status_ttl_s=0.0
    )
    first = mw._augment("BASE")
    status = mw._status_block()
    assert status and first.endswith(status)
    assert first.startswith("BASE")
    assert first.index("Restrições físicas") < first.index("Status ATUAL")

    # Status muda entre turnos; o prefixo estático continua idêntico.
    fake_controller.get_lights_status.return_value = []
    second = mw._augment("BASE")
    prefix = first[: first.index("Status ATUAL")]
    assert second.startswith(prefix.rstrip())
