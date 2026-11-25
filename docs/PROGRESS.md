# Progress

## Current milestone
**M1 — Foundation: complete (2026-11-25).** Stopped here as instructed.
M2 not started: it waits for the decisions listed under "Before M2".

## M1 delivered (PLAN §2, M1)
| PLAN M1 item | Where | Verified by |
|--------------|-------|-------------|
| uv, ruff, mypy strict, pytest-asyncio, pre-commit | `backend/pyproject.toml`, `.pre-commit-config.yaml` | CI `backend`; `pre-commit run --all-files` |
| compose: postgres (pg16 + pgvector 0.8.1), redis, api, web | `compose.yaml` (api/web/migrate under `--profile app`), Dockerfiles | CI `images`; full stack in containers passed the browser smoke run and the demo |
| core: settings, async engine, JSON logs + request id, Sentry | `backend/app/core/` | unit tests |
| tables: workspaces, users, memberships (6 roles), append-only audit_events | migration `0001_tenancy_rls` | catalog + RLS tests; upgrade → downgrade → upgrade in CI |
| RLS: owner migrates, app_user NOBYPASSRLS, ENABLE + FORCE, transaction-local context | migration 0001, `app/core/db.py`, ADR-0002 | `test_catalog.py`, `test_rls.py` |
| catalog test: tenant table without RLS + FORCE + policy fails | `tests/tenancy/test_catalog.py` | CI |
| cross-tenant suite over every route, fails if a route has no case | `tests/tenancy/test_cross_tenant.py` | CI |
| auth: AuthVerifier, Clerk JWT (JWKS) + fake; orgs/roles in our DB | `app/providers/auth/`, ADR-0003 | `test_auth.py`, `test_config.py` |
| API: create workspace, members list/add/remove/change role, `/v1/me`, RBAC | `app/api/v1/tenancy.py`, `app/tenancy/` | `test_members.py`, cross-tenant suite |
| web: Next.js shell, sign-in, workspace switcher, members page | `web/` | CI `web` (lint, typecheck, 14 unit tests, build); browser smoke run |
| CI: ruff, mypy, pytest with a Postgres service, web lint + typecheck + build | `.github/workflows/ci.yml` | green on every push to main |
| docs: failure-modes/tenancy.md; ADRs | `docs/failure-modes/tenancy.md` (28 rows, every cited test checked); ADR-0002 RLS, 0003 auth, 0004 provider interfaces, 0005 local Docker Postgres (0001 Neon: superseded) | review |
| demo: two workspaces, users in each, A can't see B | `seed/demo_m1.py` (also runs as a db test in CI) | 15 checks: API and raw SQL as app_user |

### Final test status (2026-11-25, commit 571dc53)
- Backend: **86 passed, 0 skipped** locally and in CI. That's 47 offline
  plus 39 against Postgres: RLS, catalog, cross-tenant for every route,
  member rules, and the demo. ruff and mypy strict are clean.
- Web: 14 Vitest tests; lint, typecheck and build are clean.
- CI: `backend`, `web` and `images` all green
  (run 45627823575).
- Browser smoke run (Playwright, headless Chromium, not in CI): 12 steps
  pass against both native dev servers and the containerised stack.

### Fixes found along the way
- Test emails used the reserved `.test` TLD, so every add-member returned
  422. Tests now use `example.com`; production validation is unchanged.
- The migration couldn't be rolled back, because policies depended on
  `memberships`. Fixed, and CI now runs the round trip.
- An empty `CLERK_AUTHORIZED_PARTIES` disabled the `azp` check. It's now
  required outside local/test.
- `post-create.sh` fallback used `ensurepip -q`, which isn't a valid flag.
  Fixed; it was caught when the same fallback ran in the API Dockerfile.

## Decisions made — review
Reversible choices made without asking, under the M1 close-out
instructions. Each is easy to change.
- **Web auth selection:** Clerk if `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` is
  set, else the fake dev sign-in (`NEXT_PUBLIC_AUTH_PROVIDER` overrides). A
  yellow banner marks fake mode. The backend is the real guard: it refuses
  fake tokens outside ENVIRONMENT=local/test.
- **No Next.js `proxy.ts` (ex-middleware); Clerk client-side only:** the
  browser calls FastAPI directly with a bearer token. `<ClerkProvider>` is
  rendered only with a key; without one, Clerk would start "keyless" mode and
  contact Clerk.
- **One repo-root `.env`** for API, Compose and web. `next.config.ts` loads
  it, and only `NEXT_PUBLIC_*` reach the browser. Each password is stored
  once (`POSTGRES_PASSWORD`, `APP_DB_PASSWORD`) and the URLs are built with
  `${VAR}`.
- **Client-side data fetching** with a small `useQuery` hook, not TanStack
  Query or server components, because tokens live client-side. Revisit when
  pages get heavier.
