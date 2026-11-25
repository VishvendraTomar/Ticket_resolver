"""Ingestion jobs (ADR-0007). Called by Celery tasks (workers/) and directly by tests.

Two jobs, each idempotent and keyed by version id:
- ingest_version: parse → sections → chunks → references → tag suggestions,
  ending in `awaiting_review` (a human confirms tags next).
- embed_version: context headers → full-text vectors → embeddings (with reuse),
  ending in `ready`.

A job claims a lease on the version (pipeline_run_id + pipeline_lease_until)
in a short transaction, does slow work (parsing, provider calls) with no
transaction open, then writes results in a second short transaction only if
it still holds the lease. A concurrent or redelivered run sees the lease and
skips (ingestion.md #5). Failures are recorded by `record_failure`.
"""

from __future__ import annotations

import asyncio
import math
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam, delete, func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.db import set_context
from app.ingestion.chunking import chunk_section
from app.ingestion.header import content_hash, context_header, embedded_text, ts_config
from app.ingestion.refs import extract_refs, resolve_ref
from app.ingestion.sectioning import build_sections
from app.ingestion.tagging import SectionInput, Vocabulary, suggest_tags
from app.knowledge.jurisdictions import load_tree
from app.knowledge.models import (
    Chunk,
    ChunkEmbedding,
    Document,
    DocumentVersion,
    JobFailure,
    PipelineStatus,
    ScopeField,
    Section,
    SectionRef,
    Topic,
    VersionStatus,
)
from app.providers.embeddings.base import Embedder, EmbeddingError, InputType
from app.providers.llm.base import LLM
from app.providers.parser.base import ParseError, Parser
from app.providers.storage.base import Storage
from app.tenancy.models import Workspace

SKIPPED = "skipped"
DONE = "done"
EMBED_BATCH = 64
MIN_TEXT_CHARS = 40


class LeaseLost(Exception):
    """Another run took over this version; this run's results are discarded."""


@dataclass(frozen=True)
class Claim:
    run_id: uuid.UUID
    version: DocumentVersion
    document: Document


@asynccontextmanager
async def _tx(
    sm: async_sessionmaker[AsyncSession], workspace_id: uuid.UUID
) -> AsyncIterator[AsyncSession]:
    """One transaction in the version's workspace, as app_user (ADR-0002, ingestion.md #7)."""
    async with sm() as session, session.begin():
        await set_context(session, workspace_id=workspace_id)
        yield session


async def _lock(
    session: AsyncSession, version_id: uuid.UUID, *, skip_locked: bool
) -> DocumentVersion | None:
    stmt = (
        select(DocumentVersion)
        .where(DocumentVersion.id == version_id)
        .with_for_update(skip_locked=skip_locked)
    )
    return await session.scalar(stmt)


async def _claim(
    sm: async_sessionmaker[AsyncSession],
    workspace_id: uuid.UUID,
    version_id: uuid.UUID,
    allowed: set[PipelineStatus],
    start_status: PipelineStatus,
) -> Claim | None:
    lease = timedelta(seconds=get_settings().parse_timeout_seconds + 300)
    async with _tx(sm, workspace_id) as session:
        version = await _lock(session, version_id, skip_locked=True)
        if version is None:
            return None  # locked by another run right now, or not in this workspace
        now = datetime.now(UTC)
        if version.pipeline_lease_until is not None and version.pipeline_lease_until > now:
            return None  # another run holds the lease
        if version.status is not VersionStatus.DRAFT or version.pipeline_status not in allowed:
            return None
        version.pipeline_run_id = uuid.uuid4()
        version.pipeline_lease_until = now + lease
        version.pipeline_status = start_status
        version.pipeline_error = None
        document = await session.get_one(Document, version.document_id)
        await session.flush()
        session.expunge_all()
        return Claim(version.pipeline_run_id, version, document)


async def _locked_with_lease(
    session: AsyncSession, version_id: uuid.UUID, run_id: uuid.UUID
) -> DocumentVersion:
    version = await _lock(session, version_id, skip_locked=False)
    if version is None or version.pipeline_run_id != run_id:
        raise LeaseLost(f"version {version_id}: lease lost")
    return version


def _release(version: DocumentVersion) -> None:
    version.pipeline_run_id = None
    version.pipeline_lease_until = None


# --- ingest ------------------------------------------------------------------------------


