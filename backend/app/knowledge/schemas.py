"""API schemas for the knowledge base."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.knowledge.models import JurisdictionLevel, PipelineStatus, VersionStatus

KEY_PATTERN = r"^[a-z][a-z0-9_]*$"


class JurisdictionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    parent_code: str | None
    level: JurisdictionLevel
    name: str


class TopicOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    name: str
    description: str | None


class TopicCreate(BaseModel):
    key: str = Field(pattern=KEY_PATTERN, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)


class ScopeFieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    name: str
    allowed_values: list[str]


class ScopeFieldCreate(BaseModel):
    key: str = Field(pattern=KEY_PATTERN, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    allowed_values: list[str] = Field(min_length=1, max_length=100)


class GlossaryTermOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    term: str
    synonyms: list[str]
    language: str | None


class GlossaryTermCreate(BaseModel):
    term: str = Field(min_length=1, max_length=200)
    synonyms: list[str] = Field(default_factory=list, max_length=50)
    language: str | None = Field(default=None, max_length=16)


class VersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    version_number: int
    status: VersionStatus
    pipeline_status: PipelineStatus
    pipeline_error: str | None
    needs_review: bool
    file_name: str
    mime_type: str
    size_bytes: int
    jurisdiction_code: str | None
    scope: dict[str, str]
    topic_id: uuid.UUID | None
    effective_from: date | None
    effective_to: date | None
    tags_confirmed_at: datetime | None
    created_at: datetime
    published_at: datetime | None


class RelationOut(BaseModel):
    to_version_id: uuid.UUID
    kind: str


class VersionDetail(VersionSummary):
    parse_report: dict[str, Any]
    tag_suggestions: dict[str, Any]
    relations: list[RelationOut] = Field(default_factory=list)


class DocumentOut(BaseModel):
    id: uuid.UUID
    title: str
    source: str | None
    language: str
    created_at: datetime
    version_count: int
    latest_version: VersionSummary | None


class DocumentDetail(BaseModel):
    id: uuid.UUID
    title: str
    source: str | None
    language: str
    created_at: datetime
    versions: list[VersionSummary]


class SectionRefOut(BaseModel):
    target_text: str
    to_section_id: uuid.UUID | None


class SectionOut(BaseModel):
    id: uuid.UUID
    ordinal: int
    heading_path: list[str]
    clause_number: str | None
    title: str | None
    text: str
    token_count: int
    has_table: bool
    page_start: int | None
    jurisdiction_code: str | None
    scope: dict[str, str] | None
    topic_id: uuid.UUID | None
    chunk_count: int
    refs: list[SectionRefOut]


class SectionTagIn(BaseModel):
    section_id: uuid.UUID
    # null = inherit the version's value
    jurisdiction_code: str | None = None
    scope: dict[str, str] | None = None
    topic_id: uuid.UUID | None = None


class TagConfirm(BaseModel):
    """The editor's confirmed tags (suggestions are never applied without this)."""

    jurisdiction_code: str
    scope: dict[str, str] = Field(default_factory=dict)
    topic_id: uuid.UUID | None = None
    effective_from: date
    effective_to: date | None = None
    sections: list[SectionTagIn] = Field(default_factory=list, max_length=5000)


class PublishIn(BaseModel):
    acknowledge_conflicts: bool = False
    supersedes: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    supplements: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class CoverageCell(BaseModel):
    jurisdiction_code: str
    topic_id: uuid.UUID | None
    sections: int
    documents: int


class CoverageOut(BaseModel):
    jurisdictions: list[JurisdictionOut]
    topics: list[TopicOut]
    cells: list[CoverageCell]


class JobFailureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_name: str
    version_id: uuid.UUID | None
    error: str
    attempts: int
    created_at: datetime
    resolved_at: datetime | None
