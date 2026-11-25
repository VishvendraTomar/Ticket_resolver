"""docs/failure-modes/ingestion.md #8–#14, parsing.md #9 — the version lifecycle."""

from __future__ import annotations

from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import World, add_member, new_person, sign_in
from tests.knowledge.helpers import (
    add_version,
    confirm,
    get_version,
    publish,
    published_version,
    rows,
    unique_md,
    upload,
)

pytestmark = pytest.mark.db


async def test_publish_requires_jurisdiction_and_dates(client: AsyncClient, world: World) -> None:
    doc = await upload(client, world.bob, world.ws_b)
    vid = doc["versions"][0]["id"]
    path = f"/v1/workspaces/{world.ws_b}/versions/{vid}/tags"
    r = await client.put(path, json={"scope": {}}, headers=world.bob.headers)
    assert r.status_code == 422  # jurisdiction_code and effective_from are required
    r = await client.put(
        path,
        json={"jurisdiction_code": "ZZ", "effective_from": "2026-01-01"},
        headers=world.bob.headers,
    )
    assert r.status_code == 422
    assert "Unknown jurisdiction" in r.json()["error"]["message"]
    await confirm(client, world.bob, world.ws_b, vid, effective_to=date(2025, 1, 1), expect=422)


async def test_publish_requires_ready(client: AsyncClient, world: World) -> None:
    doc = await upload(client, world.bob, world.ws_b)
    vid = doc["versions"][0]["id"]
    r = await publish(client, world.bob, world.ws_b, vid, expect=409)
    assert "isn't ready to publish (awaiting_review)" in r.json()["error"]["message"]


async def test_new_version_closes_previous(client: AsyncClient, world: World) -> None:
    doc_id, v1 = await published_version(
        client, world.bob, world.ws_b, effective_from=date(2026, 1, 1)
    )
    r = await add_version(client, world.bob, world.ws_b, doc_id)
    v2 = r.json()["id"]
    await confirm(client, world.bob, world.ws_b, v2, effective_from=date(2026, 7, 1))
    await publish(client, world.bob, world.ws_b, v2, ack=True)
    old = await get_version(client, world.bob, world.ws_b, v1)
    new = await get_version(client, world.bob, world.ws_b, v2)
    assert (old["status"], old["effective_to"]) == ("published", "2026-07-01")
    assert (new["status"], new["effective_from"], new["effective_to"]) == (
        "published",
        "2026-07-01",
        None,
    )

    # A third version starting *before* v2 would overlap it: refused, nothing changes.
    r = await add_version(client, world.bob, world.ws_b, doc_id)
    v3 = r.json()["id"]
    await confirm(client, world.bob, world.ws_b, v3, effective_from=date(2026, 3, 1))
    r = await publish(client, world.bob, world.ws_b, v3, ack=True, expect=409)
    assert "already covers these dates" in r.json()["error"]["message"]
    assert (await get_version(client, world.bob, world.ws_b, v3))["status"] == "draft"


async def test_chunk_fields_follow_publish_and_retire(
    client: AsyncClient, world: World, app_engine: AsyncEngine
) -> None:
    _, vid = await published_version(client, world.bob, world.ws_b, jurisdiction="FR")
    sql = (
        "SELECT DISTINCT version_status::text, jurisdiction_code FROM chunks WHERE version_id = :v"
    )
    assert await rows(app_engine, world.ws_b, sql, v=vid) == [("published", "FR")]
    r = await client.post(
        f"/v1/workspaces/{world.ws_b}/versions/{vid}/retire", headers=world.bob.headers
    )
    assert r.status_code == 200
    assert await rows(app_engine, world.ws_b, sql, v=vid) == [("retired", "FR")]


async def test_publish_flags_contradiction_candidates(client: AsyncClient, world: World) -> None:
    await published_version(client, world.bob, world.ws_b, jurisdiction="EU", topic="sick_pay")
    doc = await upload(client, world.bob, world.ws_b, title="Germany sick pay")
    vid = doc["versions"][0]["id"]
    await confirm(client, world.bob, world.ws_b, vid, jurisdiction="DE-BY", topic="sick_pay")
    r = await publish(client, world.bob, world.ws_b, vid, expect=409)
    candidates = r.json()["error"]["details"]["candidates"]
    assert candidates
    assert {c["other_jurisdiction"] for c in candidates} == {"EU"}
    assert (await get_version(client, world.bob, world.ws_b, vid))["status"] == "draft"
    await publish(client, world.bob, world.ws_b, vid, ack=True)

    # Different topic or a jurisdiction outside the chain: no candidates.
    doc = await upload(client, world.bob, world.ws_b, title="France expenses")
    vid = doc["versions"][0]["id"]
    await confirm(client, world.bob, world.ws_b, vid, jurisdiction="GB", topic="sick_pay")
    await publish(client, world.bob, world.ws_b, vid)


async def test_restricted_policy_editor(client: AsyncClient, world: World) -> None:
    erin = new_person("erin")
    await sign_in(client, erin)
    membership = await add_member(client, world.bob, world.ws_b, erin, "policy_editor")
    r = await client.patch(
        f"/v1/workspaces/{world.ws_b}/members/{membership}",
        json={"jurisdiction_codes": ["DE"]},
        headers=world.bob.headers,
    )
    assert r.status_code == 200
    assert r.json()["jurisdiction_codes"] == ["DE"]

    doc = await upload(client, erin, world.ws_b)
    vid = doc["versions"][0]["id"]
    r = await confirm(client, erin, world.ws_b, vid, jurisdiction="FR", expect=403)
    assert "only edit documents for: DE" in r.json()["error"]["message"]
    await confirm(client, erin, world.ws_b, vid, jurisdiction="DE-BY")  # within DE: fine
    await publish(client, erin, world.ws_b, vid, ack=True)

    _, french = await published_version(client, world.bob, world.ws_b, jurisdiction="FR")
    r = await client.post(
        f"/v1/workspaces/{world.ws_b}/versions/{french}/retire", headers=erin.headers
    )
    assert r.status_code == 403


async def test_section_tags_override_version_defaults(
    client: AsyncClient, world: World, app_engine: AsyncEngine
) -> None:
    md = unique_md(
        "# Global Handbook\n\n## 1. Leave\n\nEveryone gets 25 days.\n\n"
        "## Annex DE\n\nIn Germany employees get 30 days.\n"
    )
    doc = await upload(client, world.bob, world.ws_b, md, title="Global Handbook")
    vid = doc["versions"][0]["id"]
    sections = (
        await client.get(
            f"/v1/workspaces/{world.ws_b}/versions/{vid}/sections", headers=world.bob.headers
        )
    ).json()
    annex = sections[1]["id"]
    await confirm(
        client,
        world.bob,
        world.ws_b,
        vid,
        jurisdiction="GLOBAL",
        sections=[{"section_id": annex, "jurisdiction_code": "DE"}],
    )
    got = await rows(
        app_engine,
        world.ws_b,
        "SELECT s.title, c.jurisdiction_code, c.context_header FROM chunks c "
        "JOIN sections s ON s.id = c.section_id WHERE c.version_id = :v ORDER BY c.ordinal",
        v=vid,
    )
    assert [(t, j) for t, j, _ in got] == [("1. Leave", "GLOBAL"), ("Annex DE", "DE")]
    assert "applies to: Germany (DE)" in got[1][2]
