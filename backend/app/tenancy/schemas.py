"""API schemas for tenancy."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.tenancy.roles import Role


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str | None
    name: str | None


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_at: datetime


class MyWorkspace(BaseModel):
    id: uuid.UUID
    name: str
    role: Role


class MeOut(BaseModel):
    user: UserOut
    workspaces: list[MyWorkspace]


class MemberOut(BaseModel):
    id: uuid.UUID  # membership id
    user: UserOut
    role: Role
    # Policy editors may be limited to these jurisdictions; null = unrestricted.
    jurisdiction_codes: list[str] | None = None
    created_at: datetime


class MemberAdd(BaseModel):
    email: EmailStr
    role: Role


class MemberUpdate(BaseModel):
    """Send `role`, `jurisdiction_codes`, or both. `jurisdiction_codes: null` clears them."""

    role: Role | None = None
    jurisdiction_codes: list[str] | None = Field(default=None, max_length=50)
