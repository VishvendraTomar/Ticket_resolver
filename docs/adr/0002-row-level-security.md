# ADR-0002: Tenant isolation with Postgres Row-Level Security

- Status: Accepted
- Date: 2026-11-25
- Implements: SPEC §4 (RLS for tenant isolation), PLAN M1
- Numbering note: PLAN M1 listed "ADR-0001 RLS mechanism". ADR-0001 was taken
  by the (superseded) Neon decision, so the RLS ADR is 0002, auth is 0003, and
  provider interfaces will be 0004.

## Context
Every workspace's policy documents, tickets and answers must be invisible to
every other workspace. A filter in application code (`WHERE workspace_id = …`)
leaks the moment one query forgets it, and nothing catches that per query. The
spec asks for RLS. This ADR fixes *how* we use it, because RLS is easy to set up
in a way that silently does nothing (superuser connections, table owners,
session-level settings leaking through a pool).

## Decision

**Two database roles.**
- *Owner* (`DATABASE_URL`): runs migrations, owns every object, and is used by
  the catalog tests. The running app never gets this URL.
- `app_user` (`APP_DATABASE_URL`): everything the app does. Created by migration
  0001 in SQL as `LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE
  NOINHERIT`, with the password read from `APP_DATABASE_URL`, so it never sits
  in code. It owns no tables.

**Context is transaction-local.** `app.core.db.set_context` sets
`app.auth_subject`, `app.user_id` and `app.workspace_id` with
`set_config(key, value, is_local => true)`. The values disappear at commit or
rollback, so they can't leak to the next request through the connection pool,
and the scheme stays correct behind a transaction-mode pooler. Celery tasks
use the same helper (M2).

**Fail closed.** Policies read the context through `STABLE` SQL functions
(`app_current_workspace_id()` etc.) that return `NULL` when a setting is missing
or empty. With no context, every comparison is false: reads return zero rows,
writes fail `WITH CHECK`.

**Tenant tables** (`workspaces`, `memberships`, `audit_events`, and every future
table with `workspace_id`) get `ENABLE` **and** `FORCE ROW LEVEL SECURITY`, plus
a policy per command keyed on `app_current_workspace_id()`. Without FORCE the
table owner bypasses RLS.

**Two contexts.**
- *Account context* (no workspace set): a user sees only their own
  memberships and the workspaces they belong to. Used by `/v1/me` and by the
  membership check.
- *Workspace context* (workspace set): everything is scoped to that one
  workspace, including memberships, so a user's other workspaces don't show.

**Entering a workspace** happens in one place: the `Access` dependency
(`tenancy.deps`) checks membership in account context, then sets
`app.workspace_id`. Not a member and "doesn't exist" both return 404, so ids
can't be probed.

**`users` is global** (one person, many workspaces). It has RLS policies but is
not FORCE'd, so one owner-defined `SECURITY DEFINER` function,
`app_find_user_id_by_email`, can look up a user by email for "add member". It
returns only an id, works only inside a workspace context, and is on an
explicit allowlist in the catalog test.

**Explicit grants only.** `app_user` gets per-table privileges; a new table is
invisible to the app until a migration grants it. `audit_events` gets
`SELECT, INSERT` only, and a trigger rejects `UPDATE`, `DELETE` and `TRUNCATE`
for every role, the owner included.

**Guarded by tests that run on every build** (docs/failure-modes/tenancy.md):
- Catalog: any table with `workspace_id` lacks RLS, FORCE or a policy → fail.
  Any table `app_user` can reach without RLS and a policy, unless it's
  allowlisted → fail. `app_user` is superuser, has BYPASSRLS, can assume a
  role that does, or owns any table → fail. `alembic_version` isn't
  reachable by the app. A `SECURITY DEFINER` function
  that isn't allowlisted → fail.
- Behaviour: no context sees nothing; context dies with the transaction;
  writing another workspace's id is rejected; audit is append-only.
- Cross-tenant: the suite enumerates every FastAPI route and fails if a route
  has no cross-tenant case.

## Alternatives considered
- **App-layer filtering only.** Simplest, but one missed `WHERE` is a breach,
  and review can't reliably catch it. We still filter explicitly in queries,
  as a second layer.
- **Schema or database per tenant.** Strong isolation, but migrations, pgvector
  indexes and connection pools multiply with the number of tenants, and
  cross-tenant admin queries get harder. Not justified at our scale; we can
  move a large tenant to its own database later, since the app is 12-factor.
- **A Postgres role per tenant.** Role explosion and a pool per tenant.
- **Session-level `SET`.** Leaks between requests that share a pooled
  connection.

## Consequences
- Every new tenant table needs `workspace_id`, ENABLE + FORCE RLS, policies and
  explicit grants in its migration. The catalog test fails the build until
  all four are present.
- RLS covers the *current* workspace. Which workspace a user may enter is an
  app-layer membership check (failure mode #16). It sits in one dependency
  that every tenant route uses, and the cross-tenant suite covers every route.
- Policy subqueries on `memberships` cost an index lookup per row checked
  (`ix_memberships_user_id`, unique `(workspace_id, user_id)`). Re-check query
  plans when M2 adds large tables. Those tables compare `workspace_id`
  directly, with no subquery.
- The owner URL must stay out of the app's environment in every deployment.
- In Compose the owner is the Postgres superuser. On Cloud SQL it won't be,
  so re-check the `SECURITY DEFINER` lookup and the catalog test when we
  deploy.
