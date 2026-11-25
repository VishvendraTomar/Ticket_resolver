"""RLS behaviour, exercised with raw SQL as app_user (no API, no app-layer filters)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from tests.conftest import World

pytestmark = pytest.mark.db

TENANT_TABLES = ("workspaces", "memberships", "audit_events", "users")


async def _set_workspace(conn: AsyncConnection, workspace_id: str) -> None:
    await conn.execute(
        text("SELECT set_config('app.workspace_id', :ws, true)"), {"ws": workspace_id}
    )


async def _count(conn: AsyncConnection, table: str, where: str = "true", **params: str) -> int:
    value = await conn.scalar(text(f"SELECT count(*) FROM {table} WHERE {where}"), params)  # noqa: S608
    return int(value or 0)


async def test_no_context_sees_nothing(app_engine: AsyncEngine, world: World) -> None:
    async with app_engine.connect() as conn:
        for table in TENANT_TABLES:
            assert await _count(conn, table) == 0, f"{table} visible without context"


async def test_app_role_sees_only_current_workspace(app_engine: AsyncEngine, world: World) -> None:
    async with app_engine.begin() as conn:
        await _set_workspace(conn, world.ws_a)
        # Even asking explicitly for B's rows returns nothing.
        assert await _count(conn, "workspaces", "id = :b", b=world.ws_b) == 0
        assert await _count(conn, "memberships", "workspace_id = :b", b=world.ws_b) == 0
        assert await _count(conn, "audit_events", "workspace_id = :b", b=world.ws_b) == 0
        # And everything visible belongs to A.
        assert await _count(conn, "memberships", "workspace_id <> :a", a=world.ws_a) == 0
        assert await _count(conn, "audit_events", "workspace_id <> :a", a=world.ws_a) == 0
        assert await _count(conn, "memberships") >= 1
        # Users of B (bob, carol) are not visible from A.
        assert await _count(conn, "users", "email = :e", e=world.carol.email) == 0


async def test_context_does_not_survive_transaction(app_engine: AsyncEngine, world: World) -> None:
    async with app_engine.connect() as conn:
        async with conn.begin():
            await _set_workspace(conn, world.ws_a)
            assert await _count(conn, "memberships") >= 1
        # Same connection, new transaction: the setting is gone.
        async with conn.begin():
            assert await _count(conn, "memberships") == 0


async def test_cannot_insert_into_other_workspace(app_engine: AsyncEngine, world: World) -> None:
    async with app_engine.connect() as conn:
        await conn.begin()
        await _set_workspace(conn, world.ws_a)
        with pytest.raises(DBAPIError, match="row-level security"):
            await conn.execute(
                text("""
                    INSERT INTO audit_events (id, workspace_id, action, target_type)
                    VALUES (:id, :ws, 'test.forged', 'test')
                """),
                {"id": str(uuid.uuid4()), "ws": world.ws_b},
            )
        await conn.rollback()


async def test_cannot_move_a_row_to_another_workspace(
    app_engine: AsyncEngine, world: World
) -> None:
    async with app_engine.connect() as conn:
        await conn.begin()
        await _set_workspace(conn, world.ws_a)
        with pytest.raises(DBAPIError, match="row-level security"):
            await conn.execute(
                text("UPDATE memberships SET workspace_id = :b WHERE id = :m"),
                {"b": world.ws_b, "m": world.alice_membership_a},
            )
        await conn.rollback()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_events SET action = 'tampered'",
        "DELETE FROM audit_events",
        "TRUNCATE audit_events",
    ],
)
async def test_audit_events_are_append_only(
    app_engine: AsyncEngine, world: World, statement: str
) -> None:
    async with app_engine.connect() as conn:
        await conn.begin()
        await _set_workspace(conn, world.ws_a)
        with pytest.raises(DBAPIError, match="permission denied"):
            await conn.execute(text(statement))
        await conn.rollback()


async def test_audit_trigger_blocks_even_the_owner(owner_engine: AsyncEngine) -> None:
    """TRUNCATE ignores RLS, so the trigger is the last line of defence for privileged roles."""
    async with owner_engine.connect() as conn:
        await conn.begin()
        try:
            with pytest.raises(DBAPIError, match="append-only"):
                await conn.execute(text("TRUNCATE audit_events"))
        finally:
            await conn.rollback()
