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


# --- Knowledge base (M2) -----------------------------------------------------------------


async def _b_document(client: AsyncClient, w: World) -> tuple[str, str]:
    """A document in B (as Bob), parsed and awaiting review. Returns (document_id, version_id)."""
    from tests.knowledge.helpers import upload

    doc = await upload(client, w.bob, w.ws_b, title="B secret policy")
    return doc["id"], doc["versions"][0]["id"]


async def _b_get(client: AsyncClient, w: World, path: str) -> object:
    r = await client.get(f"/v1/workspaces/{w.ws_b}{path}", headers=w.bob.headers)
    assert r.status_code == 200, r.text
    return r.json()


async def _alice_404(client: AsyncClient, method: str, paths: list[str], **kw: object) -> None:
    for path in paths:
        r = await client.request(method, path, **kw)  # type: ignore[arg-type]
        assert r.status_code == 404, (path, r.status_code, r.text)


async def case_list_jurisdictions(client: AsyncClient, w: World) -> None:
    await _alice_404(
        client, "GET", [f"/v1/workspaces/{w.ws_b}/jurisdictions"], headers=w.alice.headers
    )


async def case_list_topics(client: AsyncClient, w: World) -> None:
    await client.post(
        f"/v1/workspaces/{w.ws_b}/topics",
        json={"key": "b_only", "name": "B"},
        headers=w.bob.headers,
    )
    await _alice_404(client, "GET", [f"/v1/workspaces/{w.ws_b}/topics"], headers=w.alice.headers)
    a_topics = (await client.get(f"/v1/workspaces/{w.ws_a}/topics", headers=w.alice.headers)).json()
    assert "b_only" not in {t["key"] for t in a_topics}


async def case_create_topic(client: AsyncClient, w: World) -> None:
    before = await _b_get(client, w, "/topics")
    await _alice_404(
        client,
        "POST",
        [f"/v1/workspaces/{w.ws_b}/topics"],
        json={"key": "x", "name": "X"},
        headers=w.alice.headers,
    )
    assert await _b_get(client, w, "/topics") == before


async def case_list_scope_fields(client: AsyncClient, w: World) -> None:
    await client.post(
        f"/v1/workspaces/{w.ws_b}/scope-fields",
        json={"key": "b_field", "name": "B", "allowed_values": ["x"]},
        headers=w.bob.headers,
    )
    await _alice_404(
        client, "GET", [f"/v1/workspaces/{w.ws_b}/scope-fields"], headers=w.alice.headers
    )
    a = (await client.get(f"/v1/workspaces/{w.ws_a}/scope-fields", headers=w.alice.headers)).json()
    assert a == []


async def case_create_scope_field(client: AsyncClient, w: World) -> None:
    before = await _b_get(client, w, "/scope-fields")
    await _alice_404(
        client,
        "POST",
        [f"/v1/workspaces/{w.ws_b}/scope-fields"],
        json={"key": "x", "name": "X", "allowed_values": ["a"]},
        headers=w.alice.headers,
    )
    assert await _b_get(client, w, "/scope-fields") == before


async def case_list_glossary(client: AsyncClient, w: World) -> None:
    await client.post(
        f"/v1/workspaces/{w.ws_b}/glossary", json={"term": "B-PTO"}, headers=w.bob.headers
    )
    await _alice_404(client, "GET", [f"/v1/workspaces/{w.ws_b}/glossary"], headers=w.alice.headers)
    a = (await client.get(f"/v1/workspaces/{w.ws_a}/glossary", headers=w.alice.headers)).json()
    assert a == []


async def case_create_glossary_term(client: AsyncClient, w: World) -> None:
    before = await _b_get(client, w, "/glossary")
    await _alice_404(
        client,
        "POST",
        [f"/v1/workspaces/{w.ws_b}/glossary"],
        json={"term": "X"},
        headers=w.alice.headers,
    )
    assert await _b_get(client, w, "/glossary") == before


async def case_delete_glossary_term(client: AsyncClient, w: World) -> None:
    r = await client.post(
        f"/v1/workspaces/{w.ws_b}/glossary", json={"term": "Keep me"}, headers=w.bob.headers
    )
    term = r.json()["id"]
    await _alice_404(
        client,
        "DELETE",
        [f"/v1/workspaces/{w.ws_b}/glossary/{term}", f"/v1/workspaces/{w.ws_a}/glossary/{term}"],
        headers=w.alice.headers,
    )
    assert any(t["id"] == term for t in await _b_get(client, w, "/glossary"))  # type: ignore[attr-defined]