async def ingest_version(
    sm: async_sessionmaker[AsyncSession],
    workspace_id: uuid.UUID,
    version_id: uuid.UUID,
    *,
    parser: Parser,
    storage: Storage,
    llm: LLM,
) -> str:
    settings = get_settings()
    claim = await _claim(
        sm,
        workspace_id,
        version_id,
        {PipelineStatus.QUEUED, PipelineStatus.FAILED},
        PipelineStatus.PARSING,
    )
    if claim is None:
        return SKIPPED
    version, document = claim.version, claim.document

    # 1. Parse, outside any transaction (can take minutes for OCR'd PDFs).
    data = await storage.get(version.storage_key)
    parsed = await asyncio.to_thread(parser.parse, data, version.mime_type, version.file_name)
    text_chars = sum(len(b.text) for b in parsed.blocks)
    if text_chars < MIN_TEXT_CHARS:
        raise ParseError(
            "No text extracted: the file may be empty, encrypted, or a scan that OCR "
            "couldn't read (parsing.md #4)"
        )
    if parsed.page_count and parsed.page_count > settings.max_pages:
        raise ParseError(f"{parsed.page_count} pages is over the {settings.max_pages}-page limit")

    sectioned = build_sections(parsed.blocks)
    warnings = list(parsed.warnings) + sectioned.warnings
    chunks_per_section = []
    for section in sectioned.sections:
        drafts, chunk_warnings = chunk_section(section)
        chunks_per_section.append(drafts)
        warnings += chunk_warnings
    low_ocr = sorted(p for p, c in parsed.ocr_confidence.items() if c < settings.ocr_min_confidence)
    needs_review = bool(low_ocr)
    report: dict[str, Any] = {
        "parser": parsed.parser,
        "page_count": parsed.page_count,
        "blocks": len(parsed.blocks),
        "headings": sum(1 for b in parsed.blocks if b.kind == "heading"),
        "tables": sum(1 for b in parsed.blocks if b.kind == "table"),
        "sections": len(sectioned.sections),
        "chunks": sum(len(c) for c in chunks_per_section),
        "title": sectioned.title,
        "ocr": {
            "pages_ocrd": len(parsed.ocr_confidence),
            "min_confidence": round(min(parsed.ocr_confidence.values()), 3)
            if parsed.ocr_confidence
            else None,
            "low_confidence_pages": low_ocr,
            "threshold": settings.ocr_min_confidence,
        },
        "warnings": warnings,
        "needs_review": needs_review,
    }

    # 2. Replace this version's sections/chunks/refs in one transaction (ingestion.md #4).
    section_ids: list[uuid.UUID] = []
    async with _tx(sm, workspace_id) as session:
        v = await _locked_with_lease(session, version_id, claim.run_id)
        await session.execute(delete(Section).where(Section.version_id == version_id))
        config = ts_config(document.language)
        for ordinal, section in enumerate(sectioned.sections):
            sid = uuid.uuid4()
            section_ids.append(sid)
            session.add(
                Section(
                    id=sid,
                    workspace_id=workspace_id,
                    version_id=version_id,
                    ordinal=ordinal,
                    heading_path=section.heading_path,
                    clause_number=section.clause_number,
                    title=section.title,
                    text=section.text,
                    token_count=section.token_count,
                    has_table=section.has_table,
                    page_start=section.page_start,
                )
            )
        await session.flush()
        chunk_ordinal = 0
        for sid, drafts in zip(section_ids, chunks_per_section, strict=True):
            for draft in drafts:
                session.add(
                    Chunk(
                        id=uuid.uuid4(),
                        workspace_id=workspace_id,
                        version_id=version_id,
                        section_id=sid,
                        ordinal=chunk_ordinal,
                        text=draft.text,
                        context_header="",
                        content_hash=content_hash("", draft.text),
                        token_count=draft.token_count,
                        ts_config=config,
                        document_id=document.id,
                        version_status=VersionStatus.DRAFT,
                        scope={},
                    )
                )
                chunk_ordinal += 1
        for i, section in enumerate(sectioned.sections):
            for target in extract_refs(section.text):
                to = resolve_ref(target, sectioned.sections, exclude=i)
                session.add(
                    SectionRef(
                        id=uuid.uuid4(),
                        workspace_id=workspace_id,
                        version_id=version_id,
                        from_section_id=section_ids[i],
                        target_text=target[:200],
                        to_section_id=section_ids[to] if to is not None else None,
                    )
                )
        v.parse_report = report
        v.needs_review = needs_review
        v.tag_suggestions = {}
        v.tags_confirmed_at = None
        v.pipeline_status = PipelineStatus.TAGGING
        tree = await load_tree(session)
        topics = {
            t.key: (t.id, t.name)
            for t in await session.scalars(select(Topic).where(Topic.workspace_id == workspace_id))
        }
        fields = {
            f.key: f.allowed_values
            for f in await session.scalars(
                select(ScopeField).where(ScopeField.workspace_id == workspace_id)
            )
        }

    # 3. Tag suggestions, outside any transaction (tagging.md #3: outage ≠ failure).
    vocab = Vocabulary(
        jurisdiction_codes=frozenset(tree.parents),
        topics={k: name for k, (_, name) in topics.items()},
        scope_fields=fields,
    )
    suggestions = await suggest_tags(
        llm,
        document_title=document.title,
        language=document.language,
        sections=[
            SectionInput(i, s.heading_path, s.text) for i, s in enumerate(sectioned.sections)
        ],
        vocab=vocab,
        max_sections=settings.tagging_max_sections,
    )
    # Store by section id and topic id, so the UI can prefill the review form.
    suggestions["sections"] = {
        str(section_ids[int(i)]): _with_topic_id(v, topics)
        for i, v in suggestions["sections"].items()
    }
    suggestions["version"] = _with_topic_id(suggestions["version"], topics)

    async with _tx(sm, workspace_id) as session:
        v = await _locked_with_lease(session, version_id, claim.run_id)
        v.tag_suggestions = suggestions
        v.pipeline_status = PipelineStatus.AWAITING_REVIEW
        _release(v)
    return DONE


