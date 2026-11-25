"""Workspace roles (SPEC §2) and what each may do in M1."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    POLICY_EDITOR = "policy_editor"
    AGENT = "agent"
    VIEWER = "viewer"
    INTEGRATOR = "integrator"


MEMBER_MANAGERS = frozenset({Role.OWNER, Role.ADMIN})


def can_manage_members(role: Role) -> bool:
    return role in MEMBER_MANAGERS


def can_assign_role(actor: Role, target_role: Role) -> bool:
    """Admins manage everyone except owners; only owners create or change owners."""
    if actor is Role.OWNER:
        return True
    if actor is Role.ADMIN:
        return target_role is not Role.OWNER
    return False
