"""Routes: /v1/me, workspaces, members."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.tenancy import service
from app.tenancy.deps import Access, CurrentUser, SessionDep
from app.tenancy.models import Membership, User
from app.tenancy.schemas import (
    MemberAdd,
    MemberOut,
    MemberUpdate,
    MeOut,
    MyWorkspace,
    UserOut,
    WorkspaceCreate,
    WorkspaceOut,
)

router = APIRouter()


def _member_out(membership: Membership, user: User) -> MemberOut:
    return MemberOut(
        id=membership.id,
        user=UserOut.model_validate(user),
        role=membership.role,
        jurisdiction_codes=membership.jurisdiction_codes,
        created_at=membership.created_at,
    )


@router.get("/me", response_model=MeOut, tags=["account"])
async def get_me(session: SessionDep, user: CurrentUser) -> MeOut:
    workspaces = await service.list_my_workspaces(session, user)
    await session.commit()  # persists a first-sign-in user row
    return MeOut(
        user=UserOut.model_validate(user),
        workspaces=[MyWorkspace(id=ws.id, name=ws.name, role=role) for ws, role in workspaces],
    )


@router.post(
    "/workspaces",
    response_model=WorkspaceOut,
    status_code=status.HTTP_201_CREATED,
    tags=["workspaces"],
)
async def create_workspace(
    body: WorkspaceCreate, session: SessionDep, user: CurrentUser
) -> WorkspaceOut:
    workspace = await service.create_workspace(session, user, body.name)
    out = WorkspaceOut.model_validate(workspace)
    await session.commit()
    return out


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceOut, tags=["workspaces"])
async def get_workspace(session: SessionDep, access: Access) -> WorkspaceOut:
    return WorkspaceOut.model_validate(await service.get_workspace(session, access))


@router.get("/workspaces/{workspace_id}/members", response_model=list[MemberOut], tags=["members"])
async def list_members(session: SessionDep, access: Access) -> list[MemberOut]:
    return [_member_out(m, u) for m, u in await service.list_members(session, access)]


@router.post(
    "/workspaces/{workspace_id}/members",
    response_model=MemberOut,
    status_code=status.HTTP_201_CREATED,
    tags=["members"],
)
async def add_member(body: MemberAdd, session: SessionDep, access: Access) -> MemberOut:
    membership, user = await service.add_member(session, access, body.email, body.role)
    out = _member_out(membership, user)
    await session.commit()
    return out


@router.patch(
    "/workspaces/{workspace_id}/members/{membership_id}",
    response_model=MemberOut,
    tags=["members"],
)
async def change_member_role(
    membership_id: uuid.UUID, body: MemberUpdate, session: SessionDep, access: Access
) -> MemberOut:
    membership, user = await service.update_member(
        session,
        access,
        membership_id,
        role=body.role,
        jurisdiction_codes=body.jurisdiction_codes,
        set_jurisdictions="jurisdiction_codes" in body.model_fields_set,
    )
    out = _member_out(membership, user)
    await session.commit()
    return out


@router.delete(
    "/workspaces/{workspace_id}/members/{membership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["members"],
)
async def remove_member(membership_id: uuid.UUID, session: SessionDep, access: Access) -> None:
    await service.remove_member(session, access, membership_id)
    await session.commit()
