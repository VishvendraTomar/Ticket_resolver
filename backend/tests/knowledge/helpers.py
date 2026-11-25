"""Helpers for knowledge-base tests: upload, confirm tags, publish (fakes, eager jobs)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import Person

POLICY_MD = """# Northwind Leave Policy

## 1. Scope

1.1 This policy applies to all employees. See Annex B for carry-over forms.

## 2. Annual leave

2.1 Employees receive 30 working days of paid annual leave per calendar year.

2.2 Up to five unused days may be carried over and must be taken by 31 March.

| Years of service | Extra days |
|---|---|
| 0-4 | 0 |
| 5+ | 2 |

## Annex B

Carry-over request form and approval steps.
"""


def unique_md(base: str = POLICY_MD) -> str:
    """Different bytes every call, so uploads never collide on the file hash."""
    return f"{base}\n\n<!-- {uuid.uuid4()} -->\n"


async def upload(
    client: AsyncClient,
    who: Person,
    ws: str,
    md: str | None = None,
    *,
    title: str = "Northwind Leave Policy",
    filename: str = "leave.md",
    language: str = "en",
    expect: int = 201,
) -> dict[str, Any]:
    r = await client.post(
        f"/v1/workspaces/{ws}/documents",
        data={"title": title, "language": language},
        files={"file": (filename, (md or unique_md()).encode(), "text/markdown")},
        headers=who.headers,
    )
    assert r.status_code == expect, r.text
    body: dict[str, Any] = r.json()
    return body


async def add_version(
    client: AsyncClient, who: Person, ws: str, document_id: str, md: str | None = None
) -> Response:
    return await client.post(
        f"/v1/workspaces/{ws}/documents/{document_id}/versions",
        files={"file": ("leave-v2.md", (md or unique_md()).encode(), "text/markdown")},
        headers=who.headers,
    )


async def get_version(client: AsyncClient, who: Person, ws: str, vid: str) -> dict[str, Any]:
    r = await client.get(f"/v1/workspaces/{ws}/versions/{vid}", headers=who.headers)
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


async def topic_id(client: AsyncClient, who: Person, ws: str, key: str) -> str:
    topics = (await client.get(f"/v1/workspaces/{ws}/topics", headers=who.headers)).json()
    return str(next(t["id"] for t in topics if t["key"] == key))


async def confirm(
    client: AsyncClient,
    who: Person,
    ws: str,
    vid: str,
    *,
    jurisdiction: str = "DE",
    effective_from: date = date(2026, 1, 1),
    effective_to: date | None = None,
    topic: str | None = "leave",
    scope: dict[str, str] | None = None,
    sections: list[dict[str, Any]] | None = None,
    expect: int = 200,
) -> Response:
    body: dict[str, Any] = {
        "jurisdiction_code": jurisdiction,
        "effective_from": effective_from.isoformat(),
        "effective_to": effective_to.isoformat() if effective_to else None,
        "topic_id": await topic_id(client, who, ws, topic) if topic else None,
        "scope": scope or {},
        "sections": sections or [],
    }
    r = await client.put(f"/v1/workspaces/{ws}/versions/{vid}/tags", json=body, headers=who.headers)
    assert r.status_code == expect, r.text
    return r


async def publish(
    client: AsyncClient, who: Person, ws: str, vid: str, *, ack: bool = False, expect: int = 200
) -> Response:
    r = await client.post(
        f"/v1/workspaces/{ws}/versions/{vid}/publish",
        json={"acknowledge_conflicts": ack},
        headers=who.headers,
    )
    assert r.status_code == expect, r.text
    return r


async def published_version(
    client: AsyncClient, who: Person, ws: str, **confirm_kw: Any
) -> tuple[str, str]:
    """Upload → review → embed → publish. Returns (document_id, version_id)."""
    doc = await upload(client, who, ws)
    vid = doc["versions"][0]["id"]
    await confirm(client, who, ws, vid, **confirm_kw)
    assert (await get_version(client, who, ws, vid))["pipeline_status"] == "ready"
    await publish(client, who, ws, vid, ack=True)
    return doc["id"], vid


async def rows(engine: AsyncEngine, ws: str, sql: str, **params: Any) -> list[Any]:
    """Query as app_user inside the workspace (RLS applies)."""
    async with engine.begin() as conn:
        await conn.execute(text("SELECT set_config('app.workspace_id', :w, true)"), {"w": ws})
        return list((await conn.execute(text(sql), params)).all())
