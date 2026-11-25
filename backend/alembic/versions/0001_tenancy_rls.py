"""Tenancy tables, app_user role and Row-Level Security.

Revision ID: 0001_tenancy_rls
Revises:
Create Date: 2026-11-25

Design (ADR-0002):
- The app connects as ``app_user``: LOGIN, NOSUPERUSER, NOBYPASSRLS, created here
  in SQL (never in the Neon dashboard, whose roles inherit BYPASSRLS via
  neon_superuser). Its password is taken from APP_DATABASE_URL.
- Tables get explicit grants only. A new table is invisible to app_user until a
  migration grants it, and the catalog test then demands RLS on it.
- Tenant tables: ENABLE + FORCE RLS, policies keyed on app_current_workspace_id().
- ``users`` is global (one person, many workspaces): RLS enabled with policies,
  but not FORCE, so the owner-defined lookup function below can see all rows.
"""

import re
from collections.abc import Sequence
from urllib.parse import unquote, urlsplit

import sqlalchemy as sa
from alembic import op

from app.core.config import get_settings

revision: str = "0001_tenancy_rls"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"


def _run_all(sql: str) -> None:
    """Run a script one statement at a time (asyncpg prepares each statement).

    Statements are separated by ``;`` at end of line. Dollar-quoted bodies in
    this file keep their ``;`` mid-line, so they are never split.
    """
    for statement in re.split(r";[ \t]*\n", sql):
        if statement.strip():
            if statement.count("$$") % 2:
                raise RuntimeError(f"Split inside a $$ body; keep ';' mid-line:\n{statement}")
            op.execute(statement)


def _app_role_password() -> str:
    raw = get_settings().app_database_url
    if raw is None:
        raise RuntimeError("APP_DATABASE_URL is required: the migration creates its role")
    parts = urlsplit(raw.get_secret_value())
    if parts.username != APP_ROLE:
        raise RuntimeError(f"APP_DATABASE_URL must connect as {APP_ROLE!r}, not {parts.username!r}")
    if not parts.password:
        raise RuntimeError("APP_DATABASE_URL must include a password")
    return unquote(parts.password)


