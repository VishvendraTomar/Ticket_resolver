# Progress

## Current milestone
**M1 — Foundation**: in progress. Backend tenancy code written; **DB/RLS
tests have never run** (see below).

## Done
- 2026-11-25: Plan approved with changes (PLAN.md §4, §5): Clerk identity
  only; spec changes 4.1–4.15 accepted (RAGAS kept); hard pass marks for
  M3–M5 on live providers; M3 ablation report.
- 2026-11-25: M1 backend, first slice (`backend/`):
  - uv project, Python 3.12, ruff, mypy (strict), pytest + pytest-asyncio.
  - Settings (`app/core/config.py`), async engine + transaction-local RLS
    context (`app/core/db.py`), JSON logs with request id, Sentry with minimal
    data collection, error mapping (404 for "not yours").
  - Migration `0001_tenancy_rls`: `app_user` role created in SQL
    (NOBYPASSRLS, password from APP_DATABASE_URL), workspaces / users /
    memberships / audit_events, ENABLE+FORCE RLS, explicit per-table grants,
    append-only audit triggers (incl. TRUNCATE), one allowlisted
    SECURITY DEFINER lookup.
  - Auth: `AuthVerifier` interface, fake verifier, Clerk JWT verifier
    (JWKS, iss, exp/nbf, azp, RS256 only).
  - API: `GET /v1/me`, `POST /v1/workspaces`, `GET /v1/workspaces/{id}`,
    members list/add/patch/delete, owner/admin rules, last-owner protection.
  - Tests: catalog (RLS+FORCE+policy on tenant tables, app-accessible tables
    protected, app role can't bypass RLS / owns nothing, SECURITY DEFINER
    allowlist, audit triggers), raw-SQL RLS behaviour, cross-tenant case for
    every `/v1` route (plus a check that every route has one), member rules.
  - docs/failure-modes/tenancy.md, ADR-0001.

### Test status — read this
- **Offline: 47 passed** (`uv run pytest`), ruff clean, mypy strict clean.
- **31 DB tests skipped: never run against a real Postgres.** That includes
  every RLS, catalog and cross-tenant test, *and the migration itself*. Treat
  all of that code as unverified until they pass.

## In progress
M1 backend tenancy, awaiting a database to verify against.

## Next step (in the Codespace)
1. Write `compose.yaml` (Postgres 16 + pgvector ≥ 0.8, Redis) — it doesn't
   exist yet — plus `.devcontainer/` if wanted.
2. Point `.env` at Compose: owner `DATABASE_URL`, `APP_DATABASE_URL` as
   `app_user`; `ENVIRONMENT=local`. Update `.env.example` comments (they
   still describe Neon).
3. `cd backend && uv sync && uv run alembic upgrade head && uv run pytest`;
   fix whatever fails. Expect surprises in the migration and RLS tests —
   nothing there has executed yet.
4. Write ADR-0002 (RLS mechanism) and ADR-0003 (Clerk identity-only) — the
   code references them but they're not written.
5. Then: web shell (Next.js + Clerk; Node ≥ 20), CI (GitHub Actions with a
   Postgres service container), `seed/demo_m1.py`, PROGRESS update.

## Open questions / notes
- ADR-0001 (Neon) was **not used**: the user chose Docker in Codespaces
  instead. Marked superseded.
- FastAPI 0.165 nests included routers lazily; route enumeration uses
  `fastapi.routing.iter_route_contexts` (guarded by a test).
- sentry-sdk 3 replaced `send_default_pii` with `data_collection`; we
  disable user info, bodies, DB query data and frame variables.
- Providers for embeddings, LLMs, reranker and email: decide when the
  milestone needs them (fakes until then).
