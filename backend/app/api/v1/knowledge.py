"""Routes: knowledge base (jurisdictions, topics, scope fields, glossary, documents,
versions, coverage, job failures). Routers only; logic lives in app/knowledge.

Jobs are queued only after the transaction that created their rows commits, so a
worker never looks for a version that isn't visible yet.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile, status

from app.core.config import get_settings
from app.knowledge import service
from app.knowledge.models import Document, DocumentVersion
from app.knowledge.schemas import (
    CoverageCell,
    CoverageOut,
    DocumentDetail,
    DocumentOut,
    GlossaryTermCreate,
    GlossaryTermOut,
    JobFailureOut,
    JurisdictionOut,
    PublishIn,
    RelationOut,
    ScopeFieldCreate,
    ScopeFieldOut,
    SectionOut,
    SectionRefOut,
    TagConfirm,
    TopicCreate,
    TopicOut,
    VersionDetail,
    VersionSummary,
)
from app.knowledge.uploads import check_size
from app.providers.storage import get_storage
from app.tenancy.deps import Access, SessionDep
from workers.tasks import enqueue_embed, enqueue_ingest

router = APIRouter(prefix="/workspaces/{workspace_id}")

WS = "knowledge"


async def _read_upload(file: UploadFile) -> bytes:
    max_mb = get_settings().max_upload_mb
    data = await file.read(max_mb * 1024 * 1024 + 1)  # never read more than the limit + 1
    check_size(data, max_mb)
    return data


# --- Reference and configuration ----------------------------------------------------------


@router.get("/jurisdictions", response_model=list[JurisdictionOut], tags=[WS])
async def list_jurisdictions(session: SessionDep, access: Access) -> list[JurisdictionOut]:
    return [JurisdictionOut.model_validate(j) for j in await service.list_jurisdictions(session)]


@router.get("/topics", response_model=list[TopicOut], tags=[WS])
async def list_topics(session: SessionDep, access: Access) -> list[TopicOut]:
    return [TopicOut.model_validate(t) for t in await service.list_topics(session, access)]


@router.post("/topics", response_model=TopicOut, status_code=status.HTTP_201_CREATED, tags=[WS])
async def create_topic(body: TopicCreate, session: SessionDep, access: Access) -> TopicOut:
    topic = await service.create_topic(session, access, body.key, body.name, body.description)
    out = TopicOut.model_validate(topic)
    await session.commit()
    return out


@router.get("/scope-fields", response_model=list[ScopeFieldOut], tags=[WS])
async def list_scope_fields(session: SessionDep, access: Access) -> list[ScopeFieldOut]:
    fields = await service.list_scope_fields(session, access)
    return [ScopeFieldOut.model_validate(f) for f in fields]


@router.post(
    "/scope-fields", response_model=ScopeFieldOut, status_code=status.HTTP_201_CREATED, tags=[WS]
)
async def create_scope_field(
    body: ScopeFieldCreate, session: SessionDep, access: Access
) -> ScopeFieldOut:
    field = await service.create_scope_field(
        session, access, body.key, body.name, body.allowed_values
    )
    out = ScopeFieldOut.model_validate(field)
    await session.commit()
    return out


@router.get("/glossary", response_model=list[GlossaryTermOut], tags=[WS])
async def list_glossary(session: SessionDep, access: Access) -> list[GlossaryTermOut]:
    return [GlossaryTermOut.model_validate(t) for t in await service.list_glossary(session, access)]


@router.post(
    "/glossary", response_model=GlossaryTermOut, status_code=status.HTTP_201_CREATED, tags=[WS]
)
async def create_glossary_term(
    body: GlossaryTermCreate, session: SessionDep, access: Access
) -> GlossaryTermOut:
    term = await service.create_glossary_term(
        session, access, body.term, body.synonyms, body.language
    )
    out = GlossaryTermOut.model_validate(term)
    await session.commit()
    return out


@router.delete("/glossary/{term_id}", status_code=status.HTTP_204_NO_CONTENT, tags=[WS])
async def delete_glossary_term(term_id: uuid.UUID, session: SessionDep, access: Access) -> None:
    await service.delete_glossary_term(session, access, term_id)
    await session.commit()


# --- Documents and versions ---------------------------------------------------------------


def _summary(v: DocumentVersion) -> VersionSummary:
    return VersionSummary.model_validate(v)


def _document_out(d: Document, count: int, latest: DocumentVersion | None) -> DocumentOut:
    return DocumentOut(
        id=d.id,
        title=d.title,
        source=d.source,
        language=d.language,
        created_at=d.created_at,
        version_count=count,
        latest_version=_summary(latest) if latest else None,
    )


@router.get("/documents", response_model=list[DocumentOut], tags=[WS])
async def list_documents(session: SessionDep, access: Access) -> list[DocumentOut]:
    return [_document_out(*row) for row in await service.list_documents(session, access)]


@router.post(
    "/documents", response_model=DocumentDetail, status_code=status.HTTP_201_CREATED, tags=[WS]
)
async def create_document(
    session: SessionDep,
    access: Access,
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form(min_length=1, max_length=300)],
    language: Annotated[str, Form(min_length=2, max_length=16)] = "en",
    source: Annotated[str | None, Form(max_length=2000)] = None,
) -> DocumentDetail:
    data = await _read_upload(file)
    document, version = await service.create_document(
        session,
        get_storage(),
        access,
        title=title.strip(),
        language=language,
        source=source,
        file_name=file.filename or "upload",
        data=data,
    )
    out = DocumentDetail(
        id=document.id,
        title=document.title,
        source=document.source,
        language=document.language,
        created_at=document.created_at,
        versions=[_summary(version)],
    )
    await session.commit()
    enqueue_ingest(access.workspace_id, version.id)
    return out


@router.get("/documents/{document_id}", response_model=DocumentDetail, tags=[WS])
async def get_document(
    document_id: uuid.UUID, session: SessionDep, access: Access
) -> DocumentDetail:
    document = await service.get_document(session, access, document_id)
    versions = await service.list_versions(session, document)
    return DocumentDetail(
        id=document.id,
        title=document.title,
        source=document.source,
        language=document.language,
        created_at=document.created_at,
        versions=[_summary(v) for v in versions],
    )


@router.post(
    "/documents/{document_id}/versions",
    response_model=VersionSummary,
    status_code=status.HTTP_201_CREATED,
    tags=[WS],
)
async def add_version(
    document_id: uuid.UUID,
    session: SessionDep,
    access: Access,
    file: Annotated[UploadFile, File()],
) -> VersionSummary:
    data = await _read_upload(file)
    version = await service.add_version(
        session, get_storage(), access, document_id, file_name=file.filename or "upload", data=data
    )
    out = _summary(version)
    await session.commit()
    enqueue_ingest(access.workspace_id, version.id)
    return out


async def _detail(session: SessionDep, version: DocumentVersion) -> VersionDetail:
    relations = await service.version_relations(session, version)
    return VersionDetail(
        **_summary(version).model_dump(),
        parse_report=version.parse_report,
        tag_suggestions=version.tag_suggestions,
        relations=[RelationOut(to_version_id=r.to_version_id, kind=r.kind) for r in relations],
    )


@router.get("/versions/{version_id}", response_model=VersionDetail, tags=[WS])
async def get_version(version_id: uuid.UUID, session: SessionDep, access: Access) -> VersionDetail:
    return await _detail(session, await service.get_version(session, access, version_id))


@router.get("/versions/{version_id}/sections", response_model=list[SectionOut], tags=[WS])
async def list_sections(
    version_id: uuid.UUID, session: SessionDep, access: Access
) -> list[SectionOut]:
    version = await service.get_version(session, access, version_id)
    return [
        SectionOut(
            id=s.id,
            ordinal=s.ordinal,
            heading_path=s.heading_path,
            clause_number=s.clause_number,
            title=s.title,
            text=s.text,
            token_count=s.token_count,
            has_table=s.has_table,
            page_start=s.page_start,
            jurisdiction_code=s.jurisdiction_code,
            scope=s.scope,
            topic_id=s.topic_id,
            chunk_count=count,
            refs=[
                SectionRefOut(target_text=r.target_text, to_section_id=r.to_section_id)
                for r in refs
            ],
        )
        for s, count, refs in await service.list_sections(session, version)
    ]


@router.put("/versions/{version_id}/tags", response_model=VersionDetail, tags=[WS])
async def confirm_tags(
    version_id: uuid.UUID, body: TagConfirm, session: SessionDep, access: Access
) -> VersionDetail:
    version = await service.confirm_tags(session, access, version_id, body)
    out = await _detail(session, version)
    await session.commit()
    enqueue_embed(access.workspace_id, version.id)
    return out


@router.post("/versions/{version_id}/publish", response_model=VersionDetail, tags=[WS])
async def publish_version(
    version_id: uuid.UUID, body: PublishIn, session: SessionDep, access: Access
) -> VersionDetail:
    version, _ = await service.publish(session, access, version_id, body)
    out = await _detail(session, version)
    await session.commit()
    return out


@router.post("/versions/{version_id}/retire", response_model=VersionDetail, tags=[WS])
async def retire_version(
    version_id: uuid.UUID, session: SessionDep, access: Access
) -> VersionDetail:
    version = await service.retire(session, access, version_id)
    out = await _detail(session, version)
    await session.commit()
    return out


@router.post("/versions/{version_id}/retry", response_model=VersionDetail, tags=[WS])
async def retry_version(
    version_id: uuid.UUID, session: SessionDep, access: Access
) -> VersionDetail:
    version, task = await service.prepare_retry(session, access, version_id)
    out = await _detail(session, version)
    await session.commit()
    (enqueue_embed if task == "embed" else enqueue_ingest)(access.workspace_id, version.id)
    return out


# --- Coverage and failures ------------------------------------------------------------------


@router.get("/coverage", response_model=CoverageOut, tags=[WS])
async def get_coverage(session: SessionDep, access: Access) -> CoverageOut:
    jurisdictions, topics, cells = await service.coverage(session, access)
    return CoverageOut(
        jurisdictions=[JurisdictionOut.model_validate(j) for j in jurisdictions],
        topics=[TopicOut.model_validate(t) for t in topics],
        cells=[
            CoverageCell(jurisdiction_code=c, topic_id=t, sections=n, documents=d)
            for c, t, n, d in cells
        ],
    )


@router.get("/job-failures", response_model=list[JobFailureOut], tags=[WS])
async def list_job_failures(session: SessionDep, access: Access) -> list[JobFailureOut]:
    failures = await service.list_job_failures(session, access)
    return [JobFailureOut.model_validate(f) for f in failures]
