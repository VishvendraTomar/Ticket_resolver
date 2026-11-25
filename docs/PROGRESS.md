# Progress

## Current milestone
**M2 — Knowledge base: almost complete (paused 2026-11-25 at the owner's
request).** Everything in PLAN §2 M2 is built and tested; one CI job is red
(see "M2 — what's left"). M1 is complete (below).

## M2 delivered so far (PLAN §2, M2)
Decisions taken from the owner on 2026-11-25: Vertex AI `gemini-embedding-001`
at 768 dims (EU), small LLM = newest in-region Gemini Flash via LiteLLM,
Docling for PDF/DOCX/HTML/Markdown with OCR, stay on Clerk, Clerk deletion
webhook moved to M7b, live provider calls only in `@pytest.mark.live`.

| PLAN M2 item | Where | Verified by |
|--------------|-------|-------------|
| Failure-mode docs first | `docs/failure-modes/ingestion.md`, `parsing.md`, `tagging.md`, `embeddings.md` | every cited test exists (checked by script) |
| Provider decisions + residency findings | ADR-0006; Celery jobs ADR-0007 | — |
| Tables: jurisdictions (318 ISO rows: GLOBAL, EU, countries, US states, DE Länder), topics (defaults), scope_fields, documents, document_versions, version_relations, sections, section_refs, chunks, chunk_embeddings, glossary_terms, job_failures; membership jurisdiction restrictions | migration `0002_knowledge_base` | catalog tests (FORCE RLS everywhere; jurisdictions read-only for app_user); upgrade/downgrade round trip |
| Constraints: no overlapping published versions (EXCLUDE gist), nothing published without jurisdiction/dates/confirmed tags, cascade from version, dims CHECK | migration 0002 | `test_constraints.py` (bypassing the API) |
| Providers behind interfaces with fakes: storage (memory/local/GCS), parser (fake/Docling), embeddings (fake/Vertex via LiteLLM, wrapped by a validator: token budget, retries, dims, L2 norm), LLM (fake/Vertex via LiteLLM) | `app/providers/*` | unit tests; GCS against fake-gcs-server; opt-in live Vertex contract tests (not yet run: no credentials) |
| Celery: idempotent lease-based jobs, retries with backoff, `job_failures` dead-letter, retry endpoint, time limits | `app/ingestion/pipeline.py`, `workers/` | `test_pipeline.py`; real worker run over Redis |
| Pipeline: hash/dedupe → Docling parse → OCR confidence → sections (heading path, clause no.) → 300–500-token chunks (tables/clauses never split) → cross-refs → AI tag suggestions → human confirm → context headers → embeddings with reuse → tsvector → ready → publish | `app/ingestion/*`, `app/knowledge/service.py` | `test_chunking.py`, `test_tagging.py`, `test_parsing.py`, `test_versions.py`; scanned-PDF OCR test passes with Docling models |
| Parse report, section preview, contradiction candidates at publish (PLAN §4.9), coverage map | service + API + web | `test_versions.py`, `test_coverage.py`, browser smoke run |
| API: 20 routes under `/v1/workspaces/{id}` | `app/api/v1/knowledge.py` | a cross-tenant case for every route (31 cases total) |
| Web: documents + upload, document versions, version review (parse report, sections, tag form prefilled from suggestions, per-section overrides, publish with conflict acknowledgement, retire, retry), coverage map, policy-editor jurisdiction limits | `web/src/app/w/[workspaceId]/…` | lint, typecheck, 15 unit tests, build; Playwright smoke run (10 steps) through API + real worker + Docling |
| Seed: Northwind Global corpus (14 docs; GLOBAL, EU, DE + DE-BY annex, FR, ES, GB, IN, US-CA, US-NY) from official sources with URL + retrieval date per clause; override, supplement, mid-year change, cross-reference | `seed/northwind/`, `seed/demo_m2.py` | demo: 9 checks pass in-process, through a real Celery worker, and as a db test in CI |
| Compose: `worker` (Celery + Docling) and `fake-gcs` | `compose.yaml` | compose config check |

### Test status (2026-11-25, commit before this one)
- Backend: **197 passed, 3 skipped** (2 live Vertex tests, 1 Docling-models
  OCR test that passes locally with `DOCLING_MODELS=1`). ruff, format, mypy
  strict (app + workers) clean.
- Web: 15 Vitest tests; lint, typecheck, build clean.
- CI: `backend` and `web` green. **`images` red** on the new full-stack
  smoke step (below).

