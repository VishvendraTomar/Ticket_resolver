# Ticket Resolver — Plan

Source of truth: docs/SPEC.md, as amended by the decisions recorded in §5.
This plan sets the layout, breaks the §21 milestones into concrete
deliverables, and records the agreed changes to the spec (§4).

**Status: approved 2026-11-25.** Accepted: §4.1–4.10 and §4.12–4.15; §4.11
accepted with a modification (RAGAS kept, see §4.11). Wherever this plan and
SPEC.md differ, this plan wins for the items listed in §4 and §5, and SPEC.md
wins for everything else.

## 1. Repository layout

Follows SPEC §5 with four changes (marked ★).

ticket-resolver/
  compose.yaml            ★ at the root, so `docker compose up -d` (CLAUDE.md) works as-is
  .env.example
  backend/
    pyproject.toml        # uv, ruff, mypy, pytest config
    alembic/
    app/
      core/               # settings, db engine/session, workspace context, logging, errors
      providers/          ★ one place for every external-service interface:
                          #   <name>/base.py (Protocol), fake.py, <vendor>.py
                          #   auth, llm, embeddings, reranker, storage, parser, pii, tracing
      tenancy/            # workspaces, users, memberships, roles, RLS helpers
      knowledge/          # documents, versions, jurisdictions, scope fields, topics, glossary
      ingestion/          # parse, sectionise, chunk, tag, embed
      context/            # requester profiles, RequesterContext, jurisdiction chain
      retrieval/          # filters, hybrid search, fusion, rerank, expand, precedence, evidence
      resolution/         # LangGraph graph, nodes, ResolutionState, answer schema
      verification/
      guardrails/
      handoff/
      livedata/           ★ renamed from tools/ (it's easy to mistake for dev tooling)
      evaluation/
      integrations/       # chatwoot, email, widget, webhooks
      api/v1/             # routers only; no business logic
    workers/              # celery app, queues, tasks (thin wrappers around app/ services)
    tests/
      unit/  integration/  tenancy/   ★ tenancy/ holds the cross-tenant suite that runs on every route
  web/                    # Next.js App Router
  eval/                   # golden sets (JSONL), reports
  seed/                   # Northwind Global sources + demo scripts per milestone (demo_m1.py …)
  infra/                  # terraform later; nothing until deployment is requested
  docs/  adr/  failure-modes/

Conventions:
- Every domain package has `models.py` (SQLAlchemy), `schemas.py` (Pydantic),
  `service.py` (logic), `repo.py` (queries). Routers and tasks call services.
- Fakes are deterministic and the default in tests. Tests that use real
  providers are marked `@pytest.mark.live` and skipped unless keys are set.

## 2. Milestones

Each one is done only when tests pass, its failure-mode notes are written,
`seed/demo_mN.py` runs, PROGRESS.md is updated (SPEC §21), **and its hard pass
marks are met**.

### Hard pass marks (quality gates)

| Milestone | Gate |
|-----------|------|
| M3 | recall@8 ≥ 0.90 · MRR ≥ 0.75 · **zero** out-of-chain, out-of-scope or out-of-date chunks returned |
| M4 | citation precision ≥ 0.95 · faithfulness ≥ 0.90 · **no** unverified claim reaches the answer |
| M5 | CI fails if any tracked metric drops more than 3 points (0.03) against the stored baseline |

- **Gate runs use real providers** (`@pytest.mark.live`), never fakes. Fakes
  prove the code paths; only real models prove the quality numbers. Each gate
  run writes a report to `eval/reports/` (metrics, provider and model
  versions, dataset version, commit) so the result can be reproduced.
- The "zero out-of-chain/scope/date" and "no unverified claim" gates are
  *also* enforced offline by deterministic tests on every run, because they
  are properties of the filter and verifier code, not of model quality.
- A gate that misses its mark blocks the milestone. I report the numbers and
  what I'd change; I don't lower the bar or tune the test set to pass.

### M1 — Foundation
- uv project, ruff, mypy (strict on app/), pytest-asyncio, pre-commit; git repo.
- compose.yaml: postgres (pg16 + pgvector ≥ 0.8), redis, api, web.
  Further services are added in the milestone that first needs them.
- core: Pydantic Settings, async engine, JSON logs with request/trace id,
  Sentry (no-op without a DSN).
- Tables: workspaces, users, memberships (role: owner, admin, policy_editor,
  agent, viewer, integrator), audit_events (append-only: UPDATE/DELETE revoked
  plus a trigger).
- RLS: migrations run as an owner role; the app connects as `app_user`
  (NOBYPASSRLS). Every tenant table has `ENABLE` + `FORCE ROW LEVEL SECURITY`
  and a policy on `current_setting('app.workspace_id')`. That setting is set with
  `SET LOCAL` inside each transaction, so it is pool-safe. Celery uses the same
  helper.
- Catalog test: fails if any table with a workspace_id column lacks
  RLS + FORCE + a policy.
- Cross-tenant suite: lists every FastAPI route and fails if a route has no
  cross-tenant case registered.
- Auth: `AuthVerifier` interface; Clerk JWT (JWKS) implementation + fake.
  Workspaces and memberships live in our DB (see §4.1).
- API: create workspace, list/add/remove members, change role, `GET /v1/me`.
  RBAC dependency.
- Web: Next.js shell with sign-in, workspace switcher and a members page.
- CI: GitHub Actions running ruff, mypy, pytest (Postgres service container),
  web lint + typecheck + build.
- Docs: failure-modes/tenancy.md; ADR-0001 RLS mechanism, ADR-0002 auth,
  ADR-0003 provider interfaces.
- Demo: two workspaces, users in each; shows that A cannot see B.

### M2 — Knowledge base
- Tables: jurisdictions (seeded ISO tree: GLOBAL, EU, countries, US states),
  scope_fields, topics (★ §4.4), documents, document_versions, sections
  (+ section_refs), chunks, chunk_embeddings (★ §4.6), glossary_terms,
  job_failures (★ §4.12). memberships gets its jurisdiction restrictions here.
- Constraints: btree_gist exclusion constraint that rules out overlapping
  published ranges for the same (document, jurisdiction, scope_hash);
  jurisdiction NOT NULL when publishing; chunks deleted with their version
  (FK cascade).
- Storage interface: local FS / fake-gcs-server (added to compose) / GCS.
- Celery: ingestion + maintenance queues, idempotent tasks keyed by version id,
  late ack, backoff with jitter, final failure recorded in job_failures, retry endpoint.
- Pipeline: hash and dedupe → Docling parse (tables as Markdown) → OCR with
  confidence → sections (heading path, clause no.) → chunks of 300–500 tokens
  (never splitting a table or clause; parents ≤ 1,500) → context header → AI tag
  suggestions → human confirm → batched embedding with reuse by content hash →
  tsvector → ready → publish.
- Parsing-quality report; section preview; contradiction check at publish
  (scoped down, §4.9); coverage map.
- Web: upload, section preview, tagging, versions, publish, coverage map.
- Seed: Northwind Global documents (§4.14) ingested end to end.
- Docs: failure-modes/ingestion.md, parsing.md, tagging.md, embeddings.md.

### M3 — Retrieval
- Requesters + dated attribute history; RequesterContext with a source per value;
  jurisdiction chain builder; scope filter.
- Query understanding (small model): topic, intent, sub-questions, 2–3
  rewrites using the glossary, language, event date.
- SQL hard filter → per-query vector (HNSW, iterative scan; exact search when
  the filtered set is under N rows) + language-aware FTS → RRF → rerank 50→8 →
  parent expansion + one cross-reference hop → precedence labels → evidence score.
- Golden set v0 (~60 retrieval cases, including wrong-country and
  outdated-version lures). Deterministic metrics: hit rate, MRR, and context
  precision/recall against expected citations.
- Property-style test: no chunk outside the chain, scope or date range ever comes back.
- **Ablation report** (`eval/reports/m3-ablation.md`), on the same golden set
  and real providers: vector-only → hybrid (vector + FTS + RRF) → + rerank →
  + query rewriting. For each: recall@8, MRR, p50/p95 latency and cost per query.
- **Gate:** recall@8 ≥ 0.90, MRR ≥ 0.75, zero out-of-chain/scope/date chunks (live run).
- Docs: failure-modes/context.md, retrieval.md, precedence.md.

### M4 — Resolution
- LangGraph graph with a typed ResolutionState; node order adjusted (§4.3).
- Answer schema exactly as in SPEC §10; generation with labelled evidence.
- Verifier checks 1–5, with locale-aware normalisation of numbers, dates and amounts.
- Guardrails pipeline (input/PII, injection, document wrapping, output checks).
- Handoff rules + payload + escalation-reason enum; autonomy setting
  (draft-only default).
- Confidence combiner with conservative global defaults (§4.10).
- Resolution trace persisted in our DB; Langfuse via the tracing interface.
- Cost and latency recorded per node and per resolution; per-ticket cost cap.
- `POST /v1/tickets/resolve` with SSE progress events (§4.8).
- Web: test console.
- **Gate:** citation precision ≥ 0.95, faithfulness ≥ 0.90 (live run), and no
  unverified claim in any returned answer (enforced by the verifier and by an
  offline test that feeds it bad drafts).
- Docs: failure-modes/resolution.md, verifier.md, guardrails.md, handoff.md.

### M5 — Evaluation
- Golden set grown to ~200, all trap types; eval_sets/cases/runs/results.
- Custom metrics (jurisdiction accuracy, decision accuracy, over- and
  under-escalation, citation precision) + DeepEval for faithfulness and
  correctness (the core, §4.11).
- RAGAS: synthetic test-set generation (cases reviewed by you before they enter
  the golden set) and a secondary report alongside the core metrics.
- Verifier measured against human labels (false-reject and false-pass rates).
- Confidence calibration report (reliability curve).
- CI gate: offline subset on every PR, nightly live run.
  **Gate:** the build fails if any tracked metric drops more than 3 points
  against the stored baseline.
- Replay: CSV upload → report comparing against what agents actually sent.
- Web: evaluation reports.

### M6 — Review and analytics
- Review inbox; feedback (approve/edit/reject + reason); API keys (hashed,
  scoped, revocable) with rate limits per key and per workspace; cost tracking
  and budgets; analytics (escalation reasons, edit rate, country × topic).
- Production sampling for judge scoring.

### M7 — Integration and launch (split into M7a/M7b, §4.13)
- M7a: HelpdeskConnector + Chatwoot (webhook in, dedupe by
  (workspace, provider, event_id), draft posted as a private note), email intake,
  embeddable widget with signed requester identity (§4.7).
- M7b: live-data tool framework, mock HR connector, public sign-up.

Deployment (GCP, Terraform) is not a milestone until you ask for it.

## 3. Cross-cutting rules I'll hold to
- Tenant id in every cache key, file path and vector query.
- Every new env var goes into .env.example; no secrets in code.
- Store model name/version on every embedding and resolution; prompts are
  versioned files.
- Small commits whenever tests pass.

## 4. Changes to the spec (agreed 2026-11-25)

Ordered by impact. Each one says what the spec says, the problem, and what we
do instead. All accepted; 4.11 accepted with a modification.

**4.1 Auth: let Clerk handle identity only, and keep orgs/roles in our DB.**
§4 says "managed auth with organisations". If Clerk orgs own membership, we
duplicate roles, jurisdiction restrictions and workspace ids, and keep them in
sync through webhooks, while RLS needs them in Postgres anyway.
→ Clerk (or an alternative) verifies who the user is; workspaces, memberships
and roles live only in our DB. One more point: Clerk is US-hosted, and for EU
HR customers that should be a conscious choice. EU-hostable alternatives are
Zitadel Cloud and WorkOS (WorkOS is better if enterprise SSO is needed soon).
Your call (§5).

**4.2 Jurisdiction at version level doesn't fit real handbooks.**
§6 gives one jurisdiction_id per document_version. Real global handbooks
contain country annexes ("Annex DE", "Annex FR") inside one file.
→ The version carries a default jurisdiction and scope; a section can narrow
them (inherit by default). Chunks keep the denormalised effective values, so
retrieval doesn't change.

**4.3 The node order makes per-topic jurisdiction rules impossible.**
§8 says the workspace configures whether work location or contracting entity
wins *per topic*, and the event date is extracted from ticket text. But §10
runs resolve_context *before* understand, which is where topic and the event
date are identified.
→ Order: intake → input_guardrails → understand → resolve_context → retrieve → …
Same nodes, two swapped.

**4.4 "Topic" is used everywhere but never modelled.**
The autonomy matrix (country × topic), always-human topics, the coverage map and
tag suggestions all depend on topics, but there is no topics table in §6.
→ Add per-workspace `topics` (seeded with defaults: leave, sick pay, notice,
payroll, expenses, …). Other tables missing from §6: api_keys,
webhook_events (for dedupe), autonomy_rules, guardrail_config,
livedata_tools, job_failures. I'll add each in the milestone that needs it.

**4.5 Precedence "most specific overrides" is unsafe at chunk level.**
A German sick-pay chunk shouldn't suppress a global expenses chunk, and two
chunks on the same topic may cover different rules.
→ An override applies only through an explicit `supersedes` relation, or
same-topic + more-specific level with a "replaces parent" flag that the editor
confirms at publish (we prompt when a same-topic document exists higher up
the chain). Otherwise both chunks are kept and labelled; a conflict is escalated.

**4.6 Changing the embedding model can't work with one embedding column.**
§7 says re-embed in the background and switch over when complete, so two
models coexist, possibly with different dimensions. A single `chunks.embedding`
column can't hold that.
→ A `chunk_embeddings(chunk_id, model, embedding)` table with one partial HNSW
index per model (an expression cast to that model's dimension), and an
`active_embedding_model` setting per workspace.

**4.7 Widget/email identity plus live-data tools is a data-leak risk.**
Requesters aren't logged in (§2). Anyone can type an employee id into a
widget or spoof an email From, then ask "how many leave days do I have?"
→ The widget requires a requester token signed by the customer's backend
(HMAC). Unverified sessions get policy answers only, with no tools and no
profile attributes. Email: a DKIM/SPF pass is required before linking to a
requester profile.

**4.8 "Synchronous with streaming" conflicts with "verify before showing".**
Streaming answer tokens shows unverified text that might be blocked.
→ Stream progress events over SSE (stage started/finished, evidence count,
checks), then send the final verified answer as one event.

**4.9 The contradiction check across all published documents is O(n²) LLM calls.**
→ M2: flag same-topic, overlapping-chain, overlapping-date sections for human
review (cheap, deterministic). An LLM contradiction check on those candidate
pairs only, added in M4 once the entailment model exists.

**4.10 Per-workspace calibration has no data for a new workspace.**
§9 and §10 say to calibrate per workspace on the eval set, but a new customer
has none, and 200 Northwind cases give wide error bars.
→ Global conservative defaults calibrated on Northwind. Per-workspace
calibration switches on once a workspace has ≥ N labelled outcomes from review
feedback. Draft-only mode is the safety net until then. Report calibration error
with confidence intervals, not a single "0.8 = 80%".

**4.11 Over-built: RAGAS + DeepEval + custom metrics; Langfuse + OTel + own audit trace.**
→ Evaluation: the custom deterministic metrics are the core (they're our
edge and cost nothing). Use DeepEval for LLM-judged faithfulness and
correctness (it integrates with pytest/CI). **Modified by decision:** RAGAS
stays, for synthetic test-set generation and as a secondary report in M5 —
it doesn't gate the build.
→ Observability: our DB is the system of record for the audit trace (§1
requires it anyway). Langfuse sits behind a tracing interface for dev ergonomics
from M4. OTel metrics wait for deployment. Only PII-masked text ever goes to
Langfuse.
→ Reranker: Cohere + fake only; self-hosted bge-reranker later, behind the same interface.
→ Retrieval cache (§17): defer to M6; measure first.

**4.12 Redis-broker Celery has no dead-letter queue, and visibility timeout can bite.**
→ DLQ = a `job_failures` table written on final failure, with an admin view and
retry. Set `visibility_timeout` above the longest OCR job; idempotency keys
cover redelivery. Pipeline code is async while Celery is sync: each task runs
`asyncio.run` with a per-process engine (documented in an ADR).

**4.13 M7 is too big for one milestone.** → Split into M7a/M7b (above).

**4.14 Writing the seed corpus and golden set is substantial work and needs your review.**
Eight-plus jurisdictions of clean-room policies, plus about 200 reviewed cases.
→ I draft Northwind policies from public government sources, with the source URL
and retrieval date on each clause, labelled as demo data and not legal advice.
The golden set grows in stages: ~60 in M3, ~200 in M5. You review in batches of 25.

**4.15 Smaller points**
- Presidio's default recognisers mask dates and amounts, which breaks
  event-date extraction and the verifier's number check. → Configure it to mask
  people, contacts, IDs and bank details only.
- GDPR deletion vs an append-only audit log. → Requester PII is kept out of
  audit payloads (they reference ids); deletion removes the PII tables, redacts
  stored ticket text, and appends a tombstone event.
- "Widen up the chain when nothing is found" (§9) is already covered, because
  the hard filter includes the whole chain. → Drop it as a separate step; keep
  the labelling ("no Bavaria-specific rule; German policy applies").
- Unknown scope value (e.g. worker type not known): match only scope-`*`
  content, and clarify if specific-scope content exists for the topic.
- Missing event date: default to the ticket's received date and state it in the answer.
- "Draft-only" and "approve-before-send" (§13) read alike. My reading:
  draft-only = we never send and the agent sends from their helpdesk;
  approve-before-send = we send after the agent clicks approve. Please confirm.
- Billing appears in roles but not in any milestone. → Out of scope for V1 unless you say otherwise.
- LangGraph adds little to a fixed graph. → Keep it, as the spec decides, but
  keep nodes as plain `state → partial state` functions so they can be tested
  without it.

## 5. Decisions (SPEC §22 + above)

| # | Decision | Status |
|---|----------|--------|
| 1 | Auth provider | **Decided:** Clerk for identity only; workspaces, memberships and roles in our DB (§4.1) |
| 2 | Embeddings provider | Open — decide at the start of M2; fake until then |
| 3 | LLM providers (small + strong) | Open — decide when first needed (M2 tag suggestions / M3); fake until then |
| 4 | Reranker | Open — decide at the start of M3; fake until then |
| 5 | Inbound email provider | Open — decide at the start of M7a |
| 6 | GCP project + budget | **Decided:** no deployment until asked |
| 7 | §4 proposals | **Decided:** 4.1–4.10, 4.12–4.15 accepted; 4.11 accepted with RAGAS kept |
| 8 | Autonomy modes | **Decided:** draft-only = we never send, agent sends from their helpdesk; approve-before-send = we send after the agent approves |

Go-ahead for M1 given 2026-11-25.
