from unittest.mock import MagicMock


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
    assert "Fita Led" in captured["prompt"]            # status vivo
    assert "noite_relaxante" in captured["prompt"]      # preset


def test_status_block_is_cached(fake_controller, fake_manager):
    """O status é cacheado por TTL: várias chamadas de modelo no mesmo turno
    não martelam a bridge."""
    from marvin_hue.chat.middleware.hue_context import HueContextMiddleware

    mw = HueContextMiddleware(fake_controller, fake_manager, locations_path=None, status_ttl_s=60.0)

    def handler(req):
        return "resp"

    for _ in range(3):
        req = MagicMock()
        req.system_prompt = "BASE"
        req.override.side_effect = lambda **kw: req
        mw.wrap_model_call(req, handler)

    # 3 chamadas de modelo, mas só 1 leitura na bridge (cache TTL).
    assert fake_controller.get_lights_status.call_count == 1
