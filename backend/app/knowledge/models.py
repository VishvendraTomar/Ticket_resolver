"""Knowledge-base tables. Constraints and RLS policies live in migration 0002."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, REGCONFIG, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, CreatedAt, UUIDPk


def _enum(cls: type[StrEnum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class JurisdictionLevel(StrEnum):
    GLOBAL = "global"
    REGION = "region"
    COUNTRY = "country"
    STATE = "state"


class VersionStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


class PipelineStatus(StrEnum):
    QUEUED = "queued"
    PARSING = "parsing"
    TAGGING = "tagging"
    AWAITING_REVIEW = "awaiting_review"
    EMBEDDING = "embedding"
    READY = "ready"
    FAILED = "failed"


class RelationKind(StrEnum):
    SUPERSEDES = "supersedes"
    SUPPLEMENTS = "supplements"


class Jurisdiction(Base):
    """Global reference tree (GLOBAL → region → country → state). Read-only for the app."""

    __tablename__ = "jurisdictions"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    parent_code: Mapped[str | None] = mapped_column(ForeignKey("jurisdictions.code"))
    level: Mapped[JurisdictionLevel] = mapped_column(_enum(JurisdictionLevel, "jurisdiction_level"))
    name: Mapped[str] = mapped_column(String(200))


class Topic(UUIDPk, CreatedAt, Base):
    __tablename__ = "topics"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    key: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)


class ScopeField(UUIDPk, CreatedAt, Base):
    """A custom dimension, e.g. worker_type ∈ {employee, contractor}."""

    __tablename__ = "scope_fields"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    key: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(100))
    allowed_values: Mapped[list[str]] = mapped_column(ARRAY(String(100)))


class Document(UUIDPk, CreatedAt, Base):
    __tablename__ = "documents"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    title: Mapped[str] = mapped_column(String(300))
    source: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(16), default="en")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class DocumentVersion(UUIDPk, CreatedAt, Base):
    __tablename__ = "document_versions"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    version_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[VersionStatus] = mapped_column(
        _enum(VersionStatus, "version_status"), default=VersionStatus.DRAFT
    )
    pipeline_status: Mapped[PipelineStatus] = mapped_column(
        _enum(PipelineStatus, "pipeline_status"), default=PipelineStatus.QUEUED
    )
    pipeline_error: Mapped[str | None] = mapped_column(Text)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    file_name: Mapped[str] = mapped_column(String(300))
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    file_hash: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(Text)
    parse_report: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    tag_suggestions: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    tags_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    jurisdiction_code: Mapped[str | None] = mapped_column(ForeignKey("jurisdictions.code"))
    scope: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    topic_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("topics.id"))
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class VersionRelation(UUIDPk, CreatedAt, Base):
    __tablename__ = "version_relations"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    from_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_versions.id"))
    to_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_versions.id"))
    kind: Mapped[RelationKind] = mapped_column(_enum(RelationKind, "version_relation_kind"))


class Section(UUIDPk, Base):
    __tablename__ = "sections"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_versions.id"))
    ordinal: Mapped[int] = mapped_column(Integer)
    heading_path: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    clause_number: Mapped[str | None] = mapped_column(String(50))
    title: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    has_table: Mapped[bool] = mapped_column(Boolean, default=False)
    page_start: Mapped[int | None] = mapped_column(Integer)
    jurisdiction_code: Mapped[str | None] = mapped_column(ForeignKey("jurisdictions.code"))
    scope: Mapped[dict[str, str] | None] = mapped_column(JSONB)
    topic_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("topics.id"))


class SectionRef(UUIDPk, Base):
    __tablename__ = "section_refs"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_versions.id"))
    from_section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sections.id"))
    target_text: Mapped[str] = mapped_column(String(200))
    to_section_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sections.id"))


class Chunk(UUIDPk, Base):
    __tablename__ = "chunks"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_versions.id"))
    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sections.id"))
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    context_header: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64))
    token_count: Mapped[int] = mapped_column(Integer)
    ts_config: Mapped[str] = mapped_column(REGCONFIG, default="simple")
    tsv: Mapped[str | None] = mapped_column(TSVECTOR)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    version_status: Mapped[VersionStatus] = mapped_column(
        _enum(VersionStatus, "version_status"), default=VersionStatus.DRAFT
    )
    jurisdiction_code: Mapped[str | None] = mapped_column(ForeignKey("jurisdictions.code"))
    scope: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    topic_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("topics.id"))
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"

    chunk_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chunks.id"), primary_key=True)
    model: Mapped[str] = mapped_column(String(100), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    dims: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list[float]] = mapped_column(Vector())
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GlossaryTerm(UUIDPk, CreatedAt, Base):
    __tablename__ = "glossary_terms"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    term: Mapped[str] = mapped_column(String(200))
    synonyms: Mapped[list[str]] = mapped_column(ARRAY(String(200)), default=list)
    language: Mapped[str | None] = mapped_column(String(16))


class JobFailure(UUIDPk, CreatedAt, Base):
    """Dead-letter record for an ingestion task that exhausted its retries (ADR-0007)."""

    __tablename__ = "job_failures"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    task_name: Mapped[str] = mapped_column(String(100))
    version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("document_versions.id"))
    error: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