### Bugs found and fixed along the way
- Docling's RapidOCR needs `onnxruntime`, which Docling doesn't install:
  every scanned PDF would have failed. Found by the OCR test; dependency added.
- Web forms stayed in "Uploading…" after navigating back (Next keeps pages
  mounted with state). Found by the browser smoke run; forms reset.
- Eager-mode Celery retries raised `Retry` into the API; retries now run
  inline in eager mode.
- Demo re-run picked the latest version instead of v1 for multi-version docs.

## M2 — what's left
1. **Fix the red CI `images` job:** `backend/Dockerfile` doesn't copy
   `workers/`, so the API container fails with
   `ModuleNotFoundError: No module named 'workers'`. Add
   `COPY workers ./workers`, then confirm the full-stack smoke (compose app
   profile + `demo_m2.py --api-url` through the containerised worker) passes.
2. Run the live Vertex tests once credentials exist
   (`RUN_LIVE=1 VERTEX_PROJECT=… uv run pytest tests/live -m live`), and the
   M2 demo with `EMBEDDINGS_PROVIDER=vertex LLM_PROVIDER=vertex`.
3. Then mark M2 complete and stop (don't start M3).

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

### M2 decisions (reversible)
- **Small LLM = `gemini-3.5-flash` in `europe-west3`**: the newest Flash with
  *in-country* (Frankfurt) processing. `gemini-3.8-flash` is newer but only
  processed in the EU multi-region; switching is one env var (ADR-0006).
- **`gemini-embedding-001` can't be processed in a single country**: Google
  lists EU-multi-region processing only. Default location `europe-west4`.
  If Germany-only processing is required, that model can't do it.
- **Torch from the CPU-only index** (no CUDA), Docling's RapidOCR with onnxruntime.
- **Embedding reuse is workspace-wide** (same text hash + model), not per document.
- **Publishing auto-closes the previous open-ended version** of the same
  document/jurisdiction/scope at the new start date (audited); other overlaps → 409.
- **Contradiction check at publish is deterministic** (same topic, overlapping
  chain and dates); publishing needs explicit acknowledgement. LLM check in M4.
- **Token counts are a conservative estimate** (words × 1.3), not Gemini's tokenizer.
- **Migration 0002 was edited in place** (lease columns) since it was never deployed.
- **`uv` network workaround in this Codespace:** the post-quantum TLS
  ClientHello is dropped on this network path (confirmed with `openssl
  s_client`). A system-wide MSS clamp was refused by the sandbox, so `uv lock`
  ran through a local user-space proxy that clamps TCP segment size (scratch
  file, not in the repo). CI and fresh environments don't need it.

## Open items
- **Clerk user-deletion webhook (not built; moved to M7b, before public
  sign-up, per owner).** Deleting a user in Clerk
  doesn't remove or disable our `users` row or their memberships; they just
  can't sign in. Needs a signature-verified webhook endpoint (its own signing
  secret, a new env var) that removes memberships, keeps the audit trail,
  and handles last-owner workspaces. Ties into GDPR erasure (M6). See
  failure-modes/tenancy.md, "Not covered yet".
- **Clerk never exercised for real.** No keys yet. Token verification is
  unit-tested with locally signed JWTs, and the web app builds in Clerk mode
  with a dummy key. You'll add the keys to `.env`; then test a real sign-in.
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

## Before M3 — your decisions
1. **Vertex AI project + credentials** for the live tests and real embeddings
   (and whether EU-multi-region processing is acceptable, see M2 decisions).
2. **Reranker** (PLAN §5 #4): Cohere is the plan; it's needed at the start of M3.
3. **Review the Northwind corpus** (`seed/northwind/`): the golden set in M3 is
   built on it (~60 cases, reviewed in batches of 25).

## Next step
Finish M2 (see "M2 — what's left": the one-line Dockerfile fix, then the
live runs when credentials exist). Then stop; M3 starts after your decisions.

## Notes
- ADR numbering is shifted by one from PLAN M1, because 0001 went to Neon.
- FastAPI 0.165 nests included routers lazily, so route enumeration uses
  `fastapi.routing.iter_route_contexts` (guarded by a test).
- sentry-sdk 3 replaced `send_default_pii` with `data_collection`. We
  disable user info, bodies, DB query data and frame variables.
- `web/AGENTS.md` is generated by Next.js and points coding agents at the
  version-matched docs in `node_modules/next/dist/docs/`. Committed on
  purpose, since `next dev` re-creates it.
