"""Tenancy use cases. Callers own the transaction; functions here never commit.

Every query runs under RLS as app_user, so these functions rely on the
context set by ``tenancy.deps`` rather than on their own WHERE clauses for
isolation (they still filter explicitly — belt and braces).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import set_context
from app.core.errors import Conflict, Forbidden, NotFound
from app.knowledge.defaults import DEFAULT_TOPICS
from app.knowledge.models import Jurisdiction, Topic
from app.providers.auth.base import Principal
from app.tenancy.models import AuditEvent, Membership, User, Workspace
from app.tenancy.roles import Role, can_assign_role, can_manage_members


@dataclass(frozen=True)
class WorkspaceAccess:
    """The caller, acting inside one workspace with one role."""

    user: User
    workspace_id: uuid.UUID
    role: Role
    # Policy editors may be limited to these jurisdictions (and descendants); None = all.
    jurisdiction_codes: list[str] | None = None


# --- Users ---------------------------------------------------------------------------


async def resolve_user(session: AsyncSession, principal: Principal) -> User:
    """Find (or on first sign-in, create) the caller's user row and set the user context."""
    await set_context(session, auth_subject=principal.subject)
    email = principal.email.lower() if principal.email else None

    user = await session.scalar(select(User).where(User.auth_subject == principal.subject))
    if user is None:
        user = User(
            id=uuid.uuid4(), auth_subject=principal.subject, email=email, name=principal.name
        )
        session.add(user)
        try:
            await session.flush()
        except IntegrityError as exc:
            raise Conflict("Another account already uses this email address") from exc
    elif (user.email, user.name) != (email, principal.name):
        user.email, user.name = email, principal.name
        await session.flush()

    await set_context(session, user_id=user.id)
    return user


# --- Workspaces ----------------------------------------------------------------------


async def list_my_workspaces(session: AsyncSession, user: User) -> list[tuple[Workspace, Role]]:
    """Account context only (no workspace set): RLS shows just the caller's memberships."""
    rows = await session.execute(
        select(Workspace, Membership.role)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .where(Membership.user_id == user.id)
        .order_by(Workspace.created_at)
    )
    return [(ws, role) for ws, role in rows]


async def create_workspace(session: AsyncSession, user: User, name: str) -> Workspace:
    workspace = Workspace(id=uuid.uuid4(), name=name)
    await set_context(session, workspace_id=workspace.id)
    session.add(workspace)
    await session.flush()
    membership = Membership(
        id=uuid.uuid4(), workspace_id=workspace.id, user_id=user.id, role=Role.OWNER
    )
    session.add(membership)
    session.add_all(
        Topic(id=uuid.uuid4(), workspace_id=workspace.id, key=key, name=name)
        for key, name in DEFAULT_TOPICS
    )
    await session.flush()
    await record_audit(
        session,
        workspace.id,
        user.id,
        "workspace.created",
        "workspace",
        workspace.id,
        {"name": name},
    )
    return workspace


async def enter_workspace(
    session: AsyncSession, user: User, workspace_id: uuid.UUID
) -> WorkspaceAccess:
    """Check membership in account context, then switch the transaction into the workspace.

    Not a member and "doesn't exist" both give 404, so ids can't be probed.
    """
    row = (
        await session.execute(
            select(Membership.role, Membership.jurisdiction_codes).where(
                Membership.workspace_id == workspace_id, Membership.user_id == user.id
            )
        )
    ).first()
    if row is None:
        raise NotFound("Workspace not found")
    role, codes = row
    await set_context(session, workspace_id=workspace_id)
    return WorkspaceAccess(
        user=user, workspace_id=workspace_id, role=role, jurisdiction_codes=codes
    )


async def get_workspace(session: AsyncSession, access: WorkspaceAccess) -> Workspace:
    workspace = await session.get(Workspace, access.workspace_id)
    if workspace is None:  # pragma: no cover - membership implies existence
        raise NotFound("Workspace not found")
    return workspace


# --- Members -------------------------------------------------------------------------


async def list_members(
    session: AsyncSession, access: WorkspaceAccess
) -> list[tuple[Membership, User]]:
    rows = await session.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.workspace_id == access.workspace_id)
        .order_by(Membership.created_at)
    )
    return [(m, u) for m, u in rows]


