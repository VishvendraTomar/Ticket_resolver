# Failure modes: tenancy, isolation and auth

Scope: workspaces, users, memberships, audit events, the per-request database
context, identity verification, every API route that touches tenant data, and
the web shell that calls them. Design: ADR-0002 (RLS), ADR-0003 (Clerk identity
only).

The invariant: **a request acting for workspace A can never read or change
data belonging to workspace B**, whatever bug exists in a query, a route or the
UI.

Last reviewed: 2026-11-25 (M1 close-out). Every test named below exists and
runs in CI (`.github/workflows/ci.yml`).

## Database (RLS)

| # | How it fails | How we detect it | What the system does instead | Test that proves it |
|---|--------------|------------------|------------------------------|---------------------|
| 1 | A query forgets `WHERE workspace_id = …` | Can't be detected per query — so we don't rely on it | RLS policy on every tenant table filters by `app.workspace_id` | `test_rls.py::test_app_role_sees_only_current_workspace` |
| 2 | A new table is added without RLS, or with RLS but not FORCE, or with no policy | Catalog test over `pg_class`/`pg_policies` on every run | Build fails; the table can't ship | `test_catalog.py::test_every_tenant_table_has_forced_rls_and_policy` |
| 3 | A global (non-workspace) table becomes readable by the app without a policy | Catalog test: every table `app_user` can access must have RLS + a policy; global tables are on an explicit, justified allowlist | Build fails | `test_catalog.py::test_app_accessible_tables_are_protected` |
| 4 | The app connects as a role that bypasses RLS (superuser, BYPASSRLS, a member of such a role, a role created by hand in a hosting dashboard) | Test connects with `APP_DATABASE_URL` and inspects its own role and memberships | Build fails; `app_user` is created only by migration SQL with NOSUPERUSER NOBYPASSRLS NOINHERIT | `test_catalog.py::test_app_role_cannot_bypass_rls` |
| 5 | The app role owns a table (owners bypass non-FORCE'd RLS and can alter policies) | Catalog test | Build fails | `test_catalog.py::test_app_role_owns_no_tables` |
| 6 | No workspace context is set (a bug in a dependency, a background job) | — | Policies compare against `NULL` → **zero rows**; inserts fail `WITH CHECK`. Fail closed, never open | `test_rls.py::test_no_context_sees_nothing` |
| 7 | Context leaks from one request to the next through the connection pool | — | Context is set with `set_config(..., is_local => true)`: it dies with the transaction | `test_rls.py::test_context_does_not_survive_transaction` |
| 8 | Code writes a row tagged with another workspace's id | — | `WITH CHECK (workspace_id = current workspace)` rejects it | `test_rls.py::test_cannot_insert_into_other_workspace` |
| 9 | Code moves an existing row to another workspace with `UPDATE` | — | `WITH CHECK` on UPDATE policies rejects it | `test_rls.py::test_cannot_move_a_row_to_another_workspace` |
| 10 | A `SECURITY DEFINER` function is added that reads across tenants | Catalog test lists every SECURITY DEFINER function in `public` | Build fails unless allowlisted with a justification (today: only `app_find_user_id_by_email`, which returns an id and only inside a workspace context) | `test_catalog.py::test_security_definer_functions_are_allowlisted` |
| 11 | The app reads or rewrites migration bookkeeping (`alembic_version`) | Catalog test | No grant; build fails if one appears | `test_catalog.py::test_migration_bookkeeping_is_not_app_accessible` |
| 12 | The audit log is edited, deleted or truncated to hide a change | Catalog test checks the triggers exist | `UPDATE`/`DELETE` not granted to `app_user` **and** triggers reject UPDATE, DELETE and TRUNCATE for every role, the owner included | `test_rls.py::test_audit_events_are_append_only`, `test_rls.py::test_audit_trigger_blocks_even_the_owner`, `test_catalog.py::test_audit_log_has_append_only_triggers` |

## API

| # | How it fails | How we detect it | What the system does instead | Test that proves it |
|---|--------------|------------------|------------------------------|---------------------|
| 13 | User of A calls a route with B's workspace id in the path | Membership check in the single `Access` dependency | 404 (not 403, so existence isn't revealed) | `test_cross_tenant.py::test_cross_tenant` (every route) |
| 14 | User of A calls a route in A with an id that belongs to B (e.g. a membership id) | — | RLS hides B's row → 404 | `test_cross_tenant.py::test_cross_tenant` (every route with an id) |
| 15 | A new route is added without a cross-tenant test, or outside `/v1` where the suite doesn't look | Suite enumerates every route (including lazily included routers) | Build fails | `test_cross_tenant.py::test_every_route_has_a_cross_tenant_case`, `::test_no_unexpected_routes_outside_v1`, `::test_route_enumeration_sees_included_routers` |
| 16 | Membership is checked at the app layer only; a bug there would let A set B's context | Cross-tenant suite on every route (#13, #15) | Known limit (ADR-0002): RLS scopes to the *current* workspace; membership is enforced in one dependency every tenant route uses | `test_cross_tenant.py`, `::test_outsider_sees_no_workspaces` |
| 17 | A non-manager manages members, or an admin grants/changes/removes an owner | Role checks in the service layer | 403 | `test_members.py::test_non_manager_cannot_manage`, `::test_admin_cannot_grant_or_touch_owner` |
| 18 | The last owner removes or demotes themselves, leaving a workspace nobody can manage | Service check | 409 Conflict | `test_members.py::test_cannot_remove_last_owner`, `::test_second_owner_allows_demotion` |
| 19 | Member changes leave no trace | — | Every add / role change / removal writes an audit event in the same transaction | `test_members.py::test_member_changes_are_audited` |

