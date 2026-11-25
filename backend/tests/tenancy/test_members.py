"""Member management rules within one workspace."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import World, add_member, new_person, sign_in

pytestmark = pytest.mark.db


async def test_unauthenticated_is_401(client: AsyncClient) -> None:
    assert (await client.get("/v1/me")).status_code == 401
    r = await client.get("/v1/me", headers={"Authorization": "Bearer not-a-token"})
    assert r.status_code == 401


async def test_cannot_remove_last_owner(client: AsyncClient, world: World) -> None:
    path = f"/v1/workspaces/{world.ws_a}/members/{world.alice_membership_a}"
    r = await client.delete(path, headers=world.alice.headers)
    assert r.status_code == 409
    r = await client.patch(path, json={"role": "admin"}, headers=world.alice.headers)
    assert r.status_code == 409


async def test_second_owner_allows_demotion(client: AsyncClient, world: World) -> None:
    dave = new_person("dave")
    await sign_in(client, dave)
    await add_member(client, world.alice, world.ws_a, dave, "owner")
    path = f"/v1/workspaces/{world.ws_a}/members/{world.alice_membership_a}"
    r = await client.patch(path, json={"role": "admin"}, headers=world.alice.headers)
    assert r.status_code == 200
    assert r.json()["role"] == "admin"


async def test_non_manager_cannot_manage(client: AsyncClient, world: World) -> None:
    # Carol is an agent in B.
    r = await client.post(
        f"/v1/workspaces/{world.ws_b}/members",
        json={"email": world.alice.email, "role": "viewer"},
        headers=world.carol.headers,
    )
    assert r.status_code == 403


async def test_admin_cannot_grant_or_touch_owner(client: AsyncClient, world: World) -> None:
    erin, frank = new_person("erin"), new_person("frank")
    for p in (erin, frank):
        await sign_in(client, p)
    await add_member(client, world.bob, world.ws_b, erin, "admin")

    r = await client.post(
        f"/v1/workspaces/{world.ws_b}/members",
        json={"email": frank.email, "role": "owner"},
        headers=erin.headers,
    )
    assert r.status_code == 403

    bob_membership = next(
        m["id"]
        for m in (
            await client.get(f"/v1/workspaces/{world.ws_b}/members", headers=erin.headers)
        ).json()
        if m["role"] == "owner"
    )
    r = await client.delete(
        f"/v1/workspaces/{world.ws_b}/members/{bob_membership}", headers=erin.headers
    )
    assert r.status_code == 403


async def test_duplicate_and_unknown_member(client: AsyncClient, world: World) -> None:
    r = await client.post(
        f"/v1/workspaces/{world.ws_b}/members",
        json={"email": world.carol.email, "role": "viewer"},
        headers=world.bob.headers,
    )
    assert r.status_code == 409
    r = await client.post(
        f"/v1/workspaces/{world.ws_b}/members",
        json={"email": "nobody-signed-in@example.com", "role": "viewer"},
        headers=world.bob.headers,
    )
    assert r.status_code == 404


async def test_member_changes_are_audited(
    client: AsyncClient, world: World, app_engine: AsyncEngine
) -> None:
    path = f"/v1/workspaces/{world.ws_b}/members/{world.carol_membership_b}"
    assert (
        await client.patch(path, json={"role": "viewer"}, headers=world.bob.headers)
    ).status_code == 200
    assert (await client.delete(path, headers=world.bob.headers)).status_code == 204

    async with app_engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.workspace_id', :ws, true)"), {"ws": world.ws_b}
        )
        actions = (
            (
                await conn.execute(
                    text(
                        "SELECT action FROM audit_events WHERE workspace_id = :ws "
                        "ORDER BY created_at, action"
                    ),
                    {"ws": world.ws_b},
                )
            )
            .scalars()
            .all()
        )
    assert actions[0] == "workspace.created"
    assert {"member.added", "member.role_changed", "member.removed"} <= set(actions)
