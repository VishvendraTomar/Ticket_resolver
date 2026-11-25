"""SPEC §6 'constraints that make bad states impossible', proven against the DB directly."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import World
from tests.knowledge.helpers import add_version, confirm, published_version, rows, upload

pytestmark = pytest.mark.db


async def _exec(engine: AsyncEngine, ws: str, sql: str, **params: object) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("SELECT set_config('app.workspace_id', :w, true)"), {"w": ws})
        await conn.execute(text(sql), params)


async def test_db_rejects_published_without_jurisdiction(
    client: AsyncClient, world: World, app_engine: AsyncEngine
) -> None:
    doc = await upload(client, world.bob, world.ws_b)
    vid = doc["versions"][0]["id"]
    with pytest.raises(DBAPIError, match="ck_document_versions_published_needs_tags"):
        await _exec(
            app_engine,
            world.ws_b,
            "UPDATE document_versions SET status = 'published' WHERE id = :v",
            v=vid,
        )


async def test_overlapping_published_versions_are_impossible(
    client: AsyncClient, world: World, app_engine: AsyncEngine
) -> None:
    doc_id, _v1 = await published_version(
        client, world.bob, world.ws_b, effective_from=date(2026, 1, 1)
    )
    r = await add_version(client, world.bob, world.ws_b, doc_id)
    v2 = r.json()["id"]
    await confirm(client, world.bob, world.ws_b, v2, effective_from=date(2026, 6, 1))
    # Bypass the API: publish v2 directly while v1 is still open-ended.
    with pytest.raises(DBAPIError, match="ex_document_versions_no_overlap"):
        await _exec(
            app_engine,
            world.ws_b,
            "UPDATE document_versions SET status = 'published' WHERE id = :v",
            v=v2,
        )
    # Different scope is a different rule: allowed to coexist.
    await _exec(
        app_engine,
        world.ws_b,
        "UPDATE document_versions SET status = 'published', "
        'scope = \'{"worker_type": "contractor"}\' WHERE id = :v',
        v=v2,
    )


async def test_chunks_are_deleted_with_their_version(
    client: AsyncClient, world: World, app_engine: AsyncEngine
) -> None:
    doc = await upload(client, world.bob, world.ws_b)
    vid = doc["versions"][0]["id"]
    await confirm(client, world.bob, world.ws_b, vid)
    count = (
        "SELECT (SELECT count(*) FROM chunks WHERE version_id = :v), "
        "(SELECT count(*) FROM chunk_embeddings e JOIN chunks c ON c.id = e.chunk_id "
        "WHERE c.version_id = :v), (SELECT count(*) FROM sections WHERE version_id = :v)"
    )
    [(chunks, embeddings, sections)] = await rows(app_engine, world.ws_b, count, v=vid)
    assert chunks > 0
    assert embeddings == chunks
    assert sections > 0
    await _exec(app_engine, world.ws_b, "DELETE FROM document_versions WHERE id = :v", v=vid)
    assert await rows(app_engine, world.ws_b, count, v=vid) == [(0, 0, 0)]


async def test_db_rejects_dimension_mismatch(
    client: AsyncClient, world: World, app_engine: AsyncEngine
) -> None:
    doc = await upload(client, world.bob, world.ws_b)
    vid = doc["versions"][0]["id"]
    [(chunk_id,)] = await rows(
        app_engine, world.ws_b, "SELECT id FROM chunks WHERE version_id = :v LIMIT 1", v=vid
    )
    with pytest.raises(DBAPIError, match="ck_chunk_embeddings_dims"):
        await _exec(
            app_engine,
            world.ws_b,
            "INSERT INTO chunk_embeddings (chunk_id, workspace_id, model, dims, embedding, "
            "content_hash) VALUES (:c, :w, 'x@768', 768, '[1,2,3]', repeat('0', 64))",
            c=chunk_id,
            w=world.ws_b,
        )
    assert uuid.UUID(str(chunk_id))
