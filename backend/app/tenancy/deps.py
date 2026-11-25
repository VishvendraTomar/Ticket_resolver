"""Request dependencies: who is calling, and in which workspace.

Order inside one transaction:
1. verify the bearer token          -> Principal
2. resolve_user                     -> sets app.auth_subject, app.user_id
3. enter_workspace (tenant routes)  -> membership check, then sets app.workspace_id

Every tenant route takes ``Access``; that is the single place membership is
enforced at the app layer (RLS enforces the workspace boundary underneath).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Path
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import Unauthenticated
from app.providers.auth import get_auth_verifier
from app.providers.auth.base import AuthVerifier, InvalidToken, Principal
from app.tenancy import service
from app.tenancy.models import User
from app.tenancy.service import WorkspaceAccess

_bearer = HTTPBearer(auto_error=False)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    verifier: Annotated[AuthVerifier, Depends(get_auth_verifier)],
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise Unauthenticated("Missing bearer token")
    try:
        return await verifier.verify(credentials.credentials)
    except InvalidToken as exc:
        raise Unauthenticated("Invalid or expired token") from exc


async def get_current_user(
    session: SessionDep, principal: Annotated[Principal, Depends(get_principal)]
) -> User:
    return await service.resolve_user(session, principal)


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_workspace_access(
    workspace_id: Annotated[uuid.UUID, Path()],
    session: SessionDep,
    user: CurrentUser,
) -> WorkspaceAccess:
    return await service.enter_workspace(session, user, workspace_id)


Access = Annotated[WorkspaceAccess, Depends(get_workspace_access)]
