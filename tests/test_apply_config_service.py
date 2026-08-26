"""ApplyConfigService: shared apply use case (HTTP / groups / schedules)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from marvin_hue.apply_result import ApplyResult
from marvin_hue.basics import LightConfig, LightSetting
from marvin_hue.colors import Color
from marvin_hue.services.apply_config import (
    ApplyConfigNotFoundError,
    ApplyConfigService,
)


def _scene() -> LightConfig:
    return LightConfig(
        name="concentration",
        settings=[
            LightSetting("Lâmpada 1", Color(255, 0, 0, 200)),
            LightSetting("Hue Iris", Color(0, 255, 0, 200)),
            LightSetting("Fita Led", Color(0, 0, 255, 50)),
        ],
        description="test",
    )


def _build(
    *,
    config: LightConfig | None = None,
    history: bool = True,
    snapshot_error: BaseException | None = None,
    apply_result: ApplyResult | None = None,
) -> tuple[ApplyConfigService, MagicMock, MagicMock, MagicMock | None, LightConfig]:
    cfg = config or _scene()
    manager = MagicMock()
    manager.get_config.side_effect = lambda n: cfg if n == cfg.name else None
    hue = MagicMock()
    hue.apply_light_config.return_value = apply_result or ApplyResult(
        applied=("Lâmpada 1", "Hue Iris", "Fita Led"),
        failed=(),
    )
    hist: MagicMock | None = None
    if history:
        hist = MagicMock()
        if snapshot_error is not None:
            hist.snapshot = AsyncMock(side_effect=snapshot_error)
        else:
            hist.snapshot = AsyncMock()
    return ApplyConfigService(manager, hue, hist), manager, hue, hist, cfg


@pytest.mark.asyncio
async def test_apply_looks_up_config_snapshots_and_applies() -> None:
    svc, manager, hue, hist, cfg = _build()
    result = await svc.apply("concentration", transition_time=1.5, source="apply")

    manager.get_config.assert_called_once_with("concentration")
    assert hist is not None
    hist.snapshot.assert_awaited_once()
    snap_kwargs = hist.snapshot.await_args.kwargs
    assert snap_kwargs["source"] == "apply"
    assert "concentration" in str(snap_kwargs.get("label") or "")
    hue.apply_light_config.assert_called_once()
    applied_cfg = hue.apply_light_config.call_args[0][0]
    assert applied_cfg.name == cfg.name
    assert [s.light_name for s in applied_cfg.settings] == [
        "Lâmpada 1",
        "Hue Iris",
        "Fita Led",
    ]
    assert hue.apply_light_config.call_args[0][1] == 1.5
    assert result.ok
    assert result.applied == ("Lâmpada 1", "Hue Iris", "Fita Led")


@pytest.mark.asyncio
async def test_apply_missing_config_raises() -> None:
    svc, manager, hue, hist, _ = _build()
    with pytest.raises(ApplyConfigNotFoundError, match="ghost"):
        await svc.apply("ghost")
    manager.get_config.assert_called_once_with("ghost")
    hue.apply_light_config.assert_not_called()
    assert hist is not None
    hist.snapshot.assert_not_awaited()


@pytest.mark.asyncio
async def test_apply_filters_settings_by_light_names() -> None:
    svc, _, hue, _, _ = _build()
    await svc.apply(
        "concentration",
        light_names={"Lâmpada 1", "Fita Led"},
        source="group",
    )
    applied_cfg = hue.apply_light_config.call_args[0][0]
    assert [s.light_name for s in applied_cfg.settings] == ["Lâmpada 1", "Fita Led"]


@pytest.mark.asyncio
async def test_apply_empty_light_names_yields_empty_settings() -> None:
    svc, _, hue, _, _ = _build(
        apply_result=ApplyResult(applied=(), failed=()),
    )
    result = await svc.apply("concentration", light_names=set())
    applied_cfg = hue.apply_light_config.call_args[0][0]
    assert applied_cfg.settings == []
    assert result.applied == ()
    assert result.failed == ()


@pytest.mark.asyncio
async def test_snapshot_fail_open_still_applies() -> None:
    svc, _, hue, hist, _ = _build(snapshot_error=RuntimeError("db down"))
    result = await svc.apply("concentration", source="apply")
    assert hist is not None
    hist.snapshot.assert_awaited_once()
    hue.apply_light_config.assert_called_once()
    assert result.ok


@pytest.mark.asyncio
async def test_history_none_skips_snapshot() -> None:
    svc, _, hue, hist, _ = _build(history=False)
    await svc.apply("concentration")
    assert hist is None
    hue.apply_light_config.assert_called_once()


@pytest.mark.asyncio
async def test_apply_returns_partial_apply_result() -> None:
    partial = ApplyResult(
        applied=("Lâmpada 1",),
        failed=(("Hue Iris", "timeout"),),
    )
    svc, _, _, _, _ = _build(apply_result=partial)
    result = await svc.apply("concentration")
    assert result.partial
    assert result.applied == ("Lâmpada 1",)
    assert result.failed == (("Hue Iris", "timeout"),)


@pytest.mark.asyncio
async def test_non_apply_result_from_hue_returns_empty_result() -> None:
    svc, _, hue, _, _ = _build()
    hue.apply_light_config.return_value = object()
    result = await svc.apply("concentration")
    assert result == ApplyResult(applied=(), failed=())
    hue.apply_light_config.assert_called_once()


@pytest.mark.asyncio
async def test_does_not_mutate_original_config_when_filtering() -> None:
    cfg = _scene()
    original_names = [s.light_name for s in cfg.settings]
    svc, _, _, _, _ = _build(config=cfg)
    await svc.apply("concentration", light_names={"Hue Iris"})
    assert [s.light_name for s in cfg.settings] == original_names
