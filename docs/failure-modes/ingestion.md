# Failure modes: ingestion (upload → jobs → versions → publish)

Scope: uploads, original-file storage, the Celery ingestion jobs, document
versions and their lifecycle, publishing, the coverage map. Parsing, tagging
and embeddings have their own notes ([parsing](parsing.md),
[tagging](tagging.md), [embeddings](embeddings.md)). Design: ADR-0006
(providers), ADR-0007 (jobs).

The invariant: **only a version a human has reviewed and published can ever be
retrieved, and two published versions of the same rule can never be valid on
the same day.**

| # | How it fails | How we detect it | What the system does instead | Test that proves it |
|---|--------------|------------------|------------------------------|---------------------|
| 1 | The same file is uploaded twice and ingested (and paid for) twice | SHA-256 of the bytes, unique per document | 409 with the existing version's id; nothing is stored or queued | `test_documents.py::test_identical_file_is_rejected` |
| 2 | An oversized file, or a type we can't parse, reaches the worker | Size limit (`MAX_UPLOAD_MB`) and type check from the file's magic bytes, not its name | 413 / 415 at upload; nothing is queued | `test_documents.py::test_upload_rejects_oversize_and_unknown_types` |
| 3 | One workspace reads another's original files | Storage keys are `workspaces/<id>/…`; files are only reachable through the API, which goes through RLS | 404 for anyone else | `test_cross_tenant.py` (every new route) |
| 4 | A worker crashes halfway (OOM, deploy, timeout) and leaves half-built sections/chunks | — | Each step is idempotent and keyed by version id: it deletes and rebuilds that version's derived rows in one transaction | `test_pipeline.py::test_ingest_is_idempotent` |
| 5 | A job is delivered twice at the same time (visibility timeout, retry) | Row lock on the version (`FOR UPDATE SKIP LOCKED`) plus a status guard | The second run exits without doing anything | `test_pipeline.py::test_concurrent_run_is_skipped` |
| 6 | A job keeps failing and nobody notices (Redis has no dead-letter queue) | Final failure after retries | A `job_failures` row, `pipeline_status = failed` with the error shown in the UI, and a retry endpoint | `test_pipeline.py::test_final_failure_records_job_failure`, `test_documents.py::test_retry_requeues_failed_version` |
| 7 | A task runs without a workspace context (and RLS hides everything) or with the wrong one | Tasks take `workspace_id` explicitly and use the same context helper as requests | No context → zero rows → the task fails loudly; it never runs as the owner role | `test_pipeline.py::test_task_runs_in_its_workspace_only` |
| 8 | A version is published without a jurisdiction or start date | DB `CHECK` + API validation | 422; the DB rejects it even if the API is bypassed | `test_versions.py::test_publish_requires_jurisdiction_and_dates`, `test_constraints.py::test_db_rejects_published_without_jurisdiction` |
| 9 | Two published versions of the same document, jurisdiction and scope overlap in time | `EXCLUDE USING gist` constraint on (document, jurisdiction, scope hash, date range) for published rows | Publishing a newer version closes the open-ended previous one at the new start date (audited); any other overlap → 409 | `test_constraints.py::test_overlapping_published_versions_are_impossible`, `test_versions.py::test_new_version_closes_previous` |
| 10 | Chunks outlive their version and keep being retrieved | FK `ON DELETE CASCADE` from sections/chunks/embeddings to the version | Deleting a version deletes everything derived from it | `test_constraints.py::test_chunks_are_deleted_with_their_version` |
| 11 | Chunk copies of version fields (status, dates, jurisdiction, scope) go stale, so a retired version keeps being retrieved | — | They're updated in the same transaction as the version change | `test_versions.py::test_chunk_fields_follow_publish_and_retire` |
| 12 | A version is published before parsing, review and embedding are finished | `pipeline_status` must be `ready` | 409 | `test_versions.py::test_publish_requires_ready` |
| 13 | Two published sections contradict each other (same topic, overlapping jurisdiction chain and dates) | Deterministic candidate check at publish (PLAN §4.9) | Candidates are returned, and publishing needs `acknowledge_conflicts=true`; LLM contradiction checks come in M4 | `test_versions.py::test_publish_flags_contradiction_candidates` |
| 14 | A policy editor restricted to some jurisdictions edits or publishes another's documents | Membership `jurisdiction_codes` checked on every knowledge write | 403 | `test_versions.py::test_restricted_policy_editor` |
| 15 | Gaps in coverage go unnoticed (e.g. no sick-pay policy for Spain) | Coverage map: published sections per jurisdiction × topic, from confirmed tags | Gaps are visible to editors | `test_coverage.py::test_coverage_counts_published_only` |
| 16 | Non-managers change the knowledge base | Role check: owner, admin and policy_editor only | 403; everyone else is read-only | `test_documents.py::test_only_editors_can_write` |

## Not covered yet
- Precedence (`supersedes` / `supplements`, "replaces parent" at publish,
  PLAN §4.5) is used by retrieval: M3. M2 stores the relations.
- LLM contradiction check on the candidate pairs: M4.
- Virus scanning of uploads: before public sign-up (M7b).
