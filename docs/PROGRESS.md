# Progress

## Current milestone
**M1 — Foundation** (go-ahead given 2026-11-25). Not started: no code yet.

## Done
- 2026-11-25: Read SPEC.md and wrote PLAN.md; plan approved with changes:
  - Clerk for identity only; workspaces, memberships and roles in our DB.
  - Spec changes 4.1–4.15 accepted (4.11 modified: RAGAS kept for test-set
    generation and as a secondary report in M5).
  - Hard pass marks added for M3, M4 and M5; gate runs use real providers.
  - M3 ablation report added.
- Git repo initialised; docs committed.

## In progress
Nothing.

## Next step
Start M1 in GitHub Codespaces, in this order:
1. Backend scaffold (uv, Python 3.12, ruff, mypy, pytest), compose.yaml with
   Postgres 16 + pgvector and Redis.
2. Tenancy tables + RLS (owner role for migrations, `app_user` NOBYPASSRLS,
   `SET LOCAL app.workspace_id`), failure-modes/tenancy.md, ADR-0001.
3. Catalog test (every workspace_id table has RLS + FORCE + policy) and the
   cross-tenant route suite.
4. Auth (Clerk JWT verifier + fake), ADR-0002.
5. Web shell, then CI (GitHub Actions).
Commit whenever tests pass.

## Open questions / blockers
- The local Windows machine has no Docker, no uv and only Python 3.10, so
  development is moving to GitHub Codespaces. The Codespace needs Docker
  (docker-in-docker), uv and Python 3.12; adding a `.devcontainer/` is part of
  the first M1 step.
- Providers for embeddings, LLMs, reranker and email: decide when the milestone
  needs them (fakes until then).
