"""docs/failure-modes/ingestion.md #4–#7, embeddings.md #7, #9 — the jobs themselves."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import get_sessionmaker
from app.ingestion import pipeline
from app.knowledge.models import PipelineStatus
from app.providers.embeddings import get_embedder
from app.providers.embeddings.base import EmbeddingUnavailable, InputType
from app.providers.embeddings.validating import ValidatingEmbedder
from app.providers.llm.fake import FakeLLM
from app.providers.parser.fake import FakeParser
from app.providers.storage import get_storage
from tests.conftest import World
from tests.knowledge.helpers import add_version, confirm, get_version, rows, upload

pytestmark = pytest.mark.db


async def _set(engine: AsyncEngine, ws: str, vid: str, **values: object) -> None:
    from sqlalchemy import text

    sets = ", ".join(f"{k} = :{k}" for k in values)
    async with engine.begin() as conn:
        await conn.execute(text("SELECT set_config('app.workspace_id', :w, true)"), {"w": ws})
        await conn.execute(
            text(f"UPDATE document_versions SET {sets} WHERE id = :v"),  # noqa: S608
            {"v": vid, **values},
        )


async def _ingest(ws: str, vid: str, parser: FakeParser | None = None) -> str:
    return await pipeline.ingest_version(
        get_sessionmaker(),
        uuid.UUID(ws),
        uuid.UUID(vid),
        parser=parser or FakeParser(),
        storage=get_storage(),
        llm=FakeLLM(),
    )


async def test_ingest_is_idempotent(
    client: AsyncClient, world: World, app_engine: AsyncEngine
) -> None:
    doc = await upload(client, world.bob, world.ws_b)
    vid = doc["versions"][0]["id"]
    count = (
        "SELECT (SELECT count(*) FROM sections WHERE version_id = :v), "
        "(SELECT count(*) FROM chunks WHERE version_id = :v), "
        "(SELECT count(*) FROM section_refs WHERE version_id = :v)"
    )
    before = await rows(app_engine, world.ws_b, count, v=vid)
    # Simulate a crash after parsing: run the job again from the start.
    await _set(app_engine, world.ws_b, vid, pipeline_status="queued")
    assert await _ingest(world.ws_b, vid) == pipeline.DONE
    assert await rows(app_engine, world.ws_b, count, v=vid) == before
    assert (await get_version(client, world.bob, world.ws_b, vid))[
        "pipeline_status"
    ] == "awaiting_review"


async def test_concurrent_run_is_skipped(
    client: AsyncClient, world: World, app_engine: AsyncEngine
) -> None:
    doc = await upload(client, world.bob, world.ws_b)
    vid = doc["versions"][0]["id"]
    parser = FakeParser()
    await _set(
        app_engine,
        world.ws_b,
        vid,
        pipeline_status="queued",
        pipeline_run_id=uuid.uuid4(),
        pipeline_lease_until=datetime.now(UTC) + timedelta(minutes=10),
    )
    assert await _ingest(world.ws_b, vid, parser) == pipeline.SKIPPED
    assert parser.calls == 0
    # An expired lease (crashed worker) can be taken over.
    await _set(
        app_engine, world.ws_b, vid, pipeline_lease_until=datetime.now(UTC) - timedelta(minutes=1)
    )
    assert await _ingest(world.ws_b, vid, parser) == pipeline.DONE
    assert parser.calls == 1


async def test_final_failure_records_job_failure(
    client: AsyncClient, world: World, monkeypatch: pytest.MonkeyPatch, app_engine: AsyncEngine
) -> None:
    class Down:
        model_key, dims = "fake/hash@768", 768

        async def embed_one(self, text: str, input_type: InputType) -> list[float]:
            raise EmbeddingUnavailable("503 from provider")

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(
        "workers.tasks.get_embedder",
        lambda: ValidatingEmbedder(Down(), max_tokens=1800, max_attempts=2, sleep=no_sleep),
    )
    monkeypatch.setattr("app.ingestion.pipeline.backoff_seconds", lambda attempt: 0)
    doc = await upload(client, world.bob, world.ws_b)
    vid = doc["versions"][0]["id"]
    await confirm(client, world.bob, world.ws_b, vid)
    version = await get_version(client, world.bob, world.ws_b, vid)
    assert version["pipeline_status"] == "failed"
    assert "EmbeddingUnavailable" in version["pipeline_error"]
    failures = await rows(
        app_engine,
        world.ws_b,
        "SELECT task_name, attempts FROM job_failures WHERE version_id = :v",
        v=vid,
    )
    assert failures == [("embed_version", 5)]  # first try + 4 retries


async def test_task_runs_in_its_workspace_only(client: AsyncClient, world: World) -> None:
    doc = await upload(client, world.bob, world.ws_b)
    vid = doc["versions"][0]["id"]
    # Asking for B's version with A's workspace id: RLS hides it, nothing happens.
    assert await _ingest(world.ws_a, vid) == pipeline.SKIPPED


async def test_unchanged_chunks_reuse_embeddings(
    client: AsyncClient, world: World, app_engine: AsyncEngine
) -> None:
    raw = get_embedder().raw  # type: ignore[attr-defined]
    doc = await upload(client, world.bob, world.ws_b)
    v1 = doc["versions"][0]["id"]
    await confirm(client, world.bob, world.ws_b, v1)
    first = len(raw.calls)
    # v2 has the same text and tags, plus one new paragraph.
    from tests.knowledge.helpers import POLICY_MD

    r = await add_version(
        client,
        world.bob,
        world.ws_b,
        doc["id"],
        POLICY_MD + "\n## 3. Sick leave\n\nSee the sick pay policy.\n",
    )
    v2 = r.json()["id"]
    await confirm(client, world.bob, world.ws_b, v2)
    report = (await get_version(client, world.bob, world.ws_b, v2))["parse_report"]["embedding"]
    assert report["reused"] >= 1
    assert report["embedded"] == len(raw.calls) - first
    assert report["embedded"] < report["reused"] + report["embedded"]


async def test_ready_only_when_fully_embedded(
    client: AsyncClient, world: World, app_engine: AsyncEngine
) -> None:
    class Half:
        model_key, dims = "fake/hash@768", 768

        def __init__(self) -> None:
            self.n = 0

        async def embed(self, texts: list[str], input_type: InputType) -> list[list[float]]:
            return [[1.0] + [0.0] * 767 for _ in texts[: len(texts) // 2]]

    doc = await upload(client, world.bob, world.ws_b)
    vid = doc["versions"][0]["id"]
    await _set(
        app_engine,
        world.ws_b,
        vid,
        pipeline_status="embedding",
        tags_confirmed_at=datetime.now(UTC),
        jurisdiction_code="DE",
    )
    with pytest.raises(ValueError, match="zip"):
        await pipeline.embed_version(
            get_sessionmaker(), uuid.UUID(world.ws_b), uuid.UUID(vid), embedder=Half()
        )  # type: ignore[arg-type]
    version = await get_version(client, world.bob, world.ws_b, vid)
    assert version["pipeline_status"] != PipelineStatus.READY
