"""Persistence adapters (SQLite)."""

from marvin_hue.persistence.schema import CURRENT_SCHEMA_VERSION, init_db

__all__ = ["CURRENT_SCHEMA_VERSION", "init_db"]