async def add_member(
    session: AsyncSession, access: WorkspaceAccess, email: str, role: Role
) -> tuple[Membership, User]:
    _require_manager(access)
    if not can_assign_role(access.role, role):
        raise Forbidden(f"A {access.role} cannot grant the {role} role")

    user_id = await session.scalar(
        text("SELECT app_find_user_id_by_email(:email)"), {"email": email}
    )
    if user_id is None:
        # Invitations for people who haven't signed in yet come later (M6).
        raise NotFound("No user with that email has signed in yet")

    membership = Membership(
        id=uuid.uuid4(), workspace_id=access.workspace_id, user_id=user_id, role=role
    )
    session.add(membership)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise Conflict("That user is already a member of this workspace") from exc

    user = await session.get_one(User, user_id)
    await record_audit(
        session,
        access.workspace_id,
        access.user.id,
        "member.added",
        "membership",
        membership.id,
        {"user_id": str(user_id), "role": role},
    )
    return membership, user


async def update_member(
    session: AsyncSession,
    access: WorkspaceAccess,
    membership_id: uuid.UUID,
    *,
    role: Role | None = None,
    jurisdiction_codes: list[str] | None = None,
    set_jurisdictions: bool = False,
) -> tuple[Membership, User]:
    """Change a member's role and/or jurisdiction restrictions (None clears them)."""
    _require_manager(access)
    membership = await _get_membership_for_update(session, access, membership_id)
    if not can_assign_role(access.role, membership.role):
        raise Forbidden("Only owners can change owners or grant the owner role")

    if role is not None and role is not membership.role:
        if not can_assign_role(access.role, role):
            raise Forbidden("Only owners can change owners or grant the owner role")
        if membership.role is Role.OWNER:
            await _ensure_not_last_owner(session, access)
        previous = membership.role
        membership.role = role
        await session.flush()
        await record_audit(
            session,
            access.workspace_id,
            access.user.id,
            "member.role_changed",
            "membership",
            membership.id,
            {"from": previous, "to": role},
        )

    if set_jurisdictions:
        codes = sorted(set(jurisdiction_codes)) if jurisdiction_codes else None
        if codes:
            known = set(
                (
                    await session.scalars(
                        select(Jurisdiction.code).where(Jurisdiction.code.in_(codes))
                    )
                ).all()
            )
            unknown = [c for c in codes if c not in known]
            if unknown:
                raise Conflict(f"Unknown jurisdiction codes: {', '.join(unknown)}")
        previous_codes = membership.jurisdiction_codes
        membership.jurisdiction_codes = codes
        await session.flush()
        await record_audit(
            session,
            access.workspace_id,
            access.user.id,
            "member.jurisdictions_changed",
            "membership",
            membership.id,
            {"from": previous_codes, "to": codes},
        )

    user = await session.get_one(User, membership.user_id)
    return membership, user


async def remove_member(
    session: AsyncSession, access: WorkspaceAccess, membership_id: uuid.UUID
) -> None:
    _require_manager(access)
    membership = await _get_membership_for_update(session, access, membership_id)
    if not can_assign_role(access.role, membership.role):
        raise Forbidden("Only owners can remove owners")
    if membership.role is Role.OWNER:
        await _ensure_not_last_owner(session, access)

    await session.delete(membership)
    await session.flush()
    await record_audit(
        session,
        access.workspace_id,
        access.user.id,
        "member.removed",
        "membership",
        membership.id,
        {"user_id": str(membership.user_id)},
    )


# --- Audit ---------------------------------------------------------------------------


async def record_audit(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    action: str,
    target_type: str,
    target_id: uuid.UUID | None,
    data: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            data={k: str(v) for k, v in (data or {}).items()},
        )
    )
    await session.flush()


# --- Helpers -------------------------------------------------------------------------


def _require_manager(access: WorkspaceAccess) -> None:
    if not can_manage_members(access.role):
        raise Forbidden("Only owners and admins can manage members")


async def _get_membership_for_update(
    session: AsyncSession, access: WorkspaceAccess, membership_id: uuid.UUID
) -> Membership:
    membership = await session.scalar(
        select(Membership)
        .where(Membership.id == membership_id, Membership.workspace_id == access.workspace_id)
        .with_for_update()
    )
    if membership is None:
        raise NotFound("Member not found")
    return membership


async def _ensure_not_last_owner(session: AsyncSession, access: WorkspaceAccess) -> None:
    # Lock every owner row so two concurrent demotions can't both see "2 owners".
    owner_ids = (
        await session.scalars(
            select(Membership.id)
            .where(Membership.workspace_id == access.workspace_id, Membership.role == Role.OWNER)
            .with_for_update()
        )
    ).all()
    if len(owner_ids) <= 1:
        raise Conflict("A workspace must keep at least one owner")
