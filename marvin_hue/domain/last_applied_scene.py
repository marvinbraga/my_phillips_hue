"""Last applied scene: the single-row record behind the Controle badge."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class LastAppliedScene:
    """Latest scene applied with at least one light written.

    ``config_name`` is ``None`` once the lights left that scene (lights off or
    undo); ``source`` then names what cleared it.
    """

    config_name: str | None
    source: str
    applied_at: datetime