async def case_list_documents(client: AsyncClient, w: World) -> None:
    await _b_document(client, w)
    await _alice_404(client, "GET", [f"/v1/workspaces/{w.ws_b}/documents"], headers=w.alice.headers)
    a = (await client.get(f"/v1/workspaces/{w.ws_a}/documents", headers=w.alice.headers)).json()
    assert a == []


async def case_create_document(client: AsyncClient, w: World) -> None:
    before = await _b_get(client, w, "/documents")
    await _alice_404(
        client,
        "POST",
        [f"/v1/workspaces/{w.ws_b}/documents"],
        data={"title": "x"},
        files={"file": ("a.md", b"# T\n\ntext", "text/markdown")},
        headers=w.alice.headers,
    )
    assert await _b_get(client, w, "/documents") == before


async def case_get_document(client: AsyncClient, w: World) -> None:
    doc, _ = await _b_document(client, w)
    await _alice_404(
        client,
        "GET",
        [f"/v1/workspaces/{w.ws_b}/documents/{doc}", f"/v1/workspaces/{w.ws_a}/documents/{doc}"],
        headers=w.alice.headers,
    )


async def case_add_version(client: AsyncClient, w: World) -> None:
    doc, _ = await _b_document(client, w)
    before = await _b_get(client, w, f"/documents/{doc}")
    await _alice_404(
        client,
        "POST",
        [
            f"/v1/workspaces/{w.ws_b}/documents/{doc}/versions",
            f"/v1/workspaces/{w.ws_a}/documents/{doc}/versions",
        ],
        files={"file": ("v2.md", b"# T\n\nnew text here", "text/markdown")},
        headers=w.alice.headers,
    )
    assert await _b_get(client, w, f"/documents/{doc}") == before


async def case_get_version(client: AsyncClient, w: World) -> None:
    _, v = await _b_document(client, w)
    await _alice_404(
        client,
        "GET",
        [f"/v1/workspaces/{w.ws_b}/versions/{v}", f"/v1/workspaces/{w.ws_a}/versions/{v}"],
        headers=w.alice.headers,
    )


async def case_list_sections(client: AsyncClient, w: World) -> None:
    _, v = await _b_document(client, w)
    await _alice_404(
        client,
        "GET",
        [
            f"/v1/workspaces/{w.ws_b}/versions/{v}/sections",
            f"/v1/workspaces/{w.ws_a}/versions/{v}/sections",
        ],
        headers=w.alice.headers,
    )


async def case_confirm_tags(client: AsyncClient, w: World) -> None:
    _, v = await _b_document(client, w)
    body = {"jurisdiction_code": "DE", "effective_from": "2026-01-01"}
    await _alice_404(
        client,
        "PUT",
        [
            f"/v1/workspaces/{w.ws_b}/versions/{v}/tags",
            f"/v1/workspaces/{w.ws_a}/versions/{v}/tags",
        ],
        json=body,
        headers=w.alice.headers,
    )
    version = await _b_get(client, w, f"/versions/{v}")
    assert version["tags_confirmed_at"] is None  # type: ignore[index]


async def _b_ready(client: AsyncClient, w: World) -> str:
    from tests.knowledge.helpers import confirm

    _, v = await _b_document(client, w)
    await confirm(client, w.bob, w.ws_b, v)
    return v


async def case_publish_version(client: AsyncClient, w: World) -> None:
    v = await _b_ready(client, w)
    await _alice_404(
        client,
        "POST",
        [
            f"/v1/workspaces/{w.ws_b}/versions/{v}/publish",
            f"/v1/workspaces/{w.ws_a}/versions/{v}/publish",
        ],
        json={"acknowledge_conflicts": True},
        headers=w.alice.headers,
    )
    assert (await _b_get(client, w, f"/versions/{v}"))["status"] == "draft"  # type: ignore[index]


