"""Run migrations programmatically (used by the CLI, the API on startup, and tests)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from aios.config import get_settings
from aios.db.base import get_engine

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


def alembic_config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def upgrade(url: str | None = None) -> None:
    url = url or get_settings().database_url
    cfg = alembic_config(url)
    engine = get_engine(url)
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
