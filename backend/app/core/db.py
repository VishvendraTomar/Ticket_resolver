"""Database engine, sessions and the per-transaction tenant context.

The app always connects as ``app_user`` (NOBYPASSRLS). Row-Level Security reads
three transaction-local settings, set with ``set_config(..., is_local => true)``
so they disappear when the transaction ends and can't leak through the pool:

- ``app.auth_subject`` — the verified identity-provider subject (lets a user find
  and create their own ``users`` row on first sign-in)
- ``app.user_id``      — our ``users.id`` for the caller
- ``app.workspace_id`` — the workspace the request acts in (set only after the
  membership check in ``tenancy.deps``)

Unset values read as NULL in the policies, so a missing context fails closed.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings, to_asyncpg_url


def make_engine(raw_url: str) -> AsyncEngine:
    target = to_asyncpg_url(raw_url)
    return create_async_engine(
        target.url,
        connect_args=target.connect_args,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
    )


@lru_cache
def get_engine() -> AsyncEngine:
    url = get_settings().app_database_url
    if url is None:
        raise RuntimeError("APP_DATABASE_URL is not set")
    return make_engine(url.get_secret_value())


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request.

    Handlers that write call ``await session.commit()`` explicitly; anything
    uncommitted is rolled back when the request ends.
    """
    async with get_sessionmaker()() as session:
        yield session


async def set_context(
    session: AsyncSession,
    *,
    auth_subject: str | None = None,
    user_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
) -> None:
    """Set the RLS context for the current transaction. ``None`` leaves a value unchanged."""
    values = {
        "app.auth_subject": auth_subject,
        "app.user_id": str(user_id) if user_id else None,
        "app.workspace_id": str(workspace_id) if workspace_id else None,
    }
    for key, value in values.items():
        if value is not None:
            await session.execute(
                text("SELECT set_config(:key, :value, true)"), {"key": key, "value": value}
            )
