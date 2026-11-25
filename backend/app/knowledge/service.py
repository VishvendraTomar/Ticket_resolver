"""Knowledge-base use cases. Callers own the transaction; nothing here commits.

Everything runs as app_user under RLS (ADR-0002); explicit workspace filters
are a second layer. Failure modes: docs/failure-modes/ingestion.md, tagging.md.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, Forbidden, NotFound, Unprocessable
from app.knowledge.jurisdictions import JurisdictionTree, load_tree
from app.knowledge.models import (
    Chunk,
    Document,
    DocumentVersion,
    GlossaryTerm,
    JobFailure,
    Jurisdiction,
    PipelineStatus,
    RelationKind,
    ScopeField,
    Section,
    SectionRef,
    Topic,
    VersionRelation,
    VersionStatus,
)
from app.knowledge.schemas import PublishIn, TagConfirm
from app.knowledge.uploads import detect_mime, sha256, storage_key
from app.providers.storage.base import Storage
from app.tenancy.roles import Role
from app.tenancy.service import WorkspaceAccess, record_audit

EDITORS = frozenset({Role.OWNER, Role.ADMIN, Role.POLICY_EDITOR})
CONFIGURERS = frozenset({Role.OWNER, Role.ADMIN})


# --- Permissions ------------------------------------------------------------------------


def require_editor(access: WorkspaceAccess) -> None:
    if access.role not in EDITORS:
        raise Forbidden("Only owners, admins and policy editors can change the knowledge base")


def require_configurer(access: WorkspaceAccess) -> None:
    if access.role not in CONFIGURERS:
        raise Forbidden("Only owners and admins can change workspace configuration")


def require_jurisdictions(
    access: WorkspaceAccess, tree: JurisdictionTree, codes: list[str | None]
) -> None:
    """Restricted policy editors may only touch their jurisdictions (ingestion.md #14)."""
    if access.role is not Role.POLICY_EDITOR or access.jurisdiction_codes is None:
        return
    allowed = access.jurisdiction_codes
    for code in codes:
        if code is None or not any(tree.is_within(code, a) for a in allowed):
            raise Forbidden(
                f"You can only edit documents for: {', '.join(allowed)}"
                + (f" (this one is {code})" if code else " (this one has no jurisdiction yet)")
            )


# --- Reference data and configuration -------------------------------------------------


async def list_jurisdictions(session: AsyncSession) -> list[Jurisdiction]:
    return list((await session.scalars(select(Jurisdiction).order_by(Jurisdiction.code))).all())


async def list_topics(session: AsyncSession, access: WorkspaceAccess) -> list[Topic]:
    stmt = select(Topic).where(Topic.workspace_id == access.workspace_id).order_by(Topic.name)
    return list((await session.scalars(stmt)).all())


async def create_topic(
    session: AsyncSession, access: WorkspaceAccess, key: str, name: str, description: str | None
) -> Topic:
    require_configurer(access)
    topic = Topic(
        id=uuid.uuid4(),
        workspace_id=access.workspace_id,
        key=key,
        name=name,
        description=description,
    )
    session.add(topic)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise Conflict(f"A topic with key {key!r} already exists") from exc
    await record_audit(
        session,
        access.workspace_id,
        access.user.id,
        "topic.created",
        "topic",
        topic.id,
        {"key": key},
    )
    return topic


async def list_scope_fields(session: AsyncSession, access: WorkspaceAccess) -> list[ScopeField]:
    stmt = (
        select(ScopeField)
        .where(ScopeField.workspace_id == access.workspace_id)
        .order_by(ScopeField.key)
    )
    return list((await session.scalars(stmt)).all())


async def create_scope_field(
    session: AsyncSession, access: WorkspaceAccess, key: str, name: str, values: list[str]
) -> ScopeField:
    require_configurer(access)
    cleaned = sorted({v.strip() for v in values if v.strip()})
    if not cleaned or "*" in cleaned:
        raise Unprocessable("Allowed values must be non-empty and can't include '*'")
    field = ScopeField(
        id=uuid.uuid4(),
        workspace_id=access.workspace_id,
        key=key,
        name=name,
        allowed_values=cleaned,
    )
    session.add(field)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise Conflict(f"A scope field with key {key!r} already exists") from exc
    await record_audit(
        session,
        access.workspace_id,
        access.user.id,
        "scope_field.created",
        "scope_field",
        field.id,
        {"key": key, "values": cleaned},
    )
    return field


async def list_glossary(session: AsyncSession, access: WorkspaceAccess) -> list[GlossaryTerm]:
    stmt = (
        select(GlossaryTerm)
        .where(GlossaryTerm.workspace_id == access.workspace_id)
        .order_by(GlossaryTerm.term)
    )
    return list((await session.scalars(stmt)).all())


async def create_glossary_term(
    session: AsyncSession,
    access: WorkspaceAccess,
    term: str,
    synonyms: list[str],
    language: str | None,
) -> GlossaryTerm:
    require_editor(access)
    item = GlossaryTerm(
        id=uuid.uuid4(),
        workspace_id=access.workspace_id,
        term=term.strip(),
        synonyms=[s.strip() for s in synonyms if s.strip()],
        language=language,
    )
    session.add(item)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise Conflict(f"{term!r} is already in the glossary") from exc
    return item


async def delete_glossary_term(
    session: AsyncSession, access: WorkspaceAccess, term_id: uuid.UUID
) -> None:
    require_editor(access)
    result = await session.execute(
        delete(GlossaryTerm).where(
            GlossaryTerm.id == term_id, GlossaryTerm.workspace_id == access.workspace_id
        )
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise NotFound("Glossary term not found")


# --- Documents and uploads --------------------------------------------------------------


async def _store_upload(
    storage: Storage, access: WorkspaceAccess, data: bytes, file_name: str
) -> tuple[str, str, str]:
    mime = detect_mime(data, file_name)
    digest = sha256(data)
    key = storage_key(access.workspace_id, digest, mime)
    await storage.put(key, data, mime)
    return mime, digest, key


async def create_document(
    session: AsyncSession,
    storage: Storage,
    access: WorkspaceAccess,
    *,
    title: str,
    language: str,
    source: str | None,
    file_name: str,
    data: bytes,
) -> tuple[Document, DocumentVersion]:
    # Restricted editors may upload; the tags they confirm must stay inside their jurisdictions.
    require_editor(access)
    mime, digest, key = await _store_upload(storage, access, data, file_name)
    document = Document(
        id=uuid.uuid4(),
        workspace_id=access.workspace_id,
        title=title,
        source=source,
        language=language,
        created_by=access.user.id,
    )
    session.add(document)
    await session.flush()
    version = _new_version(access, document, 1, file_name, mime, len(data), digest, key)
    session.add(version)
    await session.flush()
    await record_audit(
        session,
        access.workspace_id,
        access.user.id,
        "document.created",
        "document",
        document.id,
        {"title": title, "version_id": str(version.id)},
    )
    return document, version


def _new_version(
    access: WorkspaceAccess,
    document: Document,
    number: int,
    file_name: str,
    mime: str,
    size: int,
    digest: str,
    key: str,
) -> DocumentVersion:
    return DocumentVersion(
        id=uuid.uuid4(),
        workspace_id=access.workspace_id,
        document_id=document.id,
        version_number=number,
        status=VersionStatus.DRAFT,
        pipeline_status=PipelineStatus.QUEUED,
        file_name=file_name[:300],
        mime_type=mime,
        size_bytes=size,
        file_hash=digest,
        storage_key=key,
        created_by=access.user.id,
        parse_report={},
        tag_suggestions={},
        scope={},
    )


async def add_version(
    session: AsyncSession,
    storage: Storage,
    access: WorkspaceAccess,
    document_id: uuid.UUID,
    *,
    file_name: str,
    data: bytes,
) -> DocumentVersion:
    require_editor(access)
    document = await get_document(session, access, document_id)
    latest = await session.scalar(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document.id)
        .order_by(DocumentVersion.version_number.desc())
        .limit(1)
    )
    if latest is not None and latest.jurisdiction_code:
        require_jurisdictions(access, await load_tree(session), [latest.jurisdiction_code])
    digest = sha256(data)
    existing = await session.scalar(
        select(DocumentVersion.id).where(
            DocumentVersion.document_id == document.id, DocumentVersion.file_hash == digest
        )
    )
    if existing is not None:
        # Identical bytes: don't store, parse or pay for it twice (ingestion.md #1).
        raise Conflict(
            "This exact file is already a version of this document",
            {"existing_version_id": str(existing)},
        )
    mime, digest, key = await _store_upload(storage, access, data, file_name)
    number = (latest.version_number if latest else 0) + 1
    version = _new_version(access, document, number, file_name, mime, len(data), digest, key)
    session.add(version)
    await session.flush()
    await record_audit(
        session,
        access.workspace_id,
        access.user.id,
        "version.created",
        "document_version",
        version.id,
        {"document_id": str(document.id), "version_number": number},
    )
    return version


async def list_documents(
    session: AsyncSession, access: WorkspaceAccess
) -> list[tuple[Document, int, DocumentVersion | None]]:
    documents = (
        await session.scalars(
            select(Document)
            .where(Document.workspace_id == access.workspace_id)
            .order_by(Document.created_at.desc())
        )
    ).all()
    versions = (
        await session.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.workspace_id == access.workspace_id)
            .order_by(DocumentVersion.version_number)
        )
    ).all()
    by_doc: dict[uuid.UUID, list[DocumentVersion]] = defaultdict(list)
    for v in versions:
        by_doc[v.document_id].append(v)
    return [(d, len(by_doc[d.id]), by_doc[d.id][-1] if by_doc[d.id] else None) for d in documents]


