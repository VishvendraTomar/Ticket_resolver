"""Tenancy tables. RLS policies live in the migration, not here (see ADR-0002)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, CreatedAt, UUIDPk
from app.tenancy.roles import Role


class Workspace(UUIDPk, CreatedAt, Base):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(200))


class User(UUIDPk, CreatedAt, Base):
    """A person, global across workspaces. Identity comes from the auth provider."""

    __tablename__ = "users"

    auth_subject: Mapped[str] = mapped_column(String(255), unique=True)
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    name: Mapped[str | None] = mapped_column(String(200))


class Membership(UUIDPk, CreatedAt, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="workspace_role", values_callable=lambda e: [m.value for m in e])
    )


class AuditEvent(UUIDPk, CreatedAt, Base):
    """Append-only: UPDATE/DELETE are revoked and blocked by a trigger."""

    __tablename__ = "audit_events"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100))
    target_type: Mapped[str] = mapped_column(String(50))
    target_id: Mapped[uuid.UUID | None]
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
