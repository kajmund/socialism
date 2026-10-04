"""Workspace selection and explicit sharing within an organisation."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database.models import UserAccount
from app.database.session import get_session
from app.schemas.workspaces import (
    WorkspaceCreate,
    WorkspaceMemberCreate,
    WorkspaceMemberOut,
    WorkspaceOut,
)
from app.services import workspaces

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceOut])
async def get_workspaces(
    customer_id: int | None = Query(default=None),
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[WorkspaceOut]:
    customer = await workspaces.require_workspace_customer(session, user, customer_id)
    rows = await workspaces.list_workspaces(session, customer_id=customer, user_id=user.id)
    result = [WorkspaceOut.model_validate(row) for row in rows]
    await session.commit()
    return result


@router.post("", response_model=WorkspaceOut, status_code=201)
async def create_workspace(
    body: WorkspaceCreate,
    customer_id: int | None = Query(default=None),
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> WorkspaceOut:
    customer = await workspaces.require_workspace_customer(session, user, customer_id)
    row = await workspaces.create_client_workspace(
        session, customer_id=customer, user_id=user.id, name=body.name
    )
    result = WorkspaceOut.model_validate(row)
    await session.commit()
    return result


@router.post("/{workspace_id}/members", response_model=WorkspaceMemberOut, status_code=201)
async def add_member(
    workspace_id: str,
    body: WorkspaceMemberCreate,
    *,
    customer_id: int | None = Query(default=None),
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> WorkspaceMemberOut:
    customer = await workspaces.require_workspace_customer(session, user, customer_id)
    row = await workspaces.add_workspace_member(
        session,
        customer_id=customer,
        actor_user_id=user.id,
        workspace_id=workspace_id,
        member_user_id=body.user_id,
        role=body.role,
    )
    result = WorkspaceMemberOut.model_validate(row)
    await session.commit()
    return result
