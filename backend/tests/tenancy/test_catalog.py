"""Catalog tests: the database itself must make cross-tenant access impossible.

These inspect pg_catalog, so a new table, grant or role mistake fails the build
even if no API route touches it yet.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.db

APP_ROLE = "app_user"

# Tables without a workspace_id column that app_user may still access, and why.
GLOBAL_TABLES = {
    "workspaces": "tenant root; policies key on id (FORCE'd like tenant tables)",
    "users": "people span workspaces; RLS on, not FORCE'd, so the SECURITY DEFINER "
    "email lookup (owner) can see all rows",
}
# Global tables that must still be FORCE'd.
GLOBAL_TABLES_FORCED = {"workspaces"}

# SECURITY DEFINER functions are RLS escape hatches; each must be listed and justified.
SECURITY_DEFINER_ALLOWLIST = {
    "app_find_user_id_by_email": "add-member-by-email; returns an id only, workspace context only",
}

TABLES_SQL = text("""
    SELECT c.relname AS name,
           c.relrowsecurity AS rls,
           c.relforcerowsecurity AS forced,
           EXISTS (SELECT 1 FROM pg_policies p
                   WHERE p.schemaname = 'public' AND p.tablename = c.relname) AS has_policy,
           EXISTS (SELECT 1 FROM information_schema.columns col
                   WHERE col.table_schema = 'public' AND col.table_name = c.relname
                     AND col.column_name = 'workspace_id') AS has_workspace_id,
           has_table_privilege(:role, c.oid, 'SELECT, INSERT, UPDATE, DELETE, TRUNCATE')
               AS app_access,
           pg_get_userbyid(c.relowner) AS owner
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
""")


async def _tables(owner_engine: AsyncEngine) -> list[dict[str, object]]:
    async with owner_engine.connect() as conn:
        rows = (await conn.execute(TABLES_SQL, {"role": APP_ROLE})).mappings().all()
    return [dict(r) for r in rows]


async def test_every_tenant_table_has_forced_rls_and_policy(owner_engine: AsyncEngine) -> None:
    tables = [t for t in await _tables(owner_engine) if t["has_workspace_id"]]
    assert tables, "expected at least one tenant table"
    problems = [
        f"{t['name']}: rls={t['rls']} force={t['forced']} policy={t['has_policy']}"
        for t in tables
        if not (t["rls"] and t["forced"] and t["has_policy"])
    ]
    assert not problems, "Tenant tables without ENABLE+FORCE RLS and a policy:\n" + "\n".join(
        problems
    )


async def test_app_accessible_tables_are_protected(owner_engine: AsyncEngine) -> None:
    problems: list[str] = []
    for t in await _tables(owner_engine):
        name = str(t["name"])
        if not t["app_access"]:
            continue
        if not (t["rls"] and t["has_policy"]):
            problems.append(f"{name}: app_user can access it but RLS/policy is missing")
        if not t["has_workspace_id"]:
            if name not in GLOBAL_TABLES:
                problems.append(
                    f"{name}: no workspace_id and not in GLOBAL_TABLES (justify or add the column)"
                )
            elif name in GLOBAL_TABLES_FORCED and not t["forced"]:
                problems.append(f"{name}: must be FORCE ROW LEVEL SECURITY")
    assert not problems, "\n".join(problems)


async def test_migration_bookkeeping_is_not_app_accessible(owner_engine: AsyncEngine) -> None:
    tables = {t["name"]: t for t in await _tables(owner_engine)}
    assert "alembic_version" in tables
    assert not tables["alembic_version"]["app_access"]


async def test_app_role_owns_no_tables(owner_engine: AsyncEngine) -> None:
    """Table owners bypass non-FORCE'd RLS, so the app role must own nothing."""
    owned = [t["name"] for t in await _tables(owner_engine) if t["owner"] == APP_ROLE]
    assert owned == []


async def test_app_role_cannot_bypass_rls(app_engine: AsyncEngine) -> None:
    async with app_engine.connect() as conn:
        me = (
            (
                await conn.execute(
                    text("""
                    SELECT current_user AS name, r.rolbypassrls, r.rolsuper
                    FROM pg_roles r WHERE r.rolname = current_user
                """)
                )
            )
            .mappings()
            .one()
        )
        bypass_memberships = (
            (
                await conn.execute(
                    text("""
                    SELECT r.rolname FROM pg_roles r
                    WHERE (r.rolbypassrls OR r.rolsuper)
                      AND r.rolname <> current_user
                      AND pg_has_role(current_user, r.oid, 'MEMBER')
                """)
                )
            )
            .scalars()
            .all()
        )

    assert me["name"] == APP_ROLE, "the app must connect as app_user"
    assert me["rolbypassrls"] is False, "app_user has BYPASSRLS — RLS would be ignored"
    assert me["rolsuper"] is False, "app_user is a superuser — RLS would be ignored"
    assert bypass_memberships == [], (
        f"app_user can assume roles that bypass RLS: {bypass_memberships} "
        "(was it created in the Neon dashboard? It must be created by the migration.)"
    )


async def test_security_definer_functions_are_allowlisted(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        rows = (
            await conn.execute(
                text("""
                    SELECT p.proname, p.proconfig
                    FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                    WHERE n.nspname = 'public' AND p.prosecdef
                """)
            )
        ).all()
    found = {name: config or [] for name, config in rows}
    assert set(found) <= set(SECURITY_DEFINER_ALLOWLIST), (
        f"Unlisted SECURITY DEFINER functions: {set(found) - set(SECURITY_DEFINER_ALLOWLIST)}"
    )
    for name, config in found.items():
        assert any(c.startswith("search_path=") for c in config), f"{name}: pin search_path"


async def test_audit_log_has_append_only_triggers(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        triggers = set(
            (
                await conn.execute(
                    text("""
                        SELECT tgname FROM pg_trigger
                        WHERE tgrelid = 'public.audit_events'::regclass AND NOT tgisinternal
                    """)
                )
            ).scalars()
        )
    assert {"audit_events_no_update_delete", "audit_events_no_truncate"} <= triggers
