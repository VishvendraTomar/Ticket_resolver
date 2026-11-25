"""Alembic runs as the owner role (DATABASE_URL), never as app_user."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection

from app.core.config import get_settings
from app.core.db import make_engine
from app.core.models import Base
from app.tenancy import models as _tenancy_models  # noqa: F401  (registers tables)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _do_run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    url = get_settings().database_url
    if url is None:
        raise RuntimeError("DATABASE_URL (owner role) is required to run migrations")
    engine = make_engine(url.get_secret_value())
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_do_run)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Offline migrations are not supported; run against a database.")

asyncio.run(_run_async())