def _with_topic_id(
    values: dict[str, Any], topics: dict[str, tuple[uuid.UUID, str]]
) -> dict[str, Any]:
    out = dict(values)
    if "topic" in out:
        out["topic_id"] = str(topics[out["topic"]][0])
    return out


# --- embed -------------------------------------------------------------------------------


async def embed_version(
    sm: async_sessionmaker[AsyncSession],
    workspace_id: uuid.UUID,
    version_id: uuid.UUID,
    *,
    embedder: Embedder,
) -> str:
    claim = await _claim(
        sm,
        workspace_id,
        version_id,
        {PipelineStatus.EMBEDDING, PipelineStatus.FAILED},
        PipelineStatus.EMBEDDING,
    )
    if claim is None:
        return SKIPPED
    version, document = claim.version, claim.document
    if version.tags_confirmed_at is None:
        raise EmbeddingError("tags must be confirmed before embedding")

    # 1. Headers from confirmed tags; full-text vectors; reuse unchanged embeddings.
    async with _tx(sm, workspace_id) as session:
        await _locked_with_lease(session, version_id, claim.run_id)
        workspace = await session.get_one(Workspace, workspace_id)
        model = workspace.active_embedding_model or embedder.model_key
        if model != embedder.model_key:
            raise EmbeddingError(
                f"workspace searches with {model} but the configured embedder is "
                f"{embedder.model_key}; re-embed with that model first (embeddings.md #2)"
            )
        tree = await load_tree(session)
        sections = {
            s.id: s
            for s in await session.scalars(select(Section).where(Section.version_id == version_id))
        }
        chunks = list(
            await session.scalars(
                select(Chunk).where(Chunk.version_id == version_id).order_by(Chunk.ordinal)
            )
        )
        for chunk in chunks:
            section = sections[chunk.section_id]
            code = section.jurisdiction_code or version.jurisdiction_code
            scope = section.scope if section.scope is not None else version.scope
            chunk.context_header = context_header(
                document_title=document.title,
                heading_path=section.heading_path,
                jurisdiction=tree.label(code) if code else None,
                scope=scope,
                effective_from=version.effective_from,
                effective_to=version.effective_to,
            )
            chunk.content_hash = content_hash(chunk.context_header, chunk.text)
            chunk.jurisdiction_code = code
            chunk.scope = scope
            chunk.topic_id = section.topic_id or version.topic_id
            chunk.effective_from = version.effective_from
            chunk.effective_to = version.effective_to
            chunk.version_status = version.status
        await session.flush()
        await session.execute(
            text(
                "UPDATE chunks SET tsv = to_tsvector(ts_config, context_header || ' ' || text) "
                "WHERE version_id = :v"
            ),
            {"v": version_id},
        )
        # Drop this version's embeddings whose text changed (e.g. tags edited).
        await session.execute(
            text(
                "DELETE FROM chunk_embeddings e USING chunks c WHERE e.chunk_id = c.id "
                "AND c.version_id = :v AND e.model = :m AND e.content_hash <> c.content_hash"
            ),
            {"v": version_id, "m": model},
        )
        # Reuse an identical embedding from anywhere in this workspace (embeddings.md #7).
        await session.execute(
            text("""
                INSERT INTO chunk_embeddings (chunk_id, workspace_id, model, dims, embedding,
                                              content_hash)
                SELECT c.id, c.workspace_id, :m, prev.dims, prev.embedding, c.content_hash
                FROM chunks c
                JOIN LATERAL (
                    SELECT e.dims, e.embedding FROM chunk_embeddings e
                    WHERE e.workspace_id = c.workspace_id AND e.model = :m
                      AND e.content_hash = c.content_hash
                    LIMIT 1
                ) prev ON true
                WHERE c.version_id = :v
                ON CONFLICT (chunk_id, model) DO NOTHING
            """),
            {"v": version_id, "m": model},
        )
        have = set(
            (
                await session.scalars(
                    select(ChunkEmbedding.chunk_id)
                    .join(Chunk, Chunk.id == ChunkEmbedding.chunk_id)
                    .where(Chunk.version_id == version_id, ChunkEmbedding.model == model)
                )
            ).all()
        )
        todo = [
            (c.id, c.content_hash, embedded_text(c.context_header, c.text))
            for c in chunks
            if c.id not in have
        ]
        reused = len(chunks) - len(todo)

    # 2. Embed what's missing, outside any transaction.
    vectors: list[list[float]] = []
    for start in range(0, len(todo), EMBED_BATCH):
        batch = [t for _, _, t in todo[start : start + EMBED_BATCH]]
        vectors.extend(await embedder.embed(batch, InputType.DOCUMENT))

    # 3. Store, then mark ready only if every chunk has an embedding (embeddings.md #9).
    async with _tx(sm, workspace_id) as session:
        v = await _locked_with_lease(session, version_id, claim.run_id)
        if todo:
            stmt = insert(ChunkEmbedding).values(
                chunk_id=bindparam("chunk_id"),
                workspace_id=workspace_id,
                model=model,
                dims=embedder.dims,
                embedding=bindparam("embedding", type_=Vector()),
                content_hash=bindparam("content_hash"),
            )
            await session.execute(
                stmt,
                [
                    {"chunk_id": cid, "embedding": vec, "content_hash": h}
                    for (cid, h, _), vec in zip(todo, vectors, strict=True)
                ],
            )
        missing = await session.scalar(
            select(func.count())
            .select_from(Chunk)
            .where(
                Chunk.version_id == version_id,
                ~select(ChunkEmbedding.chunk_id)
                .where(ChunkEmbedding.chunk_id == Chunk.id, ChunkEmbedding.model == model)
                .exists(),
            )
        )
        if missing:
            raise EmbeddingError(f"{missing} chunks still have no {model} embedding")
        v.parse_report = {
            **v.parse_report,
            "embedding": {"model": model, "embedded": len(todo), "reused": reused},
        }
        v.pipeline_status = PipelineStatus.READY
        _release(v)
    return DONE