## Identity

| # | How it fails | How we detect it | What the system does instead | Test that proves it |
|---|--------------|------------------|------------------------------|---------------------|
| 20 | Missing, malformed, expired, not-yet-valid, wrong-issuer or wrongly signed token | Verifier checks signature (JWKS), `iss`, `exp`, `nbf`, required claims | 401 with `WWW-Authenticate: Bearer` | `test_members.py::test_unauthenticated_is_401`, `test_auth.py::test_clerk_rejects_bad_claims`, `::test_clerk_rejects_wrong_signature` |
| 21 | Algorithm downgrade (HS256 signed with the public key) | Only RS256 accepted | 401 | `test_auth.py::test_clerk_rejects_hs256_downgrade` |
| 22 | A token minted for a different Clerk app/origin is accepted because `CLERK_AUTHORIZED_PARTIES` is empty (the `azp` check switches off) | Settings validation at startup | App refuses to start with `AUTH_PROVIDER=clerk` outside local/test unless the list is non-empty; wrong or missing `azp` → 401 | `test_config.py::test_clerk_needs_authorized_parties_outside_local`, `test_auth.py::test_clerk_rejects_bad_claims` (azp cases) |
| 23 | Fake auth is enabled in a real environment (API or web) | Settings validation at startup | API refuses to start with `AUTH_PROVIDER=fake` unless `ENVIRONMENT` is local/test, so the web app's fake dev sign-in has nothing to talk to anywhere else; the web app shows a "development sign-in" banner in fake mode | `test_config.py::test_fake_auth_refused_outside_local` |

## Web shell

| # | How it fails | How we detect it | What the system does instead | Test that proves it |
|---|--------------|------------------|------------------------------|---------------------|
| 24 | The UI shows a control the user isn't allowed to use, or hides one they are | UI role rules mirror `roles.py` and are unit-tested against it | The UI is a convenience only; the API enforces every rule (#13–#19), and an error from the API is shown as-is | `web/src/lib/__tests__/roles.test.ts`; API tests above |
| 25 | User opens another workspace's URL | The workspace isn't in `/v1/me`, and every API call 404s | "Not found — it doesn't exist, or you're not a member of it"; nothing of B is fetched | API: `test_cross_tenant.py`; UI: manual Playwright smoke run (2026-11-25), not yet in CI |
| 26 | A stale or revoked session keeps working in the browser | Any 401 from the API | The client signs the user out and returns to sign-in | `web/src/lib/__tests__/api.test.ts` (401 → `onUnauthorized`) |

## Build and process

| # | How it fails | How we detect it | What the system does instead | Test that proves it |
|---|--------------|------------------|------------------------------|---------------------|
| 27 | CI loses its database config and the RLS suite **skips** instead of running, so the build goes green untested | `REQUIRE_DB_TESTS=1` in CI | pytest exits with a usage error instead of skipping | CI configuration; verified manually 2026-11-25 (exit code 4 without DB URLs) |
| 28 | A migration can't be rolled back (e.g. a dependency left behind) | CI runs upgrade → downgrade base → upgrade | Build fails | CI step "Migrations (upgrade, full downgrade, upgrade)" |

## Not covered yet (later milestones)
- Background jobs (Celery) setting context: M2, same helper, tested then.
- Jurisdiction-restricted policy editors: M2, application layer.
- Deleting a user in Clerk doesn't remove or disable our `users` row or their
  memberships (they just can't sign in). Needs the Clerk user-deletion
  webhook (verified with the endpoint's own webhook signing secret, a new
  env var when built): open item, see PROGRESS.md.
- Workspace and requester deletion (GDPR) vs. the append-only audit trigger: M6.
- Browser e2e (#25) in CI: add Playwright when the web app grows past the shell.