async def case_retire_version(client: AsyncClient, w: World) -> None:
    from tests.knowledge.helpers import publish

    v = await _b_ready(client, w)
    await publish(client, w.bob, w.ws_b, v, ack=True)
    await _alice_404(
        client,
        "POST",
        [
            f"/v1/workspaces/{w.ws_b}/versions/{v}/retire",
            f"/v1/workspaces/{w.ws_a}/versions/{v}/retire",
        ],
        headers=w.alice.headers,
    )
    assert (await _b_get(client, w, f"/versions/{v}"))["status"] == "published"  # type: ignore[index]


async def case_retry_version(client: AsyncClient, w: World) -> None:
    _, v = await _b_document(client, w)
    await _alice_404(
        client,
        "POST",
        [
            f"/v1/workspaces/{w.ws_b}/versions/{v}/retry",
            f"/v1/workspaces/{w.ws_a}/versions/{v}/retry",
        ],
        headers=w.alice.headers,
    )


async def case_get_coverage(client: AsyncClient, w: World) -> None:
    from tests.knowledge.helpers import publish

    v = await _b_ready(client, w)
    await publish(client, w.bob, w.ws_b, v, ack=True)
    await _alice_404(client, "GET", [f"/v1/workspaces/{w.ws_b}/coverage"], headers=w.alice.headers)
    a = (await client.get(f"/v1/workspaces/{w.ws_a}/coverage", headers=w.alice.headers)).json()
    assert a["cells"] == []


async def case_list_job_failures(client: AsyncClient, w: World) -> None:
    await _alice_404(
        client, "GET", [f"/v1/workspaces/{w.ws_b}/job-failures"], headers=w.alice.headers
    )
    a = (await client.get(f"/v1/workspaces/{w.ws_a}/job-failures", headers=w.alice.headers)).json()
    assert a == []


CASES: dict[tuple[str, str], Case] = {
    ("GET", "/v1/me"): case_get_me,
    ("POST", "/v1/workspaces"): case_create_workspace,
    ("GET", "/v1/workspaces/{workspace_id}"): case_get_workspace,
    ("GET", "/v1/workspaces/{workspace_id}/members"): case_list_members,
    ("POST", "/v1/workspaces/{workspace_id}/members"): case_add_member,
    ("PATCH", "/v1/workspaces/{workspace_id}/members/{membership_id}"): case_change_member_role,
    ("DELETE", "/v1/workspaces/{workspace_id}/members/{membership_id}"): case_remove_member,
    ("GET", "/v1/workspaces/{workspace_id}/jurisdictions"): case_list_jurisdictions,
    ("GET", "/v1/workspaces/{workspace_id}/topics"): case_list_topics,
    ("POST", "/v1/workspaces/{workspace_id}/topics"): case_create_topic,
    ("GET", "/v1/workspaces/{workspace_id}/scope-fields"): case_list_scope_fields,
    ("POST", "/v1/workspaces/{workspace_id}/scope-fields"): case_create_scope_field,
    ("GET", "/v1/workspaces/{workspace_id}/glossary"): case_list_glossary,
    ("POST", "/v1/workspaces/{workspace_id}/glossary"): case_create_glossary_term,
    ("DELETE", "/v1/workspaces/{workspace_id}/glossary/{term_id}"): case_delete_glossary_term,
    ("GET", "/v1/workspaces/{workspace_id}/documents"): case_list_documents,
    ("POST", "/v1/workspaces/{workspace_id}/documents"): case_create_document,
    ("GET", "/v1/workspaces/{workspace_id}/documents/{document_id}"): case_get_document,
    ("POST", "/v1/workspaces/{workspace_id}/documents/{document_id}/versions"): case_add_version,
    ("GET", "/v1/workspaces/{workspace_id}/versions/{version_id}"): case_get_version,
    ("GET", "/v1/workspaces/{workspace_id}/versions/{version_id}/sections"): case_list_sections,
    ("PUT", "/v1/workspaces/{workspace_id}/versions/{version_id}/tags"): case_confirm_tags,
    ("POST", "/v1/workspaces/{workspace_id}/versions/{version_id}/publish"): case_publish_version,
    ("POST", "/v1/workspaces/{workspace_id}/versions/{version_id}/retire"): case_retire_version,
    ("POST", "/v1/workspaces/{workspace_id}/versions/{version_id}/retry"): case_retry_version,
    ("GET", "/v1/workspaces/{workspace_id}/coverage"): case_get_coverage,
    ("GET", "/v1/workspaces/{workspace_id}/job-failures"): case_list_job_failures,
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
