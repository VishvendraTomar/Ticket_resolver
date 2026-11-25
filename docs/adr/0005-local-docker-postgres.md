# ADR-0005: Local Docker Compose Postgres in Codespaces

- Status: Accepted
- Date: 2026-11-25
- Supersedes: [ADR-0001](0001-temporary-neon-postgres.md) (Neon Postgres for
  development)

## Context
ADR-0001 chose a hosted Neon database because the first development machine
had no Docker. Development has moved to a GitHub Codespace, where Docker is
available. SPEC §19 and PLAN M1 assume Docker Compose locally.

## Decision
- Development and the database tests use **Postgres from `compose.yaml`**:
  `pgvector/pgvector:0.8.1-pg16` (Postgres 16, pgvector 0.8.1) plus Redis
  7.4, with ports bound to `127.0.0.1` only.
- The image's superuser is the **owner role** (`DATABASE_URL`). `app_user`
  (`APP_DATABASE_URL`) is still created only by migration 0001, with
  NOBYPASSRLS, exactly as in ADR-0002.
- `.env` is generated per Codespace by `.devcontainer/post-create.sh` with
  random local passwords and is never committed. `.env.example` documents
  every variable.
- The devcontainer (`.devcontainer/devcontainer.json`) provides uv-managed
  Python 3.12, Node LTS and Docker-in-Docker. It starts Compose and runs the
  migrations on creation.
- **CI uses the same image** as a service container, with throwaway
  credentials, so CI and development run the same Postgres and pgvector.

## Consequences
- No cloud account or secrets are needed to develop or to run CI.
- Data lives in a Docker volume inside the Codespace. It's disposable: delete
  the volume and migrate again.
- Unlike Neon, the owner here is a true superuser. On Cloud SQL it won't be,
  so ADR-0002's note on re-checking the `SECURITY DEFINER` lookup applies
  when we deploy.
- The Neon-specific URL handling in `to_asyncpg_url` (TLS for `*.neon.tech`)
  stays. It's harmless and generic: it translates `sslmode` for any managed
  Postgres.
