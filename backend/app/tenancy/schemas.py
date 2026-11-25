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
    created_at: datetime


class MemberAdd(BaseModel):
    email: EmailStr
    role: Role


class MemberUpdate(BaseModel):
    role: Role
