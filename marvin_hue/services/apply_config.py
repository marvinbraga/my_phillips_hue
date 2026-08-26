"""Named LightConfig apply use case (HTTP /apply, groups, schedules).

Focused application service — not a Facade. Callers compose this with their
own ports (manager, Hue, optional scene history).
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from marvin_hue.apply_result import ApplyResult
from marvin_hue.basics import LightConfig
from marvin_hue.logging_config import get_logger

logger = get_logger("services.apply_config")


class ApplyConfigNotFoundError(LookupError):
    """Named LightConfig does not exist in the setups catalog."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Configuração '{name}' não encontrada")


class LightConfigLookup(Protocol):
    """Port: resolve a named LightConfig (LightSetupsManager structurally)."""

    def get_config(self, name: str) -> LightConfig | None: ...


class HueApplyPort(Protocol):
    """Port: apply a LightConfig on the Hue bridge (sync; offloaded)."""

    def apply_light_config(
        self, light_config: LightConfig, transition_time_secs: float = 0
    ) -> object: ...


class SceneSnapshotPort(Protocol):
    """Port: fail-open snapshot before apply (SceneHistoryService)."""

    async def snapshot(
        self,
        hue: Any,
        *,
        source: str,
        label: str | None = None,
    ) -> object: ...


def _filter_config(config: LightConfig, light_names: set[str] | None) -> LightConfig:
    if light_names is None:
        return config
    settings = [s for s in config.settings if s.light_name in light_names]
    return LightConfig(
        name=config.name,
        settings=settings,
        description=config.description,
    )


class ApplyConfigService:
    """Load a named scene, optional fail-open snapshot, apply via Hue."""

    def __init__(
        self,
        manager: LightConfigLookup,
        hue: HueApplyPort,
        history: SceneSnapshotPort | None = None,
    ) -> None:
        self._manager = manager
        self._hue = hue
        self._history = history

    async def apply(
        self,
        name: str,
        *,
        transition_time: float = 0,
        source: str = "apply",
        light_names: set[str] | None = None,
    ) -> ApplyResult:
        config = self._manager.get_config(name)
        if config is None:
            raise ApplyConfigNotFoundError(name)

        await self._snapshot_fail_open(name, source)
        to_apply = _filter_config(config, light_names)
        raw = await asyncio.to_thread(
            self._hue.apply_light_config, to_apply, transition_time
        )
        if isinstance(raw, ApplyResult):
            logger.info(
                f"Apply '{name}' source={source!r} "
                f"applied={len(raw.applied)} failed={len(raw.failed)}"
            )
            return raw
        logger.info(f"Apply '{name}' source={source!r}")
        return ApplyResult(applied=(), failed=())

    async def _snapshot_fail_open(self, name: str, source: str) -> None:
        if self._history is None:
            return
        try:
            await self._history.snapshot(
                self._hue,
                source=source,
                label=f"before apply {name}",
            )
        except Exception as snap_exc:  # noqa: BLE001 — fail-open: still apply
            logger.warning(f"Scene snapshot before apply failed: {snap_exc}")
