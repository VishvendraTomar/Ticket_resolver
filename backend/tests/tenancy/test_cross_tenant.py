"""Cross-tenant access tests for every /v1 route.

Every route must have a case in CASES. A new route without one fails
``test_every_route_has_a_cross_tenant_case`` — that's the point.

Each case acts as Alice (owner of A only) and tries to reach Workspace B, then
checks from Bob's side that nothing in B changed.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from fastapi.routing import iter_route_contexts
from httpx import AsyncClient

from app.main import create_app
from tests.conftest import World, new_person, sign_in

Case = Callable[[AsyncClient, World], Awaitable[None]]


async def _b_members(client: AsyncClient, w: World) -> list[dict[str, object]]:
    r = await client.get(f"/v1/workspaces/{w.ws_b}/members", headers=w.bob.headers)
    assert r.status_code == 200
    members: list[dict[str, object]] = r.json()
    return members


async def case_get_me(client: AsyncClient, w: World) -> None:
    body = (await client.get("/v1/me", headers=w.alice.headers)).json()
    ids = {ws["id"] for ws in body["workspaces"]}
    assert ids == {w.ws_a}


async def case_create_workspace(client: AsyncClient, w: World) -> None:
    r = await client.post("/v1/workspaces", json={"name": "Alice 2"}, headers=w.alice.headers)
    assert r.status_code == 201
    new_id = r.json()["id"]
    assert (await client.get(f"/v1/workspaces/{new_id}", headers=w.bob.headers)).status_code == 404
    bob_ws = {
        ws["id"] for ws in (await client.get("/v1/me", headers=w.bob.headers)).json()["workspaces"]
    }
    assert new_id not in bob_ws


async def case_get_workspace(client: AsyncClient, w: World) -> None:
    r = await client.get(f"/v1/workspaces/{w.ws_b}", headers=w.alice.headers)
    assert r.status_code == 404


async def case_list_members(client: AsyncClient, w: World) -> None:
    r = await client.get(f"/v1/workspaces/{w.ws_b}/members", headers=w.alice.headers)
    assert r.status_code == 404
    # Within A, B's people never appear.
    a_members = (
        await client.get(f"/v1/workspaces/{w.ws_a}/members", headers=w.alice.headers)
    ).json()
    assert {m["user"]["email"] for m in a_members} == {w.alice.email}


async def case_add_member(client: AsyncClient, w: World) -> None:
    before = await _b_members(client, w)
    r = await client.post(
        f"/v1/workspaces/{w.ws_b}/members",
        json={"email": w.alice.email, "role": "owner"},
        headers=w.alice.headers,
    )
    assert r.status_code == 404
    assert await _b_members(client, w) == before


async def case_change_member_role(client: AsyncClient, w: World) -> None:
    body = {"role": "admin"}
    # B's membership id through B's path, and smuggled through A's path.
    for path in (
        f"/v1/workspaces/{w.ws_b}/members/{w.carol_membership_b}",
        f"/v1/workspaces/{w.ws_a}/members/{w.carol_membership_b}",
    ):
        r = await client.patch(path, json=body, headers=w.alice.headers)
        assert r.status_code == 404, path
    carol = next(m for m in await _b_members(client, w) if m["id"] == w.carol_membership_b)
    assert carol["role"] == "agent"


async def case_remove_member(client: AsyncClient, w: World) -> None:
    for path in (
        f"/v1/workspaces/{w.ws_b}/members/{w.carol_membership_b}",
        f"/v1/workspaces/{w.ws_a}/members/{w.carol_membership_b}",
    ):
        r = await client.delete(path, headers=w.alice.headers)
        assert r.status_code == 404, path
    assert any(m["id"] == w.carol_membership_b for m in await _b_members(client, w))


CASES: dict[tuple[str, str], Case] = {
    ("GET", "/v1/me"): case_get_me,
    ("POST", "/v1/workspaces"): case_create_workspace,
    ("GET", "/v1/workspaces/{workspace_id}"): case_get_workspace,
    ("GET", "/v1/workspaces/{workspace_id}/members"): case_list_members,
    ("POST", "/v1/workspaces/{workspace_id}/members"): case_add_member,
    ("PATCH", "/v1/workspaces/{workspace_id}/members/{membership_id}"): case_change_member_role,
    ("DELETE", "/v1/workspaces/{workspace_id}/members/{membership_id}"): case_remove_member,
}


# Routes outside /v1 that carry no tenant data. Anything else outside /v1 fails.
NON_TENANT_ROUTES = {"/healthz", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def _all_routes() -> set[tuple[str, str]]:
    """Every (method, path), flattened through included routers."""
    routes: set[tuple[str, str]] = set()
    for ctx in iter_route_contexts(create_app().routes):
        methods = getattr(ctx, "methods", None) or {"*"}
        for method in methods - {"HEAD"}:
            routes.add((method, str(ctx.path)))
    return routes


def _v1_routes() -> set[tuple[str, str]]:
    return {r for r in _all_routes() if r[1].startswith("/v1")}


def test_route_enumeration_sees_included_routers() -> None:
    """Guard the guard: if enumeration silently finds nothing, coverage would pass vacuously."""
    assert ("GET", "/v1/me") in _v1_routes()


def test_no_unexpected_routes_outside_v1() -> None:
    outside = {path for _, path in _all_routes() if not path.startswith("/v1")}
    assert outside <= NON_TENANT_ROUTES, f"Unreviewed routes: {outside - NON_TENANT_ROUTES}"


def test_every_route_has_a_cross_tenant_case() -> None:
    missing = sorted(_v1_routes() - set(CASES))
    assert not missing, f"Routes without a cross-tenant case: {missing}"
    stale = sorted(set(CASES) - _v1_routes())
    assert not stale, f"Cases for routes that no longer exist: {stale}"


@pytest.mark.db
@pytest.mark.parametrize("route", sorted(CASES), ids=lambda r: f"{r[0]} {r[1]}")
async def test_cross_tenant(client: AsyncClient, world: World, route: tuple[str, str]) -> None:
    await CASES[route](client, world)


@pytest.mark.db
async def test_outsider_sees_no_workspaces(client: AsyncClient, world: World) -> None:
    eve = new_person("eve")
    body = await sign_in(client, eve)
    assert body["workspaces"] == []
    for ws in (world.ws_a, world.ws_b):
        r = await client.get(f"/v1/workspaces/{ws}", headers=eve.headers)
        assert r.status_code == 404
