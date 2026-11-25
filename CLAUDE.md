# Ticket Resolver

Multi-tenant SaaS that resolves support tickets from a company's own policy
documents, with answers correct for the person asking (country, worker type,
legal entity, event date). Full spec: docs/SPEC.md.

## Start of every session
1. Read docs/PROGRESS.md (what's done, what's next).
2. Read docs/PLAN.md and the docs/SPEC.md sections for the current milestone.
3. Before touching code, state in two lines what you'll do this session.

## Rules
- One milestone at a time. Never build ahead.
- Before building any pipeline step, write docs/failure-modes/<component>.md:
  how it fails, how we detect it, what we do instead, the test that proves it.
- Never silently deviate from SPEC.md. If something seems wrong, stop and explain.
- Every external service (LLM, embeddings, reranker, storage, helpdesk) sits
  behind an interface with a fake implementation; tests run offline and free.
- No secrets in code. Every new env var goes into .env.example.
- Tenant isolation: every tenant table has workspace_id with Postgres RLS;
  every new endpoint gets a cross-tenant access test.
- Small commits with clear messages whenever tests pass.
- No cloud deployment until I ask. Local Docker Compose only.
- Record significant decisions as short ADRs in docs/adr/.

## Stack
Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic, uv
Celery + Redis · PostgreSQL 16 + pgvector · LangGraph, LiteLLM
Next.js, TypeScript, Tailwind, shadcn/ui · Docker Compose
Later: GCP (Cloud Run, Cloud SQL, Memorystore, Cloud Storage)

## Commands (keep this list current as they're created)
- First-time setup (devcontainer runs it): bash .devcontainer/post-create.sh
- Start services: docker compose up -d
- Backend tests: cd backend && uv run pytest
- Lint and types: uv run ruff check . && uv run mypy app
- Migrations: uv run alembic upgrade head
- Frontend: cd web && npm run dev

## End of every session
Update docs/PROGRESS.md: done, in progress, next step, open questions.