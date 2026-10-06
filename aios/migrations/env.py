"""Alembic environment. The URL comes from AIOS settings (or -x url=...)."""

from alembic import context
from sqlalchemy import engine_from_config, pool

from aios.config import get_settings
from aios.db import models  # noqa: F401  (registers tables)
from aios.db.base import Base

config = context.config
url = context.get_x_argument(as_dictionary=True).get("url") or config.get_main_option("sqlalchemy.url") or get_settings().database_url
target_metadata = Base.metadata


def run_offline() -> None:
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    connectable = config.attributes.get("connection")
    if connectable is not None:
        context.configure(connection=connectable, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = engine_from_config({"sqlalchemy.url": url}, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