async def get_document(
    session: AsyncSession, access: WorkspaceAccess, document_id: uuid.UUID
) -> Document:
    document = await session.scalar(
        select(Document).where(
            Document.id == document_id, Document.workspace_id == access.workspace_id
        )
    )
    if document is None:
        raise NotFound("Document not found")
    return document


async def list_versions(session: AsyncSession, document: Document) -> list[DocumentVersion]:
    stmt = (
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document.id)
        .order_by(DocumentVersion.version_number.desc())
    )
    return list((await session.scalars(stmt)).all())


async def get_version(
    session: AsyncSession,
    access: WorkspaceAccess,
    version_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> DocumentVersion:
    stmt = select(DocumentVersion).where(
        DocumentVersion.id == version_id, DocumentVersion.workspace_id == access.workspace_id
    )
    if for_update:
        stmt = stmt.with_for_update()
    version = await session.scalar(stmt)
    if version is None:
        raise NotFound("Version not found")
    return version


async def version_relations(
    session: AsyncSession, version: DocumentVersion
) -> list[VersionRelation]:
    stmt = select(VersionRelation).where(VersionRelation.from_version_id == version.id)
    return list((await session.scalars(stmt)).all())


async def list_sections(
    session: AsyncSession, version: DocumentVersion
) -> list[tuple[Section, int, list[SectionRef]]]:
    sections = (
        await session.scalars(
            select(Section).where(Section.version_id == version.id).order_by(Section.ordinal)
        )
    ).all()
    counts = dict(
        (
            await session.execute(
                select(Chunk.section_id, func.count())
                .where(Chunk.version_id == version.id)
                .group_by(Chunk.section_id)
            )
        ).all()
    )
    refs = (
        await session.scalars(select(SectionRef).where(SectionRef.version_id == version.id))
    ).all()
    by_section: dict[uuid.UUID, list[SectionRef]] = defaultdict(list)
    for ref in refs:
        by_section[ref.from_section_id].append(ref)
    return [(s, counts.get(s.id, 0), by_section[s.id]) for s in sections]


# --- Tags (docs/failure-modes/tagging.md) ------------------------------------------------


async def _validate_scope(
    session: AsyncSession, access: WorkspaceAccess, scope: dict[str, str], where: str
) -> None:
    fields = {f.key: f.allowed_values for f in await list_scope_fields(session, access)}
    for key, value in scope.items():
        if key not in fields:
            raise Unprocessable(f"{where}: unknown scope field {key!r}")
        if value != "*" and value not in fields[key]:
            raise Unprocessable(
                f"{where}: {key}={value!r} is not allowed (allowed: {', '.join(fields[key])}, *)"
            )


async def _validate_topic(
    session: AsyncSession, access: WorkspaceAccess, topic_id: uuid.UUID | None, where: str
) -> None:
    if topic_id is None:
        return
    found = await session.scalar(
        select(Topic.id).where(Topic.id == topic_id, Topic.workspace_id == access.workspace_id)
    )
    if found is None:
        raise Unprocessable(f"{where}: unknown topic")


async def confirm_tags(
    session: AsyncSession, access: WorkspaceAccess, version_id: uuid.UUID, body: TagConfirm
) -> DocumentVersion:
    """A human confirms (and corrects) the tags. Only this makes tags count (tagging.md #1)."""
    require_editor(access)
    version = await get_version(session, access, version_id, for_update=True)
    if version.status is not VersionStatus.DRAFT:
        raise Conflict("Published or retired versions can't be re-tagged; upload a new version")
    if version.pipeline_status not in (
        PipelineStatus.AWAITING_REVIEW,
        PipelineStatus.READY,
        PipelineStatus.FAILED,
    ):
        raise Conflict(f"The version is still being processed ({version.pipeline_status})")
    if (
        version.pipeline_status is PipelineStatus.FAILED
        and version.tags_confirmed_at is None
        and not version.parse_report
    ):
        raise Conflict("The version failed before it was parsed; retry it first")

    tree = await load_tree(session)
    if body.jurisdiction_code not in tree:
        raise Unprocessable(f"Unknown jurisdiction {body.jurisdiction_code!r}")
    if body.effective_to is not None and body.effective_to <= body.effective_from:
        raise Unprocessable("effective_to must be after effective_from")
    await _validate_scope(session, access, body.scope, "document")
    await _validate_topic(session, access, body.topic_id, "document")

    sections = {
        s.id: s
        for s in (await session.scalars(select(Section).where(Section.version_id == version.id)))
    }
    codes: list[str | None] = [body.jurisdiction_code]
    for item in body.sections:
        section = sections.get(item.section_id)
        if section is None:
            raise Unprocessable(f"Section {item.section_id} is not part of this version")
        where = f"section {section.ordinal + 1}"
        if item.jurisdiction_code is not None:
            if item.jurisdiction_code not in tree:
                raise Unprocessable(f"{where}: unknown jurisdiction {item.jurisdiction_code!r}")
            if not tree.is_within(item.jurisdiction_code, body.jurisdiction_code):
                # A country annex can narrow a global policy, never step outside it (#7).
                raise Unprocessable(
                    f"{where}: {item.jurisdiction_code} is not within the document's "
                    f"jurisdiction {body.jurisdiction_code}"
                )
            codes.append(item.jurisdiction_code)
        if item.scope is not None:
            await _validate_scope(session, access, item.scope, where)
        await _validate_topic(session, access, item.topic_id, where)
    require_jurisdictions(access, tree, codes)

    for section in sections.values():
        section.jurisdiction_code = None
        section.scope = None
        section.topic_id = None
    for item in body.sections:
        section = sections[item.section_id]
        section.jurisdiction_code = item.jurisdiction_code
        section.scope = item.scope
        section.topic_id = item.topic_id

    version.jurisdiction_code = body.jurisdiction_code
    version.scope = body.scope
    version.topic_id = body.topic_id
    version.effective_from = body.effective_from
    version.effective_to = body.effective_to
    version.tags_confirmed_at = datetime.now(UTC)
    version.pipeline_status = PipelineStatus.EMBEDDING
    version.pipeline_error = None
    await session.flush()
    await record_audit(
        session,
        access.workspace_id,
        access.user.id,
        "version.tags_confirmed",
        "document_version",
        version.id,
        {
            "jurisdiction": body.jurisdiction_code,
            "scope": body.scope,
            "sections_tagged": len(body.sections),
        },
    )
    return version


# --- Publish / retire (docs/failure-modes/ingestion.md #8–#13) -----------------------------


def _effective(section: Section, version: DocumentVersion) -> tuple[str | None, uuid.UUID | None]:
    return (
        section.jurisdiction_code or version.jurisdiction_code,
        section.topic_id or version.topic_id,
    )


def _dates_overlap(
    a_from: date | None, a_to: date | None, b_from: date | None, b_to: date | None
) -> bool:
    lo = max(a_from or date.min, b_from or date.min)
    hi = min(a_to or date.max, b_to or date.max)
    return lo < hi


async def contradiction_candidates(
    session: AsyncSession, access: WorkspaceAccess, version: DocumentVersion
) -> list[dict[str, Any]]:
    """Same topic, overlapping jurisdiction chain and dates, in another published document.

    Cheap and deterministic (PLAN §4.9); an LLM check on these pairs comes in M4.
    """
    tree = await load_tree(session)
    mine = (await session.scalars(select(Section).where(Section.version_id == version.id))).all()
    others = (
        await session.execute(
            select(Section, DocumentVersion, Document.title)
            .join(DocumentVersion, DocumentVersion.id == Section.version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(
                DocumentVersion.workspace_id == access.workspace_id,
                DocumentVersion.status == VersionStatus.PUBLISHED,
                DocumentVersion.document_id != version.document_id,
            )
        )
    ).all()
    candidates: list[dict[str, Any]] = []
    for section in mine:
        code, topic = _effective(section, version)
        if code is None or topic is None:
            continue
        for other, other_version, title in others:
            other_code, other_topic = _effective(other, other_version)
            if (
                other_topic == topic
                and other_code is not None
                and tree.overlaps(code, other_code)
                and _dates_overlap(
                    version.effective_from,
                    version.effective_to,
                    other_version.effective_from,
                    other_version.effective_to,
                )
            ):
                candidates.append(
                    {
                        "section_id": str(section.id),
                        "section": " › ".join(section.heading_path) or section.title,
                        "jurisdiction": code,
                        "other_document": title,
                        "other_version_id": str(other_version.id),
                        "other_section_id": str(other.id),
                        "other_section": " › ".join(other.heading_path) or other.title,
                        "other_jurisdiction": other_code,
                        "topic_id": str(topic),
                    }
                )
    return candidates


async def sync_chunks(session: AsyncSession, version: DocumentVersion) -> None:
    """Copy version-level fields onto its chunks (ingestion.md #11). Same transaction."""
    await session.execute(
        update(Chunk)
        .where(Chunk.version_id == version.id)
        .values(
            version_status=version.status,
            effective_from=version.effective_from,
            effective_to=version.effective_to,
        )
    )


async def publish(
    session: AsyncSession, access: WorkspaceAccess, version_id: uuid.UUID, body: PublishIn
) -> tuple[DocumentVersion, list[dict[str, Any]]]:
    require_editor(access)
    version = await get_version(session, access, version_id, for_update=True)
    if version.status is not VersionStatus.DRAFT:
        raise Conflict(f"Only drafts can be published (this version is {version.status})")
    if version.pipeline_status is not PipelineStatus.READY:
        raise Conflict(
            f"The version isn't ready to publish ({version.pipeline_status}): parsing, tag "
            "review and embedding must finish first"
        )
    if version.jurisdiction_code is None or version.effective_from is None:
        raise Unprocessable("A jurisdiction and an effective-from date are required to publish")
    tree = await load_tree(session)
    require_jurisdictions(access, tree, [version.jurisdiction_code])

    candidates = await contradiction_candidates(session, access, version)
    if candidates and not body.acknowledge_conflicts:
        raise Conflict(
            "Other published documents cover the same topic for overlapping jurisdictions "
            "and dates. Review them, then publish with acknowledge_conflicts=true.",
            {"candidates": candidates},
        )

    # A newer version of the same rule closes the open-ended previous one (audited).
    previous = (
        await session.scalars(
            select(DocumentVersion)
            .where(
                DocumentVersion.document_id == version.document_id,
                DocumentVersion.status == VersionStatus.PUBLISHED,
                DocumentVersion.jurisdiction_code == version.jurisdiction_code,
                DocumentVersion.scope == version.scope,
                DocumentVersion.effective_to.is_(None),
                DocumentVersion.effective_from < version.effective_from,
            )
            .with_for_update()
        )
    ).all()
    for old in previous:
        old.effective_to = version.effective_from
        await session.flush()
        await sync_chunks(session, old)
        await record_audit(
            session,
            access.workspace_id,
            access.user.id,
            "version.closed",
            "document_version",
            old.id,
            {"effective_to": version.effective_from.isoformat(), "by_version_id": str(version.id)},
        )

    version.status = VersionStatus.PUBLISHED
    version.published_at = datetime.now(UTC)
    version.published_by = access.user.id
    try:
        await session.flush()
    except IntegrityError as exc:
        raise Conflict(
            "Another published version of this document already covers these dates for the "
            "same jurisdiction and scope. Set an end date on one of them first."
        ) from exc
    await sync_chunks(session, version)

    for kind, ids in (
        (RelationKind.SUPERSEDES, body.supersedes),
        (RelationKind.SUPPLEMENTS, body.supplements),
    ):
        for target in ids:
            if target == version.id:
                raise Unprocessable("A version can't relate to itself")
            await get_version(session, access, target)  # 404 if not in this workspace
            session.add(
                VersionRelation(
                    id=uuid.uuid4(),
                    workspace_id=access.workspace_id,
                    from_version_id=version.id,
                    to_version_id=target,
                    kind=kind,
                )
            )
    await session.flush()
    await record_audit(
        session,
        access.workspace_id,
        access.user.id,
        "version.published",
        "document_version",
        version.id,
        {
            "acknowledged_conflicts": len(candidates),
            "closed_versions": [str(o.id) for o in previous],
        },
    )
    return version, candidates


async def retire(
    session: AsyncSession, access: WorkspaceAccess, version_id: uuid.UUID
) -> DocumentVersion:
    require_editor(access)
    version = await get_version(session, access, version_id, for_update=True)
    if version.status is not VersionStatus.PUBLISHED:
        raise Conflict("Only published versions can be retired")
    require_jurisdictions(access, await load_tree(session), [version.jurisdiction_code])
    version.status = VersionStatus.RETIRED
    await session.flush()
    await sync_chunks(session, version)
    await record_audit(
        session,
        access.workspace_id,
        access.user.id,
        "version.retired",
        "document_version",
        version.id,
        {},
    )
    return version


async def prepare_retry(
    session: AsyncSession, access: WorkspaceAccess, version_id: uuid.UUID
) -> tuple[DocumentVersion, str]:
    """Reset a failed version; returns which task to queue ("ingest" or "embed")."""
    require_editor(access)
    version = await get_version(session, access, version_id, for_update=True)
    if version.pipeline_status is not PipelineStatus.FAILED:
        raise Conflict(f"Only failed versions can be retried ({version.pipeline_status})")
    task = "embed" if version.tags_confirmed_at is not None else "ingest"
    version.pipeline_status = PipelineStatus.EMBEDDING if task == "embed" else PipelineStatus.QUEUED
    version.pipeline_error = None
    version.pipeline_run_id = None
    version.pipeline_lease_until = None
    await session.execute(
        update(JobFailure)
        .where(JobFailure.version_id == version.id, JobFailure.resolved_at.is_(None))
        .values(resolved_at=datetime.now(UTC))
    )
    await session.flush()
    await record_audit(
        session,
        access.workspace_id,
        access.user.id,
        "version.retried",
        "document_version",
        version.id,
        {"task": task},
    )
    return version, task


# --- Coverage and failures ------------------------------------------------------------------


async def coverage(
    session: AsyncSession, access: WorkspaceAccess
) -> tuple[list[Jurisdiction], list[Topic], list[tuple[str, uuid.UUID | None, int, int]]]:
    """Published sections per jurisdiction and topic, from confirmed tags (ingestion.md #15)."""
    code = func.coalesce(Section.jurisdiction_code, DocumentVersion.jurisdiction_code)
    topic = func.coalesce(Section.topic_id, DocumentVersion.topic_id)
    rows = (
        await session.execute(
            select(
                code,
                topic,
                func.count(Section.id),
                func.count(func.distinct(DocumentVersion.document_id)),
            )
            .join(DocumentVersion, DocumentVersion.id == Section.version_id)
            .where(
                DocumentVersion.workspace_id == access.workspace_id,
                DocumentVersion.status == VersionStatus.PUBLISHED,
            )
            .group_by(code, topic)
        )
    ).all()
    cells: list[tuple[str, uuid.UUID | None, int, int]] = [
        (str(r[0]), r[1], int(r[2]), int(r[3])) for r in rows if r[0] is not None
    ]
    used = {c[0] for c in cells}
    drafts = (
        await session.scalars(
            select(DocumentVersion.jurisdiction_code).where(
                DocumentVersion.workspace_id == access.workspace_id,
                DocumentVersion.jurisdiction_code.is_not(None),
            )
        )
    ).all()
    used |= {c for c in drafts if c}
    tree = await load_tree(session)
    shown = set()
    for c in used:
        shown.update(tree.chain(c))
    jurisdictions = (
        await session.scalars(
            select(Jurisdiction).where(Jurisdiction.code.in_(shown or {"GLOBAL"}))
        )
    ).all()
    order = {"global": 0, "region": 1, "country": 2, "state": 3}
    ordered = sorted(jurisdictions, key=lambda j: (order[j.level.value], j.code))
    return ordered, await list_topics(session, access), cells


async def list_job_failures(session: AsyncSession, access: WorkspaceAccess) -> list[JobFailure]:
    require_editor(access)
    stmt = (
        select(JobFailure)
        .where(JobFailure.workspace_id == access.workspace_id)
        .order_by(JobFailure.created_at.desc())
        .limit(200)
    )
    return list((await session.scalars(stmt)).all())


# --- Embedding model switch (docs/failure-modes/embeddings.md #3) ------------------------------


async def activate_embedding_model(
    session: AsyncSession, access: WorkspaceAccess, model: str
) -> None:
    """Switch the model searches use, only once it covers every chunk of every live version."""
    require_configurer(access)
    from app.knowledge.models import ChunkEmbedding
    from app.tenancy.models import Workspace

    missing = await session.scalar(
        select(func.count())
        .select_from(Chunk)
        .where(
            Chunk.workspace_id == access.workspace_id,
            Chunk.version_status == VersionStatus.PUBLISHED,
            ~select(ChunkEmbedding.chunk_id)
            .where(ChunkEmbedding.chunk_id == Chunk.id, ChunkEmbedding.model == model)
            .exists(),
        )
    )
    if missing:
        raise Conflict(
            f"{missing} published chunks have no {model} embedding yet; re-embed them first",
            {"missing": int(missing)},
        )
    workspace = await session.get_one(Workspace, access.workspace_id)
    previous = workspace.active_embedding_model
    workspace.active_embedding_model = model
    await session.flush()
    await record_audit(
        session,
        access.workspace_id,
        access.user.id,
        "embedding_model.activated",
        "workspace",
        access.workspace_id,
        {"from": previous, "to": model},
    )
