# ADR-0007: Ingestion jobs on Celery (Redis), async code inside sync tasks

- Status: Accepted
- Date: 2026-11-25
- Implements: SPEC §4 (Celery + Redis), PLAN §4.12

## Context
Ingestion (parse → section → chunk → tag → embed) takes seconds to minutes per
document, and OCR can take much longer. It must survive worker crashes and
redelivery, show its status to editors, and never fail silently. Redis as a
broker has no dead-letter queue, and its visibility timeout redelivers any
task that runs too long. Our database code is async (SQLAlchemy + asyncpg),
while Celery tasks are synchronous functions.

## Decision
- **Queues:** `ingestion` (parse, tag, embed) and `maintenance` (later:
  re-embedding, cleanup). Workers run with `--concurrency` sized for
  Docling's memory.
- **Tasks are thin.** Each task calls an async pipeline function with
  `asyncio.run(...)`, using an engine **created for that run with
  `NullPool`** and disposed at the end. Pooled asyncpg connections can't
  outlive the event loop that opened them, and every task run has a fresh
  loop. In eager mode (tests, local dev without a worker), a task called
  from inside a running loop runs in a helper thread with its own loop.
- **Short transactions, with a lease.** A job claims the version
  (`pipeline_run_id`, `pipeline_lease_until`) in a short transaction. It
  does the slow work (parsing, provider calls) with no transaction or row
  lock held, then writes in a second short transaction, but only if it
  still holds the lease. A redelivered or concurrent run sees a live lease
  and skips. An expired lease (a crashed worker) can be taken over.
- **Tenant context:** tasks take `workspace_id` and `version_id` as
  arguments, and connect as `app_user` through the same `set_context`
  helper as API requests (ADR-0002). A task never uses the owner role.
- **Idempotent and keyed by version id.** Each step locks the version row
  (`SELECT … FOR UPDATE SKIP LOCKED`). If another run holds it, the task
  exits. The step then deletes and rebuilds that version's derived rows in
  one transaction, and advances `pipeline_status`. Re-running a step is
  always safe.
- **Delivery:** `acks_late=True`, `task_reject_on_worker_lost=True`,
  `visibility_timeout` above the longest allowed task (parse time limit +
  margin). Hard and soft time limits per task.
- **Retries:** transient errors (provider 429/5xx, DB connection drops)
  retry with exponential backoff and jitter, up to `max_retries`.
- **Dead-letter = `job_failures` table.** On final failure, the task records
  the task name, version, error and attempts, and sets the version to
  `failed` with a readable reason. Editors see it and can call
  `POST …/versions/{id}/retry`.
- **Tests run tasks eagerly** (`task_always_eager`) against the real
  database, with fake providers. No broker is needed in tests. In eager
  mode, retries happen inline instead of through `task.retry`.

## Alternatives considered
- **Arq / Dramatiq / RQ:** fine tools, but the spec and the GCP plan name
  Celery. Celery's maturity (time limits, late ack, beat for maintenance)
  matters more than async-native ergonomics here.
- **One engine shared across tasks:** breaks across event loops; rejected.
- **Running Docling in a separate service:** isolates memory better, but adds
  a network hop and a deployment unit. Revisit if worker OOMs show up.

## Consequences
- A crashed task leaves the version at its last completed step. Redelivery
  or retry continues safely from there.
- `job_failures` needs an admin view (API in M2; UI list on the document
  page).
- `asyncio.run` per task costs a few milliseconds; negligible next to
  parsing.
