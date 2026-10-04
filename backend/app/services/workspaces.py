"""Workspace authorization and explicit organisation/common/client boundaries."""

from __future__ import annotations

from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Kund, UserAccount
from app.database.workspaces import Workspace, WorkspaceMembership
from app.database.workspace_ids import company_workspace_id as company_workspace_id


async def require_workspace_customer(
    session: AsyncSession,
    user: UserAccount,
    customer_id: int | None = None,
) -> int:
    selected = customer_id if customer_id is not None else user.kund_id
    if selected is None:
        raise HTTPException(status_code=400, detail="customer_required")
    if user.role != "admin" and selected != user.kund_id:
        raise HTTPException(status_code=404, detail="customer_not_found")
    if await session.get(Kund, selected) is None:
        raise HTTPException(status_code=404, detail="customer_not_found")
    return selected


async def _workspace_actor(session: AsyncSession, *, customer_id: int, user_id: str) -> UserAccount:
    user = await session.get(UserAccount, user_id)
    if user is None or (user.role != "admin" and user.kund_id != customer_id):
        raise HTTPException(status_code=404, detail="workspace_not_found")
    if await session.get(Kund, customer_id) is None:
        raise HTTPException(status_code=404, detail="workspace_not_found")
    return user


async def ensure_company_workspace(session: AsyncSession, *, customer_id: int) -> Workspace:
    """Create the required default once; caller owns its transaction boundary."""
    statement = select(Workspace).where(
        Workspace.customer_id == customer_id, Workspace.kind == "company"
    )
    existing = (await session.execute(statement)).scalar_one_or_none()
    if existing is not None:
        return existing
    customer = await session.get(Kund, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="customer_not_found")
    insert = {"postgresql": pg_insert, "sqlite": sqlite_insert}[session.get_bind().dialect.name]
    await session.execute(
        insert(Workspace)
        .values(
            id=company_workspace_id(customer_id),
            customer_id=customer_id,
            name=customer.organization_name or customer.name,
            kind="company",
        )
        .on_conflict_do_nothing()
    )
    return (await session.execute(statement)).scalar_one()


async def resolve_workspace(
    session: AsyncSession,
    *,
    customer_id: int,
    user_id: str,
    workspace_id: str | None = None,
) -> Workspace:
    user = await _workspace_actor(session, customer_id=customer_id, user_id=user_id)
    if workspace_id is None:
        return await ensure_company_workspace(session, customer_id=customer_id)
    row = await session.get(Workspace, workspace_id)
    if row is None or row.customer_id != customer_id:
        raise HTTPException(status_code=404, detail="workspace_not_found")
    if row.kind == "company" or user.role == "admin":
        return row
    membership = await session.get(WorkspaceMembership, (workspace_id, user_id))
    if membership is None:
        raise HTTPException(status_code=404, detail="workspace_not_found")
    return row


async def resolve_readable_workspace_ids(
    session: AsyncSession,
    *,
    customer_id: int,
    user_id: str,
    workspace_id: str | None = None,
) -> list[str]:
    active = await resolve_workspace(
        session, customer_id=customer_id, user_id=user_id, workspace_id=workspace_id
    )
    common = await ensure_company_workspace(session, customer_id=customer_id)
    return list(dict.fromkeys((common.id, active.id)))


async def list_workspaces(
    session: AsyncSession, *, customer_id: int, user_id: str
) -> list[Workspace]:
    user = await _workspace_actor(session, customer_id=customer_id, user_id=user_id)
    await ensure_company_workspace(session, customer_id=customer_id)
    statement = select(Workspace).where(Workspace.customer_id == customer_id)
    if user.role != "admin":
        member_ids = select(WorkspaceMembership.workspace_id).where(
            WorkspaceMembership.user_id == user_id
        )
        statement = statement.where(or_(Workspace.kind == "company", Workspace.id.in_(member_ids)))
    result = await session.execute(statement.order_by(Workspace.kind, Workspace.name, Workspace.id))
    return list(result.scalars().all())


async def create_client_workspace(
    session: AsyncSession, *, customer_id: int, user_id: str, name: str
) -> Workspace:
    await _workspace_actor(session, customer_id=customer_id, user_id=user_id)
    await ensure_company_workspace(session, customer_id=customer_id)
    workspace = Workspace(
        id=str(uuid4()),
        customer_id=customer_id,
        name=name,
        kind="client",
        created_by_user_id=user_id,
    )
    session.add(workspace)
    await session.flush()
    session.add(WorkspaceMembership(workspace_id=workspace.id, user_id=user_id, role="manager"))
    await session.flush()
    return workspace


async def add_workspace_member(
    session: AsyncSession,
    *,
    customer_id: int,
    actor_user_id: str,
    workspace_id: str,
    member_user_id: str,
    role: str,
) -> WorkspaceMembership:
    workspace = await resolve_workspace(
        session, customer_id=customer_id, user_id=actor_user_id, workspace_id=workspace_id
    )
    actor = await _workspace_actor(session, customer_id=customer_id, user_id=actor_user_id)
    membership = await session.get(WorkspaceMembership, (workspace_id, actor_user_id))
    if workspace.kind != "client":
        raise HTTPException(
            status_code=400, detail="company_workspace_members_are_organisation_users"
        )
    if actor.role != "admin" and (membership is None or membership.role != "manager"):
        raise HTTPException(status_code=403, detail="workspace_manager_required")
    member = await session.get(UserAccount, member_user_id)
    if member is None or member.kund_id != customer_id:
        raise HTTPException(status_code=404, detail="workspace_member_not_found")
    result = await session.get(WorkspaceMembership, (workspace_id, member_user_id))
    if result is None:
        result = WorkspaceMembership(workspace_id=workspace_id, user_id=member_user_id, role=role)
        session.add(result)
    else:
        result.role = role
    await session.flush()
    return result
