Ticket Resolver — Claude Code Build Prompt
Copy everything below into Claude Code.
You are the lead engineer building Ticket Resolver, a production-grade, multi-tenant SaaS that resolves customer support tickets from a company's own policy documents, with answers that are correct for the specific person asking. I'm a backend engineer (Python, FastAPI, Postgres, AWS) and I'll keep iterating on this with you, so build it to be easy to understand and extend.
0. How to work (read this first)
• Read this entire spec before writing any code. Then write docs/PLAN.md: repo layout, milestone breakdown, and any part of this spec you think is wrong, risky or over-built, with a better alternative. Wait for my go-ahead before starting Milestone 1.
• Work one milestone at a time (section 21). Each milestone ends with passing tests, a seed/demo script I can run, and a short update in docs/PROGRESS.md on what's done and what's next.
• Before building any pipeline step, write a short failure-modes note in docs/failure-modes/<component>.md: how it can go wrong, how we detect it, what the system does instead, and the test that proves it. This is required. The failure modes in this spec are a starting point; add the ones you discover.
• Record significant decisions as short ADRs in docs/adr/.
• Never silently deviate from the spec. If something doesn't make sense once you're in the code, stop and tell me why.
• Don't build features from later milestones early. No speculative abstractions.
• No secrets in code; everything through environment variables, with a .env.example.
• Every external dependency (LLM, embeddings, reranker, helpdesk, customer APIs) goes behind an interface with a fake implementation, so the test suite runs offline and free.
1. What we're building and why
Most AI support bots give vague answers and hand off to humans constantly. The good ones (Deel's is the benchmark) answer in two or three precise bullets that fully resolve the issue, because they know exactly who is asking and which policy applies to that person.
Ticket Resolver's edge is policy-grounded, jurisdiction-aware resolution:
• The right answer depends on the requester: country (and state/region), worker type, legal entity, and the date the event happened.
• Policies are organised by jurisdiction (Global → Region → Country → State) plus custom scope fields each company defines, with versions and effective dates.
• Every answer is 1–3 bullets, each citing the exact clause and policy version it came from.
• When evidence isn't good enough, it asks one clarifying question or hands off to a human. It never guesses.
• Every answer is auditable: inputs, retrieved evidence, policy versions, model, prompt version, checks passed.
First customers: global HR, EOR, payroll, staffing and workforce platforms; then fintech, marketplaces, insurance — any company whose support answers change by country. It must work with any company's documents, not one company's.
Do not reuse code, prompts, documents or data from any previous employer of mine. All demo data comes from public sources (section 16).
2. Users and roles
• Owner/Admin: workspace settings, autonomy rules, billing, members.
• Policy editor: uploads, tags, versions and publishes documents; can be limited to certain jurisdictions.
• Agent: reviews drafts; approves, edits, or rejects with a reason.
• Viewer/Auditor: read-only access to answers, evidence and the audit log.
• Integrator: uses API keys.
• Requester: the end customer or worker receiving the answer (not a logged-in user in V1).
3. Principles
1.  Scope before search. Which documents are allowed is decided by the requester's context and enforced in the database query, never left to semantic similarity.
2.  No evidence, no answer. Weak or conflicting evidence means clarify or escalate.
3.  Short and cited. 1–3 bullets plus an optional one-line next step; every bullet cited.
4.  Deterministic pipeline, not free-roaming agents. Fixed steps with a shared typed state; the model gets autonomy only where a step genuinely needs it.
5.  Measure everything. No retrieval, prompt or model change ships without an evaluation run.
6.  Tenant isolation is absolute. Enforced in the database and tested.
7.  Cheap by default. Small models wherever possible; cost per ticket is tracked.
4. Tech stack (decided; challenge it in PLAN.md if needed)
• Backend: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic, uv, Ruff, mypy, pytest.
• Jobs: Celery with Redis as broker.
• Database: PostgreSQL 16 with pgvector 0.8 or later (HNSW, iterative index scans enabled so filtered vector search still returns enough rows) and Postgres full-text search. Row-Level Security for tenant isolation.
• Cache and rate limits: Redis.
• Files: Google Cloud Storage, behind a storage interface (local filesystem or fake-gcs-server in development).
• Parsing: Docling; OCR for scanned PDFs.
• Models: all LLM calls through LiteLLM; embeddings and reranker behind interfaces. Defaults: a multilingual embedding model; Cohere Rerank, with a self-hosted multilingual option (bge-reranker-v2-m3); a small fast model for classification, rewriting and judging; a strong model for final answers. Store model name and version with every embedding and every answer.
• Orchestration: LangGraph for the resolution flow.
• PII: Microsoft Presidio.
• Evaluation: RAGAS and DeepEval, plus custom metrics (section 16).
• Observability: Langfuse (Langfuse Cloud, EU region, to start; self-host later) for LLM traces, prompt versions and cost; Sentry for errors; OpenTelemetry metrics.
• Frontend: Next.js (App Router), TypeScript, Tailwind, shadcn/ui.
• Auth: managed auth with organisations (default Clerk; confirm with me).
• Infra: Docker, Docker Compose locally, Terraform, GitHub Actions. Hosted on Google Cloud Platform in an EU region (europe-west3, Frankfurt).
5. Repository layout (suggested)
ticket-resolver/
  backend/
    app/
      core/          # config, db, logging, security
      tenancy/       # workspaces, members, roles, RLS
      knowledge/     # documents, versions, jurisdictions, scope fields
      ingestion/     # parse, chunk, tag, embed
      context/       # requester profiles, jurisdiction chain
      retrieval/     # filters, hybrid search, fusion, rerank, precedence
      resolution/    # LangGraph flow, generation, answer schemas
      verification/  # verifier
      guardrails/    # input and output checks
      handoff/       # escalation rules and payloads
      tools/         # live-data tool framework and connectors
      evaluation/    # golden sets, runners, metrics
      integrations/  # chatwoot, email intake, web widget, webhooks
      api/           # routers
    workers/         # celery app and tasks
    tests/
  web/               # Next.js app
  eval/              # datasets and reports
  seed/              # demo workspace and public policy data
  infra/             # docker-compose, terraform
  docs/
6. Core data model
Every tenant table carries workspace_id, protected by RLS.
• workspaces, users, memberships (role, optional jurisdiction restrictions)
• jurisdictions: tree (global, region, country, state) with ISO codes and parent_id
• scope_fields: per-workspace custom dimensions (e.g. worker_type ∈ {employee, contractor}); a document can use a value or * for all
• documents: title, owner, source, language, status
• document_versions: version number, effective_from, effective_to, jurisdiction_id, scope (JSONB), status (draft / published / retired), relations to other versions (supersedes, supplements), file hash
• sections: parent units (heading path, clause number, text) and cross-references between sections
• chunks: section_id, text, context header, content hash, embedding, embedding_model, tsvector, plus denormalised jurisdiction_id, scope, effective dates and version status for fast filtering
• glossary_terms: per-workspace synonyms ("PTO" = "annual leave")
• requesters: external id and attributes, with dated attribute history (people move countries)
• tickets, ticket_messages
• resolutions: status (answered / clarify / escalated), bullets with citations, confidence components, escalation reason, versions used, model, prompt version, cost, latency
• feedback: approve / edit / reject, edited text, reason
• eval_sets, eval_cases, eval_runs, eval_results
• audit_events (append-only), usage_events
Constraints that make bad states impossible: two published versions of the same document with the same jurisdiction and scope cannot have overlapping effective dates; nothing is published without a jurisdiction; chunks cannot outlive their version.
7. Ingestion pipeline
Upload → store the original in Cloud Storage and hash it (skip identical files) → queue a job → parse with structure kept (headings, numbered clauses, tables as Markdown) → OCR if needed → split into sections (heading path + clause number) → chunk sections at roughly 300–500 tokens, never splitting a table or a numbered clause, with parent sections capped around 1,500 tokens → prepend a context header to each chunk (e.g. "Northwind Leave Policy › Germany › §4.2 Annual leave — applies to: Germany, employees, valid from 2026-01-01") → AI suggests jurisdiction, scope and topic tags → a human confirms → embed in batches, reusing embeddings when a chunk's content hash is unchanged from the previous version → index → version ready → editor publishes.
Failure modes to handle:
• Parsing breaks tables or clause numbering: keep tables whole; produce a parsing-quality report per document; show editors a section preview before publishing.
• Scanned or poor-quality PDFs: OCR confidence score; flag for review.
• Wrong jurisdiction tag (silently poisons retrieval): AI tag suggestions are never auto-published; a coverage map shows what each country actually has.
• Overlapping or contradictory versions: the database constraint blocks overlaps; a contradiction check across published documents in the same scope flags conflicts to editors.
• Cross-references ("see Annex B"): store section references so retrieval can follow one hop.
• Changing the embedding model: embeddings are tagged by model; re-embed in the background; switch over only when complete.
• Job crashes halfway: idempotent steps keyed by version id; status visible in the UI; retry button.
8. Requester context and jurisdiction resolution
Before any search, build a RequesterContext: country, state/region, worker type, legal entity, other scope values, language, event date. Each value records its source.
Sources, in priority order: explicit fields from the integration or API → requester profile (with dated history) → extraction from the ticket text.
From it, build the jurisdiction chain (e.g. DE-BY → DE → EU → GLOBAL) and the scope filter.
Failure modes:
• Country unknown: ask one clarifying question; never silently default to Global.
• Signals disagree (profile says Germany, ticket says "I moved to France"): don't silently override; ask, or answer for the profile valid on the event date and say so.
• Two locations apply (works in Germany, contracted through a UK entity): support both work-location and contracting-entity dimensions; the workspace configures which wins for which topic.
• Event date matters ("my leave last March"): extract it; if the policy changed in between, use the version valid then and name it.
• Stale profile: dated attribute history.
9. Retrieval pipeline
1.  Query understanding (small model): topic, intent, sub-questions (split multi-question tickets), 2–3 rewritten search queries using the workspace glossary, query language.
2.  Hard filter in SQL: workspace, published, jurisdiction in the chain, scope matches or *, and effective_from ≤ event date < effective_to.
3.  Hybrid search inside the filtered set, per rewritten query: vector (pgvector HNSW with iterative scan) plus keyword (language-aware full-text).
4.  Fusion: Reciprocal Rank Fusion across all result lists.
5.  Rerank: top ~50 down to top ~8.
6.  Expand: attach each chunk's parent section; follow one cross-reference hop when a chunk points to another section.
7.  Precedence: label each chunk with its level (state / country / region / global). Default: the most specific overrides. Respect explicit supersedes and supplements relations — a global minimum plus a country addition both apply.
8.  Evidence assessment: an evidence score from reranker scores and coverage of each sub-question.
Failure modes:
• Filters too strict, nothing found: widen only up the chain (country → region → global), clearly labelled in the answer and trace; never sideways to another country.
• Filtered vector search returns too few rows: iterative scan; fall back to exact search when the filtered set is small.
• Jargon or language mismatch: glossary expansion, multilingual embeddings, translate the query when needed.
• A similar policy from the wrong scope: impossible by design (hard filter) — prove it with tests.
• A relevant clause split across chunks: parent expansion.
• Thresholds that mean nothing: calibrate evidence and confidence thresholds on the eval set, per workspace; never hard-code guesses.
10. Resolution flow (LangGraph)
A fixed graph with one typed ResolutionState (Pydantic) shared by all nodes — nodes communicate only through this state, never by chatting with each other.
Nodes: intake → input_guardrails → resolve_context → understand → retrieve → assess_evidence → optional call_tools → generate → verify → output_guardrails → decide.
Branches: missing context → clarify; weak or conflicting evidence → escalate; verifier fails → regenerate once, then escalate.
Hard caps: one clarifying question per turn and two per ticket; one regeneration; at most three tool calls. Every node writes its inputs, outputs, timing and cost to the trace.
Answer schema (structured output, validated with Pydantic):
• status: answered | clarify | escalated
• bullets: 1–3 items, each {text (≤ 300 chars), citation_ids (≥ 1)}
• next_step: optional, one line
• clarifying_question: when status is clarify
• escalation_reason: enum, when escalated
• jurisdiction_used, versions_used
• partial: true when some sub-questions are answered and the rest escalated — the reply must say so plainly
Generation rules: answer only from the evidence given; each chunk arrives labelled with id, jurisdiction and version; cite only ids from that set; write in the requester's language and the workspace's tone; never give legal advice beyond the policy text.
Confidence is not the model's self-rating. Combine the evidence score, verifier pass rate and sub-question coverage, with the model's self-assessment as one minor input. Calibrate on the eval set so 0.8 means roughly 80% of such answers are correct.
Failure modes: rules blended from two countries (prevented by filtering plus the verifier's jurisdiction check); over-long answers (schema limits); silently answering only part of a multi-question ticket (partial flag).
11. Verifier
For each bullet, check that:
1.  It has at least one citation.
2.  Every cited id was in the evidence given to the model (no invented citations).
3.  The cited chunk's jurisdiction is in the requester's chain and its version is valid on the event date.
4.  Every number, date, amount and duration in the bullet appears in the cited text, after normalisation ("20 days" = "twenty days"; "€1,000" = "1000 EUR").
5.  An entailment check by a small model — "Does this text support this claim? supported / partially / not supported" — returns supported, with a one-line reason.
A failed bullet is dropped if the rest still answers the question; otherwise regenerate once; then escalate.
Measure the verifier itself against human labels. If it rejects good answers too often, escalations explode; if it passes bad ones, trust breaks. Report both rates.
12. Guardrails
A pipeline of check functions, each returning {passed, severity (block | warn), reason}, configurable per workspace and stored on the resolution.
• Input: detect and mask personal data before any LLM call (placeholders restored in the final reply only where appropriate); screen ticket text for prompt injection; route blocked or always-human topics.
• Documents: text inside uploaded documents is data. Instructions found in documents are never followed; documents are wrapped and labelled in prompts.
• Output: schema validation; the verifier result; forbidden commitments ("we will refund you", "guaranteed") unless the policy grants them; required disclaimers per jurisdiction and topic; no personal data about anyone other than the requester; length and tone.
Any block result stops the reply from being sent.
13. Human handoff
Escalate when any of these hold:
• Jurisdiction or key context is still unknown after one clarifying question.
• The evidence score is below the calibrated threshold, or two equally specific policies conflict.
• The verifier fails after one regeneration.
• Confidence is below the threshold set for that country × topic (the autonomy matrix).
• The topic is configured as always-human (e.g. termination, legal threats, harassment, data-deletion requests, formal complaints).
• The requester asks for a human, shows strong negative sentiment, or the ticket was reopened.
• A live-data tool fails, or its data contradicts the policy.
• The request needs an action the system isn't allowed to take.
Handoff payload: a one-paragraph summary, requester context, evidence found, the draft (if any), the escalation reason (enum), a suggested queue. Escalation reasons feed analytics — they are the to-do list for improving the knowledge base.
Autonomy modes per workspace: draft-only (default; an agent approves everything) and approve-before-send. Auto-send exists behind a flag, off in V1.
14. Live-data tools
A framework for read-only lookups in the customer's systems (e.g. get_leave_balance, get_next_payroll_date, get_contract_summary).
• Tools are defined with JSON schemas and registered per workspace with encrypted credentials.
• The requester's identity is injected server-side. The model never chooses whose data to fetch; it can only call a tool for the current requester.
• Timeouts, one retry, a circuit breaker; results cached briefly per requester.
• Tool results are cited as account data, separate from policy citations.
• Read-only in V1. Build a mock HR connector for demos and tests.
• The flow calls a tool only when the policy alone can't answer the question (e.g. "how many days do I have left?").
15. Background jobs
Use Celery; don't build a custom job system. Retries, scheduling, dead letters and monitoring are solved problems and not our product.
• Queues: ingestion, resolution, evaluation, maintenance, with per-queue concurrency so a large evaluation run never starves live tickets.
• Tasks are idempotent, keyed by entity id; late acknowledgement; retries with exponential backoff and jitter.
• Poison jobs go to a dead-letter queue with an admin view and a retry action.
• Webhook events are deduplicated by (workspace, provider, event id) because helpdesks resend them.
16. Evaluation
Clean-room demo data: a fictional company, "Northwind Global", with policies for at least Germany, France, Spain, the UK, India and two US states, plus global and EU policies, written from public government sources (leave, sick pay, notice periods, payroll timing, expenses). Include tricky cases on purpose: a country override of a global rule, a supplement rule, a policy that changed mid-year, a cross-reference.
Golden set: about 200 cases to start, each with requester context, ticket text, expected status (answered / clarify / escalated), a reference answer and expected citations. Mix hand-written cases, synthetic cases (RAGAS test-set generation, reviewed by me) and, later, real anonymised tickets.
It must include trap cases: wrong-country lures, outdated-version lures, unanswerable questions, prompt injection in tickets and in documents, multi-question tickets, missing context.
Metrics:
• Retrieval: context precision and recall (RAGAS), hit rate, MRR.
• Answers: faithfulness, answer correctness (RAGAS / DeepEval), citation precision.
• Custom: jurisdiction accuracy (every citation in-chain and valid on the event date); decision accuracy (answered vs clarify vs escalate matches expected); over- and under-escalation rates.
• Operations: latency p50 and p95, cost per ticket.
Where evaluation runs:
• CI: a fast DeepEval regression subset on every pull request; a nightly full run with real models. Fail the build when key metrics drop beyond a set margin.
• Replay: upload historical tickets as CSV and compare against what agents actually sent. This doubles as the sales demo.
• Production: sample a share of live resolutions for judge-model scoring; track agent edit rate, rejection reasons and reopen rate by country and topic. Calibrate the judge against my labels and report agreement.
17. Cost control
• Small model for classification, rewriting, entailment and judging; strong model only for the final answer.
• Static system prompt placed first so provider prompt caching applies.
• Rerank so ~8 chunks reach the model, not 30.
• Reuse embeddings by content hash; batch embedding calls.
• Retrieval cache keyed by (workspace, query hash, jurisdiction chain, published versions). No semantic answer cache in V1 — the same question has different answers per jurisdiction and version.
• Per-workspace monthly budget and a per-ticket cost cap; cost per ticket and per stage visible in Langfuse and the analytics page.
18. Security and multi-tenancy
• RLS on every tenant table, plus tests that try to read across workspaces through every endpoint.
• Caches, file paths and vector queries always include the workspace id.
• Encryption in transit and at rest; connector credentials encrypted with a KMS key.
• API keys stored hashed, scoped and revocable; rate limits per key and per workspace.
• Append-only audit log of who changed which policy, and every resolution's full trace.
• Retention settings; full deletion of a workspace or requester on request (GDPR); never train on customer data.
19. Production deployment and operations
• Local: Docker Compose (api, worker, web, Postgres with pgvector, Redis, fake-gcs-server; Chatwoot as an optional profile for integration tests).
• Environments: local → staging → production; Alembic migrations run in the pipeline.
• Launch hosting: GCP europe-west3 (Frankfurt), all in Terraform: Cloud Run for the API and web app; Celery workers on Cloud Run worker pools (or a small Compute Engine instance if worker pools don't fit); Cloud SQL for PostgreSQL 16 with pgvector on a private IP; Memorystore for Redis; Cloud Storage; Secret Manager; Cloud KMS; Artifact Registry; Direct VPC egress so Cloud Run reaches Cloud SQL and Memorystore privately; budget alerts. Use Postgres, not Firestore: the design depends on SQL filters, pgvector and Row-Level Security. Later: raise the Cloud SQL tier and Cloud Run limits as load grows; add read replicas before considering anything more complex. Keep the app 12-factor so moving is configuration, not a rewrite.
• CI/CD (GitHub Actions): lint, type-check, tests, eval subset, build images, deploy to staging, manual promotion to production.
• Operations: health checks; structured JSON logs with trace ids; Sentry; dashboards for latency, errors, queue depth, cost per ticket, resolution and escalation rates; alerts on spikes.
• LLM resilience: timeouts, retries with backoff, fallback model via LiteLLM; if every provider fails, escalate with reason "system unavailable" — never fail silently.
• Backups: daily, with point-in-time recovery, and a tested restore runbook.
20. API and web app
API (versioned under /v1): documents and versions, publish, jurisdictions and scope fields, requesters, POST /v1/tickets/resolve (synchronous with streaming, for the console and API customers), webhooks for async work, feedback, eval sets and runs, analytics, API keys.
Channels: an embeddable web chat widget, email intake (inbound email via a provider webhook), and Chatwoot (open-source, self-hostable helpdesk) via its webhooks and API. Every helpdesk sits behind one HelpdeskConnector interface (receive ticket, post draft as a private note, update status), so Zendesk, Freshdesk or Intercom can be added later without touching the pipeline.
Web app screens:
• Onboarding.
• Knowledge base: upload, section preview, tagging, versions, publish.
• Coverage map: countries × topics, showing gaps.
• Test console: pick a requester profile, type a ticket, see the answer, evidence, checks passed and cost.
• Review inbox.
• Evaluation reports.
• Analytics.
• Settings: autonomy matrix, guardrails, glossary, members, API keys.
21. Milestones
1.  Foundation: repo, auth, workspaces, roles, RLS with cross-tenant tests, Docker Compose, CI. No cloud deployment yet; that comes later, when I ask for it.
2.  Knowledge base: upload, parsing, sections, chunking, tagging, versions with database constraints, publish, coverage map, seeded demo company.
3.  Retrieval: requester context, jurisdiction chain, filtered hybrid search, fusion, reranking, precedence; retrieval metrics on the golden set.
4.  Resolution: LangGraph flow, structured answers, verifier, guardrails, handoff rules, test console.
5.  Evaluation: full golden set with traps, RAGAS and DeepEval, CI gate, replay report.
6.  Review and analytics: inbox, feedback, analytics, API keys, cost tracking.
7.  Integration and launch: Channels: embeddable web widget, email intake, and Chatwoot (webhook in, draft posted as a private note), live-data tool framework with the mock connector, public sign-up.
Every milestone is done only when: tests pass, its failure-mode notes are written, its demo script runs, and PROGRESS.md is updated.
22. Open decisions — ask me before locking them in
• Auth provider (Clerk or an alternative).
• Which LLM, embedding and reranker providers to start with (I'll supply the keys).
• The GCP project to deploy into and the monthly budget.
• Inbound email provider for email intake (e.g. SendGrid or Mailgun).