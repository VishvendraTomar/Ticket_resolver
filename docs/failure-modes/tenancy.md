# Failure modes: tenancy and isolation

Scope: workspaces, users, memberships, audit events, the per-request database
context, and every API route that touches tenant data.

The invariant: **a request acting for workspace A can never read or change
data belonging to workspace B**, whatever bug exists in a query or a route.

| # | How it fails | How we detect it | What the system does instead | Test that proves it |
|---|--------------|------------------|------------------------------|---------------------|
| 1 | A query forgets `WHERE workspace_id = …` | Can't be detected per query — so we don't rely on it | RLS policy on every tenant table filters by `current_setting('app.workspace_id')` | `test_rls.py::test_app_role_sees_only_current_workspace` |
| 2 | A new table is added without RLS, or with RLS but not FORCE, or with no policy | Catalog test over `pg_class`/`pg_policies` on every run | Build fails; the table can't ship | `test_catalog.py::test_every_tenant_table_has_forced_rls_and_policy` |
| 3 | A global (non-workspace) table becomes readable by the app without a policy | Catalog test: every table `app_user` can access must have RLS + a policy, and global tables must be on an explicit, justified allowlist | Build fails | `test_catalog.py::test_app_accessible_tables_are_protected` |
| 4 | The app connects as a role that bypasses RLS (superuser, BYPASSRLS, Neon dashboard role, table owner) | Test connects with `APP_DATABASE_URL` and inspects its own role | Build fails; the role is created only by migration SQL with NOBYPASSRLS | `test_catalog.py::test_app_role_cannot_bypass_rls` |
| 5 | No workspace context is set (a bug in a dependency, a background job) | — | Policies compare against `NULL` → **zero rows**; inserts fail `WITH CHECK`. Fail closed, never open | `test_rls.py::test_no_context_sees_nothing` |
| 6 | Context leaks from one request to the next through the connection pool | — | Context is set with `set_config(..., is_local => true)`: it dies with the transaction | `test_rls.py::test_context_does_not_survive_transaction` |
| 7 | Code writes a row tagged with another workspace's id | — | `WITH CHECK (workspace_id = current workspace)` rejects it | `test_rls.py::test_cannot_insert_into_other_workspace` |
| 8 | User of A calls a route with B's workspace id in the path | Membership check in the single `workspace_member` dependency | 404 (not 403, so existence isn't revealed) | `test_cross_tenant.py` (every route) |
| 9 | User of A calls a route in A with an id that belongs to B (e.g. a membership id) | — | RLS hides B's row → 404 | `test_cross_tenant.py` (every route with an id) |
| 10 | A new route is added without a cross-tenant test | Suite enumerates every `/v1` route and checks it is registered | Build fails | `test_cross_tenant.py::test_every_route_has_a_cross_tenant_case` |
| 11 | The audit log is edited or deleted to hide a change | — | `UPDATE`/`DELETE` revoked from `app_user` **and** a trigger rejects them for every role | `test_rls.py::test_audit_events_are_append_only` |
| 12 | The last owner removes or demotes themselves, leaving a workspace nobody can manage | Service check | 409 Conflict | `test_members.py::test_cannot_remove_last_owner` |
| 13 | Fake auth is enabled in a real environment | Settings validation at startup | App refuses to start with `AUTH_PROVIDER=fake` unless `ENVIRONMENT` is `local` or `test` | `test_config.py::test_fake_auth_refused_outside_local` |
| 14 | Membership is checked at the app layer only; a bug there would let A set B's context | Cross-tenant suite on every route (#8, #10) | Known limit, recorded in ADR-0002: RLS scopes to the *current* workspace; membership is enforced in one dependency that every tenant route uses | `test_cross_tenant.py` |

## Not covered yet (later milestones)
- Background jobs (Celery) setting context: M2, same helper, tested then.
- Jurisdiction-restricted policy editors: M2, application layer.
- Workspace and requester deletion (GDPR) vs. the append-only audit trigger: M6.