- **Fake sign-in identity:** subject `dev_<email-slug>` in localStorage, so
  the same email is always the same person.
- **Kept Next 16 scaffold defaults** `cacheComponents` + `partialPrefetching`.
  Side effect: the previous route stays mounted but hidden (React
  `<Activity>`).
- **Vitest** for web unit tests. The browser e2e was a one-off Playwright
  run, not in the repo or CI (failure mode #25).
- **Versions:** the newest releases older than two weeks: Next 16.4.6,
  @clerk/nextjs 7.9.25, shadcn 4.23.0, Vitest 5.1.0; actions checkout
  v7.0.1, setup-uv v10.3.3, setup-node v7.1.0, all SHA-pinned.
  `@types/node` 24 to match Node 24 LTS.
- **Compose `app` profile:** api/web/migrate run only with
  `--profile app`, so plain `docker compose up -d` and the devcontainer stay
  fast and leave ports 3000/8000 to native dev servers.
- **Owner credentials only in `migrate`:** the `api` container gets an
  explicit env list (no `env_file`) with app_user only.
- **Dockerfile pip fallback:** the API image tries `uv sync` and falls back
  to pip with the same hash-locked set (the Codespace uv TLS issue below also
  hits `docker build`). On GitHub the uv path is used.
- **pre-commit with local hooks only** (ruff, format, mypy, eslint, web
  typecheck, a `.env` guard), using the project's pinned tools. It's
  installed outside the project's dependencies, so `uv.lock` is unchanged.
- **CI concurrency:** superseded PR runs are cancelled; every push to main
  runs to completion.
- **Dependabot:** weekly for actions, uv (backend), npm (web) and Docker base
  images, with minor/patch updates grouped. Its first PR (setup-uv 10.3.3 →
  10.4.0) is open and unmerged. 10.4.0 was five days old, so I left it for
  you.

## Open items
- **Clerk user-deletion webhook (not built).** Deleting a user in Clerk
  doesn't remove or disable our `users` row or their memberships; they just
  can't sign in. Needs a signature-verified webhook endpoint (its own signing
  secret, a new env var) that removes memberships, keeps the audit trail,
  and handles last-owner workspaces. Ties into GDPR erasure (M6). See
  failure-modes/tenancy.md, "Not covered yet".
- **Clerk never exercised for real.** No keys yet. Token verification is
  unit-tested with locally signed JWTs, and the web app builds in Clerk mode
  with a dummy key. A real sign-in needs your Clerk app (see below).
- **Invitations:** add-member requires the person to have signed in once
  (404 otherwise). Invites for new people are planned for M6.
- **Browser e2e in CI:** add Playwright when the web app grows past the shell.
- **uv ↔ PyPI TLS stall in this Codespace:** `uv sync` connects over TCP
  but the TLS handshake times out, while curl/pip (OpenSSL) work. Worked
  around in `post-create.sh` and the API Dockerfile (pip with the same
  hash-locked set). Cause not confirmed; retry plain `uv sync` in a fresh
  Codespace.
- **The devcontainer itself hasn't been built yet.** Its setup script's
  steps were each run here; the next Codespace is the real test.
- **Cloud SQL:** the owner role there isn't a superuser. Re-check the
  SECURITY DEFINER lookup and the catalog test at deployment (ADR-0002).

## Before M2 — your decisions
1. **Embeddings provider** (PLAN §5 #2): needed at the start of M2, and
   multilingual per SPEC. It's also where EU data residency first matters.
2. **LLM provider(s) via LiteLLM** (PLAN §5 #3): small + strong models. M2
   uses the small one for tag suggestions.
3. **Document parser** (ADR-0004 table): what M2 ingests (PDF/DOCX/HTML)
   decides between a hosted parser and a local library.
4. **Clerk, or an EU-hosted alternative** (ADR-0003): create the Clerk app
   and send me the publishable key, issuer URL and authorised origins, or
   choose Zitadel/WorkOS before real users exist. Clerk processes operator
   identities in the US.
5. **Whether to build the Clerk user-deletion webhook now or in M6.**

## Next step
Start M2 (Knowledge base) once the decisions above are made: read the PLAN
§2 M2 and SPEC sections, write `docs/failure-modes/ingestion.md` first,
then build behind provider interfaces with fakes.

## Notes
- ADR numbering is shifted by one from PLAN M1, because 0001 went to Neon.
- FastAPI 0.165 nests included routers lazily, so route enumeration uses
  `fastapi.routing.iter_route_contexts` (guarded by a test).
- sentry-sdk 3 replaced `send_default_pii` with `data_collection`. We
  disable user info, bodies, DB query data and frame variables.
- `web/AGENTS.md` is generated by Next.js and points coding agents at the
  version-matched docs in `node_modules/next/dist/docs/`. Committed on
  purpose, since `next dev` re-creates it.