def upgrade() -> None:
    # --- Role -----------------------------------------------------------------
    # The password travels as a bind parameter into a transaction-local setting,
    # then format(%L) quotes it. It never appears in SQL text or in this file.
    op.execute(
        sa.text("SELECT set_config('migration.app_password', :pw, true)").bindparams(
            pw=_app_role_password()
        )
    )
    op.execute(f"""
        DO $$
        DECLARE attrs text := 'LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT';
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                EXECUTE format('CREATE ROLE {APP_ROLE} %s PASSWORD %L',
                               attrs, current_setting('migration.app_password'));
            ELSE
                EXECUTE format('ALTER ROLE {APP_ROLE} %s PASSWORD %L',
                               attrs, current_setting('migration.app_password'));
            END IF;
        END $$;
    """)
    op.execute("SELECT set_config('migration.app_password', '', true)")
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")

    # --- Context helpers --------------------------------------------------------
    # STABLE SQL functions so the planner can inline them into policies.
    # Missing or empty settings read as NULL, so every comparison fails closed.
    _run_all("""
        CREATE FUNCTION app_current_workspace_id() RETURNS uuid
        LANGUAGE sql STABLE AS
        $$ SELECT nullif(current_setting('app.workspace_id', true), '')::uuid $$;

        CREATE FUNCTION app_current_user_id() RETURNS uuid
        LANGUAGE sql STABLE AS
        $$ SELECT nullif(current_setting('app.user_id', true), '')::uuid $$;

        CREATE FUNCTION app_current_auth_subject() RETURNS text
        LANGUAGE sql STABLE AS
        $$ SELECT nullif(current_setting('app.auth_subject', true), '') $$;
    """)

    # --- Tables -------------------------------------------------------------------
    _run_all("""
        CREATE TYPE workspace_role AS ENUM
            ('owner', 'admin', 'policy_editor', 'agent', 'viewer', 'integrator');

        CREATE TABLE workspaces (
            id          uuid PRIMARY KEY,
            name        varchar(200) NOT NULL,
            created_at  timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE users (
            id            uuid PRIMARY KEY,
            auth_subject  varchar(255) NOT NULL,
            email         varchar(320),
            name          varchar(200),
            created_at    timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_users_auth_subject UNIQUE (auth_subject),
            CONSTRAINT uq_users_email UNIQUE (email),
            CONSTRAINT ck_users_email_lowercase CHECK (email = lower(email))
        );

        CREATE TABLE memberships (
            id            uuid PRIMARY KEY,
            workspace_id  uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            user_id       uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role          workspace_role NOT NULL,
            created_at    timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_memberships_workspace_id UNIQUE (workspace_id, user_id)
        );
        CREATE INDEX ix_memberships_user_id ON memberships (user_id);

        CREATE TABLE audit_events (
            id             uuid PRIMARY KEY,
            workspace_id   uuid NOT NULL REFERENCES workspaces(id),
            actor_user_id  uuid REFERENCES users(id),
            action         varchar(100) NOT NULL,
            target_type    varchar(50) NOT NULL,
            target_id      uuid,
            data           jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at     timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_audit_events_workspace_created
            ON audit_events (workspace_id, created_at);
    """)

    # --- Append-only audit log --------------------------------------------------------
    _run_all("""
        CREATE FUNCTION audit_events_reject_change() RETURNS trigger
        LANGUAGE plpgsql AS
        $$ BEGIN
            RAISE EXCEPTION 'audit_events is append-only (% rejected)', TG_OP
                USING ERRCODE = 'insufficient_privilege'; END $$;

        CREATE TRIGGER audit_events_no_update_delete
            BEFORE UPDATE OR DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION audit_events_reject_change();
        CREATE TRIGGER audit_events_no_truncate
            BEFORE TRUNCATE ON audit_events
            FOR EACH STATEMENT EXECUTE FUNCTION audit_events_reject_change();
    """)

    # --- Row-Level Security ----------------------------------------------------------
    # Two contexts:
    #   * account context  (app.workspace_id unset): a user sees their own
    #     memberships and the workspaces they belong to — for /v1/me and for the
    #     membership check that precedes entering a workspace.
    #   * workspace context (app.workspace_id set): everything is scoped to it;
    #     the user's memberships in *other* workspaces are not visible.
    _run_all("""
        ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;
        ALTER TABLE workspaces FORCE ROW LEVEL SECURITY;
        CREATE POLICY workspaces_select ON workspaces FOR SELECT USING (
            id = app_current_workspace_id()
            OR (app_current_workspace_id() IS NULL
                AND id IN (SELECT m.workspace_id FROM memberships m
                           WHERE m.user_id = app_current_user_id()))
        );
        CREATE POLICY workspaces_insert ON workspaces FOR INSERT
            WITH CHECK (id = app_current_workspace_id());
        CREATE POLICY workspaces_update ON workspaces FOR UPDATE
            USING (id = app_current_workspace_id())
            WITH CHECK (id = app_current_workspace_id());

        ALTER TABLE memberships ENABLE ROW LEVEL SECURITY;
        ALTER TABLE memberships FORCE ROW LEVEL SECURITY;
        CREATE POLICY memberships_select ON memberships FOR SELECT USING (
            workspace_id = app_current_workspace_id()
            OR (app_current_workspace_id() IS NULL AND user_id = app_current_user_id())
        );
        CREATE POLICY memberships_insert ON memberships FOR INSERT
            WITH CHECK (workspace_id = app_current_workspace_id());
        CREATE POLICY memberships_update ON memberships FOR UPDATE
            USING (workspace_id = app_current_workspace_id())
            WITH CHECK (workspace_id = app_current_workspace_id());
        CREATE POLICY memberships_delete ON memberships FOR DELETE
            USING (workspace_id = app_current_workspace_id());

        ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
        ALTER TABLE audit_events FORCE ROW LEVEL SECURITY;
        CREATE POLICY audit_events_select ON audit_events FOR SELECT
            USING (workspace_id = app_current_workspace_id());
        CREATE POLICY audit_events_insert ON audit_events FOR INSERT
            WITH CHECK (workspace_id = app_current_workspace_id());

        -- Global table: a user sees themselves, and the members of the current workspace.
        ALTER TABLE users ENABLE ROW LEVEL SECURITY;
        CREATE POLICY users_select ON users FOR SELECT USING (
            auth_subject = app_current_auth_subject()
            OR id = app_current_user_id()
            OR id IN (SELECT m.user_id FROM memberships m
                      WHERE m.workspace_id = app_current_workspace_id())
        );
        CREATE POLICY users_insert ON users FOR INSERT
            WITH CHECK (auth_subject = app_current_auth_subject());
        CREATE POLICY users_update ON users FOR UPDATE
            USING (auth_subject = app_current_auth_subject())
            WITH CHECK (auth_subject = app_current_auth_subject());
    """)

    # --- Lookup for "add member by email" ---------------------------------------------
    # Runs as the owner (users is not FORCE'd), returns only an id, and only inside
    # a workspace context. Membership managers are checked by the API before calling.
    _run_all("""
        CREATE FUNCTION app_find_user_id_by_email(p_email text) RETURNS uuid
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public AS
        $$ SELECT u.id FROM public.users u
           WHERE app_current_workspace_id() IS NOT NULL AND u.email = lower(p_email) $$;
        REVOKE ALL ON FUNCTION app_find_user_id_by_email(text) FROM PUBLIC;
    """)

    # --- Grants (explicit, per table) -------------------------------------------------
    _run_all(f"""
        GRANT SELECT, INSERT, UPDATE ON workspaces TO {APP_ROLE};
        GRANT SELECT, INSERT, UPDATE ON users TO {APP_ROLE};
        GRANT SELECT, INSERT, UPDATE, DELETE ON memberships TO {APP_ROLE};
        GRANT SELECT, INSERT ON audit_events TO {APP_ROLE};
        GRANT EXECUTE ON FUNCTION app_find_user_id_by_email(text) TO {APP_ROLE};
        REVOKE ALL ON alembic_version FROM {APP_ROLE};
    """)


def downgrade() -> None:
    _run_all(f"""
        DROP FUNCTION IF EXISTS app_find_user_id_by_email(text);
        -- These policies reference memberships, so they must go before it.
        DROP POLICY IF EXISTS workspaces_select ON workspaces;
        DROP POLICY IF EXISTS users_select ON users;
        DROP TABLE IF EXISTS audit_events;
        DROP FUNCTION IF EXISTS audit_events_reject_change();
        DROP TABLE IF EXISTS memberships;
        DROP TABLE IF EXISTS users;
        DROP TABLE IF EXISTS workspaces;
        DROP TYPE IF EXISTS workspace_role;
        DROP FUNCTION IF EXISTS app_current_workspace_id();
        DROP FUNCTION IF EXISTS app_current_user_id();
        DROP FUNCTION IF EXISTS app_current_auth_subject();
        REVOKE USAGE ON SCHEMA public FROM {APP_ROLE};
        DROP ROLE IF EXISTS {APP_ROLE};
    """)
