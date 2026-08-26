"""CLI: apply a lighting scene from JSON via LightSetupsManager."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import Final, Protocol

from marvin_hue.apply_result import ApplyResult
from marvin_hue.basics import LightConfig, LightSetupsManager

DEFAULT_SETUP_NAME: Final[str] = "concentration"


class EmptySetupsError(LookupError):
    """Raised when the setups catalog has no configurations."""

    def __init__(self) -> None:
        super().__init__("No lighting setups are available")


class UnknownSetupError(LookupError):
    """Raised when the requested setup name is not in the catalog."""

    def __init__(self, name: str, available: tuple[str, ...]) -> None:
        self.name = name
        self.available = available
        listed = ", ".join(available) if available else "(none)"
        super().__init__(f"Unknown setup {name!r}. Available: {listed}")


class LightConfigApplier(Protocol):
    def apply_light_config(
        self,
        light_config: LightConfig,
        transition_time_secs: float = 0,
    ) -> ApplyResult: ...


def parse_setup_name(argv: Sequence[str]) -> str | None:
    if len(argv) < 2:
        return None
    return argv[1]


def resolve_config(manager: LightSetupsManager, name: str | None) -> LightConfig:
    configs = manager.configs
    if not configs:
        raise EmptySetupsError()

    if name is None or name == "":
        default = manager.get_config(DEFAULT_SETUP_NAME)
        if default is not None:
            return default
        return configs[0]

    found = manager.get_config(name)
    if found is None:
        available = tuple(cfg.name for cfg in configs)
        raise UnknownSetupError(name, available)
    return found


def apply_setup(
    manager: LightSetupsManager,
    controller: LightConfigApplier,
    name: str | None = None,
    *,
    transition_time_secs: float = 0,
) -> ApplyResult:
    config = resolve_config(manager, name)
    return controller.apply_light_config(config, transition_time_secs)


def format_apply_result(result: ApplyResult) -> str:
    applied = ", ".join(result.applied) if result.applied else "(none)"
    if result.failed:
        failed = "; ".join(f"{light}: {error}" for light, error in result.failed)
    else:
        failed = "(none)"
    return f"Applied: {applied}\nFailed: {failed}"


def main(argv: Sequence[str] | None = None) -> int:
    from dotenv import load_dotenv

    load_dotenv()

    from marvin_hue.config import settings
    from marvin_hue.controllers import HueController

    args = sys.argv if argv is None else argv
    setup_name = parse_setup_name(args)
    manager = LightSetupsManager(settings.setups_file)
    controller = HueController(ip_address=settings.bridge_ip)
    try:
        result = apply_setup(manager, controller, setup_name)
    except (EmptySetupsError, UnknownSetupError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(format_apply_result(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
