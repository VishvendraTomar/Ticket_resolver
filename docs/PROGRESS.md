# Progress

## Current milestone
**M1 — Foundation**: in progress. Backend tenancy verified against Compose
Postgres (all 78 tests pass, including RLS, catalog and cross-tenant).

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

- 2026-11-25: Local stack in the Codespace (Neon dropped):
  - `compose.yaml`: postgres (`pgvector/pgvector:0.8.1-pg16`) + redis 7.4,
    ports bound to 127.0.0.1. api/web join once they have Dockerfiles.
  - `.env` → Compose (owner `DATABASE_URL`, `app_user` `APP_DATABASE_URL`);
    `.env.example` rewritten for Compose.
  - `backend/.python-version` pins 3.12 (uv had been picking 3.14).
  - `alembic upgrade head` ran; `app_user` verified NOSUPERUSER,
    NOBYPASSRLS, NOINHERIT. Downgrade → upgrade round trip verified.
  - `.devcontainer/` (uv-managed Python 3.12, Node LTS, Docker-in-Docker);
    `post-create.sh` writes `.env`, syncs deps, starts Compose, migrates.

### Test status
- **78 passed, 0 skipped** (47 offline + 31 DB: RLS, catalog,
  cross-tenant for every route, member rules). ruff and mypy strict clean.
- Fixes needed to get there:
  - Test emails used `@example.test`; email-validator rejects `.test` as
    special-use (422 on add-member). Tests now use `@example.com`;
    production validation unchanged.
  - Migration downgrade failed: `workspaces_select`/`users_select` policies
    depend on `memberships`. Downgrade now drops them first.
  - Removed deprecated `Result.tuples()` (SQLAlchemy 2.1) and set
    `path_separator` in alembic.ini.

## In progress
M1: tenancy backend done and verified. Rest of M1 below.

## Next step
1. Write ADR-0002 (RLS mechanism) and ADR-0003 (Clerk identity-only) — the
   code references them but they're not written.
2. CI (GitHub Actions with a Postgres service container running the same
   pgvector image) so the DB tests run on every push.
3. Web shell (Next.js + Clerk; Node LTS), api/web Dockerfiles and their
   compose services, `seed/demo_m1.py`, PROGRESS update.

## Open questions / notes
- **uv ↔ PyPI TLS stall in this Codespace**: `uv sync` connects over TCP
  but the TLS handshake times out, while curl/pip (OpenSSL) work. Workaround
  (also automated in `post-create.sh`): `uv export --frozen` → pip install
  with `--require-hashes` into `backend/.venv` → `uv sync --frozen --offline`.
  Cause not confirmed; worth retrying plain `uv sync` in a fresh Codespace.
- The devcontainer has not been built yet; the next Codespace is its test.
- ADR-0001 (Neon) was **not used**: the user chose Docker in Codespaces
  instead. Marked superseded.
- FastAPI 0.165 nests included routers lazily; route enumeration uses
  `fastapi.routing.iter_route_contexts` (guarded by a test).
- sentry-sdk 3 replaced `send_default_pii` with `data_collection`; we
  disable user info, bodies, DB query data and frame variables.
- Providers for embeddings, LLMs, reranker and email: decide when the
  milestone needs them (fakes until then).
