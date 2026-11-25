# ADR-0001 (temporary): Neon Postgres instead of Docker Compose for development

- Status: **Superseded before use** (2026-11-25). Development moved to a GitHub
  Codespace with Docker, so the database is Compose Postgres 16 as the spec
  intended. Kept for the record; the guardrails it introduced (app_user created
  by migration SQL, the no-BYPASSRLS test) stay regardless of host.
- Date: 2026-11-25

## Context
The development machine has no Docker. SPEC §19 and PLAN M1 assume Docker
Compose with Postgres 16 + pgvector. We still need a real Postgres to build
and prove Row-Level Security, which can't be faked.

## Decision
- Development and the database tests use a **Neon Postgres project** reached via
  `DATABASE_URL`. pgvector is available on Neon (needed from M2).
- Two connection strings:
  - `DATABASE_URL` — the Neon owner role (e.g. `neondb_owner`). Used **only**
    for migrations and for the catalog tests that inspect `pg_catalog`.
  - `APP_DATABASE_URL` — `app_user`, used by the running app and the
    RLS/cross-tenant tests.
- `app_user` is created **by an Alembic migration in SQL**
  (`LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE`), never through the
  Neon dashboard: roles made in the dashboard are granted `neon_superuser`,
  which carries BYPASSRLS. The migration takes the password from
  `APP_DATABASE_URL`, so the secret lives only in the environment.
- A test fails if the app's role has `rolbypassrls = true` or `rolsuper = true`,
  is a member of any role that does, or owns any table.
- Use Neon's **direct** endpoint (host without `-pooler`) for development. The
  pooled endpoint runs PgBouncer in transaction mode; our `SET LOCAL` context
  is transaction-scoped, so it is safe there too, but direct avoids
  prepared-statement edge cases with asyncpg while we're small.
- Point development at a **dedicated Neon branch** (e.g. `dev`). Tests create
  uniquely named data and never truncate, but they do write to it.
- `compose.yaml` stays in the repo for later (Postgres 16 + pgvector, Redis);
  nothing depends on it.
- CI (later in M1) uses a Postgres 16 service container, not Neon, so CI needs
  no cloud secrets.

## Consequences
- Database tests need network access and the two env vars. Without them they
  are **skipped with a visible reason**, not silently passed. Unit tests stay
  offline.
- Neon's Postgres version must be 16 to match the spec (set at project
  creation; 17 works for everything in M1, but we pin to 16).
- Data lives in Neon's region; this is demo/dev data only, never customer data.
- When Docker arrives: point both URLs at Compose, run the same migrations,
  mark this ADR "Superseded".
