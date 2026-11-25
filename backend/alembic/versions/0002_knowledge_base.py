"""Knowledge base: jurisdictions, topics, scope fields, documents, versions,
sections, chunks, embeddings, glossary, job failures.

Revision ID: 0002_knowledge_base
Revises: 0001_tenancy_rls
Create Date: 2026-11-25

Design: SPEC §6, PLAN M2 and §4.2/4.4/4.6/4.12, ADR-0002 (RLS), ADR-0006/0007.
Constraints that make bad states impossible (SPEC §6):
- two published versions of the same document, jurisdiction and scope can't
  overlap in time (EXCLUDE USING gist);
- nothing is published without a jurisdiction and a start date (CHECK);
- sections, chunks and embeddings can't outlive their version (CASCADE).
"""

import csv
import re
from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0002_knowledge_base"
down_revision: str | None = "0001_tenancy_rls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"
JURISDICTIONS_CSV = Path(__file__).resolve().parents[2] / "app/knowledge/data/jurisdictions.csv"

# Model key of the production embedding model; one partial HNSW index per model.
VERTEX_768 = "vertex/gemini-embedding-001@768"

DEFAULT_TOPICS = [
    ("leave", "Annual leave"),
    ("sick_pay", "Sick leave and sick pay"),
    ("parental_leave", "Parental leave"),
    ("notice_period", "Notice periods"),
    ("payroll", "Payroll and pay dates"),
    ("expenses", "Expenses and reimbursements"),
    ("working_time", "Working time and overtime"),
    ("public_holidays", "Public holidays"),
    ("benefits", "Benefits"),
    ("remote_work", "Remote work"),
]

TENANT_TABLES = [
    "topics",
    "scope_fields",
    "documents",
    "document_versions",
    "version_relations",
    "sections",
    "section_refs",
    "chunks",
    "chunk_embeddings",
    "glossary_terms",
    "job_failures",
]