# --- failures ------------------------------------------------------------------------------


async def release_lease(
    sm: async_sessionmaker[AsyncSession], workspace_id: uuid.UUID, version_id: uuid.UUID
) -> None:
    """Before a retry: let the next attempt claim the version."""
    async with _tx(sm, workspace_id) as session:
        version = await _lock(session, version_id, skip_locked=False)
        if version is not None:
            _release(version)


async def record_failure(
    sm: async_sessionmaker[AsyncSession],
    workspace_id: uuid.UUID,
    version_id: uuid.UUID,
    *,
    task_name: str,
    error: str,
    attempts: int,
) -> None:
    """Dead-letter (ingestion.md #6): visible on the version, listed, retryable."""
    async with _tx(sm, workspace_id) as session:
        version = await _lock(session, version_id, skip_locked=False)
        if version is not None and version.status is VersionStatus.DRAFT:
            version.pipeline_status = PipelineStatus.FAILED
            version.pipeline_error = error[:2000]
            _release(version)
        session.add(
            JobFailure(
                id=uuid.uuid4(),
                workspace_id=workspace_id,
                task_name=task_name,
                version_id=version_id if version is not None else None,
                error=error[:4000],
                attempts=attempts,
                payload={"version_id": str(version_id)},
            )
        )


def backoff_seconds(attempt: int, base: float = 10.0, cap: float = 600.0) -> float:
    return min(cap, base * math.pow(2, attempt))
