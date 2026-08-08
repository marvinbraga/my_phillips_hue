"""Runtime eye-safety / enabled_for_app policy overlay tests."""

from marvin_hue import eye_safety as es


def setup_function() -> None:
    es.clear_runtime_policy()


def teardown_function() -> None:
    es.clear_runtime_policy()


def test_fallback_hardcoded_when_no_runtime() -> None:
    assert es.eye_safety_limit_pct("Fita Led") == 25
    assert es.eye_safety_limit_pct("Lâmpada 1") is None


def test_runtime_overrides_and_adds_limits() -> None:
    es.set_runtime_policy(
        limits_pct={"Fita Led": 10, "Hue Iris": 40},
        disabled_names=set(),
    )
    assert es.eye_safety_limit_pct("Fita Led") == 10
    assert es.eye_safety_limit_pct("Hue Iris") == 40
    assert es.clamp_eye_safety("Fita Led", 100, scale="pct") == 10
    assert es.clamp_eye_safety("Fita Led", 254, scale="hue") == int((10 / 100) * 254)


def test_runtime_none_limit_falls_back_to_hardcoded() -> None:
    # name present with None → fall back to hardcoded if any
    es.set_runtime_policy(limits_pct={"Fita Led": None}, disabled_names=set())
    assert es.eye_safety_limit_pct("Fita Led") == 25


def test_enabled_for_app_defaults_true() -> None:
    assert es.is_enabled_for_app("anything") is True
    es.set_runtime_policy(limits_pct={}, disabled_names={"Hue Play 1"})
    assert es.is_enabled_for_app("Hue Play 1") is False
    assert es.is_enabled_for_app("Hue Play 2") is True


def test_clear_runtime_policy_restores_defaults() -> None:
    es.set_runtime_policy(limits_pct={"X": 5}, disabled_names={"Y"})
    es.clear_runtime_policy()
    assert es.eye_safety_limit_pct("X") is None
    assert es.is_enabled_for_app("Y") is True
