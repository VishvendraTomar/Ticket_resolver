# ADR-0004: Every external service sits behind a provider interface

- Status: Accepted
- Date: 2026-11-25
- Implements: CLAUDE.md rule "every external service behind an interface with
  a fake", PLAN §1 (`providers/`) and the M1 docs list. (PLAN numbered this
  ADR-0003; see the numbering note in ADR-0002.)

## Context
The system depends on paid, networked, non-deterministic services: identity
(Clerk), LLMs (via LiteLLM), embeddings, a reranker, object storage, document
parsing, PII detection (Presidio), tracing (Langfuse), and later helpdesks and
inbound email. Tests must run offline and free, and be deterministic. Vendors
for embeddings, LLMs and the reranker are still open (PLAN §5). Some are
likely to change (EU hosting, ADR-0003), and the quality gates must say
exactly which model produced a number.

## Decision

**One place, one shape.** Each service lives in
`backend/app/providers/<name>/`:

| File | Contents |
|------|----------|
| `base.py` | A `typing.Protocol` for the operations the app needs, the value types it exchanges (frozen dataclasses or Pydantic models) and the provider's own exceptions. Nothing vendor-specific. |
| `fake.py` | A deterministic, offline implementation. |
| `<vendor>.py` | One real implementation per vendor, e.g. `clerk.py`. |
| `__init__.py` | `get_<name>()` reads Settings and returns the selected implementation. Vendor modules are imported lazily, so the fake path never needs vendor SDKs. |

`app/providers/auth/` (ADR-0003) is the reference implementation.

**Rules.**
1. **App code depends only on `base.py`.** Services, routers and tasks import
   the Protocol and receive an instance through FastAPI dependencies, or
   through an explicit argument in Celery tasks. They never import a vendor
   module or SDK.
2. **The interface is ours, shaped by our use cases**, not a mirror of the
   vendor API. Vendor errors are translated into the provider's exceptions
   (e.g. `InvalidToken`). Nothing vendor-typed leaks past `<vendor>.py`.
3. **Fakes are deterministic and the default in tests.** Same input, same
   output, no network, no clock or randomness unless injected. A fake may
   be simple, but it must honour the contract the app relies on. Example: a
   fake embedder returns fixed-dimension vectors where identical text gives
   identical vectors.
4. **Fakes never reach real environments.** Settings refuse a fake provider
   unless `ENVIRONMENT` is `local` or `test`, as `AUTH_PROVIDER=fake` already
   does.
5. **Selection is configuration.** Each provider has a `<NAME>_PROVIDER`
   setting plus its vendor settings. Every new variable goes into
   `.env.example`. Secrets only come from the environment.
6. **Contract tests.** Behaviour the app depends on is tested once against
   the Protocol and run against the fake. The same tests run against the
   real implementation when marked `@pytest.mark.live`, which is skipped
   unless keys are set.
7. **Provenance is part of the contract.** Implementations that produce data we
   store or score (embeddings, LLM answers, reranker scores) report the
   provider, model name and model version with the result. SPEC §4 requires
   it stored with every embedding and answer, and gate reports need it
   (PLAN §2).
8. **Resilience lives in the implementation or in LiteLLM**, not in callers:
   timeouts on every network call, bounded retries with backoff, model
   fallback through LiteLLM for LLMs. When everything fails, the provider
   raises its typed "unavailable" error, and the caller escalates with
   reason "system unavailable" (SPEC §19); it never fails silently.
9. **Data minimisation at the boundary.** Only PII-masked text goes to
   tracing (PLAN §4). Each provider's module docstring says what data leaves
   our system and to whom.

**LLMs specifically.** All calls go through LiteLLM (SPEC §4), wrapped in our
`llm` provider. LiteLLM handles vendor routing and fallback. Our interface
pins the operations we use (structured output against a Pydantic schema,
plain completion), the model tier ("small" or "strong") and the cost and
provenance reporting.

## Planned providers

| Provider | Fake | Real (first) | Needed from |
|----------|------|--------------|-------------|
| auth | `fake\|sub\|email\|name` tokens | Clerk (ADR-0003) | M1 ✓ |
| storage | in-memory / local FS | fake-gcs-server locally, GCS in cloud | M2 |
| parser | text passthrough | open (PLAN §5) | M2 |
| embeddings | hash-based fixed vectors | open, multilingual (PLAN §5 #2) | M2 |
| llm | scripted responses per prompt id | LiteLLM → open (PLAN §5 #3) | M2/M3 |
| reranker | score by term overlap | Cohere; bge-reranker later | M3 |
| pii | regex masker | Presidio | M4 |
| tracing | in-memory recorder | Langfuse (EU) | M4 |
| helpdesk, email intake | recorded fixtures | Chatwoot first; email provider open | M7a |

Each one gets its interface, fake, contract tests and failure-modes note in
the milestone that first needs it. None are built ahead (CLAUDE.md).

## Alternatives considered
- **Call vendor SDKs directly and mock them in tests** (`unittest.mock`,
  `respx`). Tests then pin vendor call shapes rather than our contract, break
  on SDK upgrades, and switching vendors touches every call site.
- **Use LiteLLM as the only abstraction.** It covers LLMs and embeddings but
  not storage, PII, reranking or tracing, and its types would leak into app
  code. We use it *inside* the `llm` provider.
- **A dependency-injection framework.** FastAPI dependencies plus explicit
  arguments in tasks are enough. Tests override `get_<name>` with
  `app.dependency_overrides`.

## Consequences
- Adding a vendor is one new `<vendor>.py` plus settings; app code doesn't
  change.
- Each provider costs a Protocol, a fake and contract tests up front. That's
  intentional: it keeps the default suite offline, free and deterministic.
- Fakes can drift from real behaviour. The live-marked contract tests are
  the check, and gate runs (M3–M5) always use real providers.