def _run_all(sql: str) -> None:
    """Run a script one statement at a time (see 0001 for the ';' rule)."""
    for statement in re.split(r";[ \t]*\n", sql):
        if statement.strip():
            if statement.count("$$") % 2:
                raise RuntimeError(f"Split inside a $$ body; keep ';' mid-line:\n{statement}")
            op.execute(statement)


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    _run_all("""
        CREATE EXTENSION IF NOT EXISTS vector;
        CREATE EXTENSION IF NOT EXISTS btree_gist;

        CREATE TYPE jurisdiction_level AS ENUM ('global', 'region', 'country', 'state');
        CREATE TYPE version_status AS ENUM ('draft', 'published', 'retired');
        CREATE TYPE pipeline_status AS ENUM
            ('queued', 'parsing', 'tagging', 'awaiting_review', 'embedding', 'ready', 'failed');
        CREATE TYPE version_relation_kind AS ENUM ('supersedes', 'supplements');
    """)

    # --- Reference data (global, read-only for the app) -------------------------------
    _run_all("""
        CREATE TABLE jurisdictions (
            code         varchar(16) PRIMARY KEY,
            parent_code  varchar(16) REFERENCES jurisdictions(code),
            level        jurisdiction_level NOT NULL,
            name         varchar(200) NOT NULL,
            CONSTRAINT ck_jurisdictions_root CHECK ((level = 'global') = (parent_code IS NULL))
        );
        CREATE INDEX ix_jurisdictions_parent_code ON jurisdictions (parent_code);
    """)
    with JURISDICTIONS_CSV.open(newline="") as f:
        rows = list(csv.DictReader(f))

    # Parents first (the CSV is ordered: GLOBAL, EU, countries, states).
    def _row(r: dict[str, str]) -> str:
        parent = _sql_literal(r["parent_code"]) if r["parent_code"] else "NULL"
        code, level, name = (_sql_literal(r[k]) for k in ("code", "level", "name"))
        return f"({code}, {parent}, {level}, {name})"

    values = ",\n".join(_row(r) for r in rows)
    op.execute(f"INSERT INTO jurisdictions (code, parent_code, level, name) VALUES {values}")

    # --- Workspace and membership additions ---------------------------------------------
    _run_all("""
        -- NULL = the deployment default (settings); set when a workspace switches model.
        ALTER TABLE workspaces ADD COLUMN active_embedding_model varchar(100);
        -- Policy editors may be limited to these jurisdictions (and their descendants).
        ALTER TABLE memberships ADD COLUMN jurisdiction_codes varchar(16)[];
    """)

    # --- Tenant tables --------------------------------------------------------------------
    _run_all("""
        CREATE TABLE topics (
            id            uuid PRIMARY KEY,
            workspace_id  uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            key           varchar(50) NOT NULL,
            name          varchar(100) NOT NULL,
            description   text,
            created_at    timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_topics_workspace_key UNIQUE (workspace_id, key),
            CONSTRAINT ck_topics_key CHECK (key ~ '^[a-z][a-z0-9_]*$')
        );

        CREATE TABLE scope_fields (
            id            uuid PRIMARY KEY,
            workspace_id  uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            key           varchar(50) NOT NULL,
            name          varchar(100) NOT NULL,
            allowed_values varchar(100)[] NOT NULL,
            created_at    timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_scope_fields_workspace_key UNIQUE (workspace_id, key),
            CONSTRAINT ck_scope_fields_key CHECK (key ~ '^[a-z][a-z0-9_]*$'),
            CONSTRAINT ck_scope_fields_values CHECK (cardinality(allowed_values) > 0)
        );

        CREATE TABLE documents (
            id            uuid PRIMARY KEY,
            workspace_id  uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            title         varchar(300) NOT NULL,
            source        text,
            language      varchar(16) NOT NULL DEFAULT 'en',
            created_by    uuid REFERENCES users(id),
            created_at    timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_documents_workspace_id ON documents (workspace_id);

        CREATE TABLE document_versions (
            id                 uuid PRIMARY KEY,
            workspace_id       uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            document_id        uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            version_number     integer NOT NULL,
            status             version_status NOT NULL DEFAULT 'draft',
            pipeline_status    pipeline_status NOT NULL DEFAULT 'queued',
            pipeline_error     text,
            -- Lease held by the job currently working on this version (ADR-0007).
            pipeline_run_id      uuid,
            pipeline_lease_until timestamptz,
            needs_review       boolean NOT NULL DEFAULT false,
            file_name          varchar(300) NOT NULL,
            mime_type          varchar(100) NOT NULL,
            size_bytes         bigint NOT NULL,
            file_hash          char(64) NOT NULL,
            storage_key        text NOT NULL,
            parse_report       jsonb NOT NULL DEFAULT '{}'::jsonb,
            tag_suggestions    jsonb NOT NULL DEFAULT '{}'::jsonb,
            tags_confirmed_at  timestamptz,
            jurisdiction_code  varchar(16) REFERENCES jurisdictions(code),
            scope              jsonb NOT NULL DEFAULT '{}'::jsonb,
            scope_hash         text GENERATED ALWAYS AS (md5(scope::text)) STORED,
            topic_id           uuid REFERENCES topics(id) ON DELETE SET NULL,
            effective_from     date,
            effective_to       date,
            created_by         uuid REFERENCES users(id),
            created_at         timestamptz NOT NULL DEFAULT now(),
            published_at       timestamptz,
            published_by       uuid REFERENCES users(id),
            CONSTRAINT uq_document_versions_number UNIQUE (document_id, version_number),
            CONSTRAINT uq_document_versions_file_hash UNIQUE (document_id, file_hash),
            CONSTRAINT ck_document_versions_published_needs_tags CHECK (
                status <> 'published'
                OR (jurisdiction_code IS NOT NULL AND effective_from IS NOT NULL
                    AND tags_confirmed_at IS NOT NULL)),
            CONSTRAINT ck_document_versions_dates CHECK (
                effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from),
            CONSTRAINT ck_document_versions_scope_object CHECK (jsonb_typeof(scope) = 'object'),
            CONSTRAINT ex_document_versions_no_overlap EXCLUDE USING gist (
                document_id WITH =,
                jurisdiction_code WITH =,
                scope_hash WITH =,
                daterange(effective_from, effective_to, '[)') WITH &&
            ) WHERE (status = 'published')
        );
        CREATE INDEX ix_document_versions_workspace_status
            ON document_versions (workspace_id, status);

        CREATE TABLE version_relations (
            id               uuid PRIMARY KEY,
            workspace_id     uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            from_version_id  uuid NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
            to_version_id    uuid NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
            kind             version_relation_kind NOT NULL,
            created_at       timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_version_relations UNIQUE (from_version_id, to_version_id, kind),
            CONSTRAINT ck_version_relations_not_self CHECK (from_version_id <> to_version_id)
        );

        CREATE TABLE sections (
            id                 uuid PRIMARY KEY,
            workspace_id       uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            version_id         uuid NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
            ordinal            integer NOT NULL,
            heading_path       text[] NOT NULL DEFAULT '{}',
            clause_number      varchar(50),
            title              text,
            text               text NOT NULL,
            token_count        integer NOT NULL,
            has_table          boolean NOT NULL DEFAULT false,
            page_start         integer,
            -- Narrow the version's defaults (PLAN §4.2); NULL = inherit.
            jurisdiction_code  varchar(16) REFERENCES jurisdictions(code),
            scope              jsonb,
            topic_id           uuid REFERENCES topics(id) ON DELETE SET NULL,
            CONSTRAINT uq_sections_version_ordinal UNIQUE (version_id, ordinal)
        );

        CREATE TABLE section_refs (
            id               uuid PRIMARY KEY,
            workspace_id     uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            version_id       uuid NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
            from_section_id  uuid NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
            target_text      varchar(200) NOT NULL,
            to_section_id    uuid REFERENCES sections(id) ON DELETE SET NULL
        );
        CREATE INDEX ix_section_refs_from ON section_refs (from_section_id);

        CREATE TABLE chunks (
            id                 uuid PRIMARY KEY,
            workspace_id       uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            version_id         uuid NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
            section_id         uuid NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
            ordinal            integer NOT NULL,
            text               text NOT NULL,
            context_header     text NOT NULL DEFAULT '',
            content_hash       char(64) NOT NULL,
            token_count        integer NOT NULL,
            ts_config          regconfig NOT NULL DEFAULT 'simple',
            tsv                tsvector,
            -- Denormalised from version/section for fast filtering (kept in sync by the service).
            document_id        uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            version_status     version_status NOT NULL DEFAULT 'draft',
            jurisdiction_code  varchar(16) REFERENCES jurisdictions(code),
            scope              jsonb NOT NULL DEFAULT '{}'::jsonb,
            topic_id           uuid REFERENCES topics(id) ON DELETE SET NULL,
            effective_from     date,
            effective_to       date,
            CONSTRAINT uq_chunks_version_ordinal UNIQUE (version_id, ordinal)
        );
        CREATE INDEX ix_chunks_filter
            ON chunks (workspace_id, version_status, jurisdiction_code);
        CREATE INDEX ix_chunks_tsv ON chunks USING gin (tsv);
        CREATE INDEX ix_chunks_section_id ON chunks (section_id);

        CREATE TABLE chunk_embeddings (
            chunk_id      uuid NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
            workspace_id  uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            model         varchar(100) NOT NULL,
            dims          integer NOT NULL,
            embedding     vector NOT NULL,
            content_hash  char(64) NOT NULL,
            created_at    timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_chunk_embeddings PRIMARY KEY (chunk_id, model),
            CONSTRAINT ck_chunk_embeddings_dims CHECK (vector_dims(embedding) = dims)
        );
        CREATE INDEX ix_chunk_embeddings_reuse
            ON chunk_embeddings (workspace_id, model, content_hash);

        CREATE TABLE glossary_terms (
            id            uuid PRIMARY KEY,
            workspace_id  uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            term          varchar(200) NOT NULL,
            synonyms      varchar(200)[] NOT NULL DEFAULT '{}',
            language      varchar(16),
            created_at    timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_glossary_terms_workspace_term UNIQUE (workspace_id, term)
        );

        CREATE TABLE job_failures (
            id            uuid PRIMARY KEY,
            workspace_id  uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            task_name     varchar(100) NOT NULL,
            version_id    uuid REFERENCES document_versions(id) ON DELETE SET NULL,
            error         text NOT NULL,
            attempts      integer NOT NULL,
            payload       jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at    timestamptz NOT NULL DEFAULT now(),
            resolved_at   timestamptz
        );
        CREATE INDEX ix_job_failures_workspace_open ON job_failures (workspace_id, resolved_at);
    """)
    # One partial HNSW index per embedding model, cast to that model's size (PLAN §4.6).
    op.execute(f"""
        CREATE INDEX ix_chunk_embeddings_hnsw_vertex_768 ON chunk_embeddings
        USING hnsw ((embedding::vector(768)) vector_cosine_ops)
        WHERE model = '{VERTEX_768}'
    """)

    # Default topics for workspaces that already exist (before RLS is switched on, so the
    # owner role can backfill on hosts where it isn't a superuser).
    topic_values = ", ".join(f"({_sql_literal(k)}, {_sql_literal(n)})" for k, n in DEFAULT_TOPICS)
    op.execute(f"""
        INSERT INTO topics (id, workspace_id, key, name)
        SELECT gen_random_uuid(), w.id, t.key, t.name
        FROM workspaces w CROSS JOIN (VALUES {topic_values}) AS t(key, name)
    """)

    # --- Row-Level Security --------------------------------------------------------------
    for table in TENANT_TABLES:
        _run_all(f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
            CREATE POLICY {table}_select ON {table} FOR SELECT
                USING (workspace_id = app_current_workspace_id());
            CREATE POLICY {table}_insert ON {table} FOR INSERT
                WITH CHECK (workspace_id = app_current_workspace_id());
            CREATE POLICY {table}_update ON {table} FOR UPDATE
                USING (workspace_id = app_current_workspace_id())
                WITH CHECK (workspace_id = app_current_workspace_id());
            CREATE POLICY {table}_delete ON {table} FOR DELETE
                USING (workspace_id = app_current_workspace_id());
            GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE};
        """)

    # Global reference data: everyone may read, nobody (but migrations) may write.
    _run_all(f"""
        ALTER TABLE jurisdictions ENABLE ROW LEVEL SECURITY;
        ALTER TABLE jurisdictions FORCE ROW LEVEL SECURITY;
        CREATE POLICY jurisdictions_select ON jurisdictions FOR SELECT USING (true);
        GRANT SELECT ON jurisdictions TO {APP_ROLE};
    """)


def downgrade() -> None:
    _run_all("""
        DROP TABLE IF EXISTS job_failures;
        DROP TABLE IF EXISTS glossary_terms;
        DROP TABLE IF EXISTS chunk_embeddings;
        DROP TABLE IF EXISTS chunks;
        DROP TABLE IF EXISTS section_refs;
        DROP TABLE IF EXISTS sections;
        DROP TABLE IF EXISTS version_relations;
        DROP TABLE IF EXISTS document_versions;
        DROP TABLE IF EXISTS documents;
        DROP TABLE IF EXISTS scope_fields;
        DROP TABLE IF EXISTS topics;
        DROP TABLE IF EXISTS jurisdictions;
        ALTER TABLE memberships DROP COLUMN IF EXISTS jurisdiction_codes;
        ALTER TABLE workspaces DROP COLUMN IF EXISTS active_embedding_model;
        DROP TYPE IF EXISTS version_relation_kind;
        DROP TYPE IF EXISTS pipeline_status;
        DROP TYPE IF EXISTS version_status;
        DROP TYPE IF EXISTS jurisdiction_level;
    """)
