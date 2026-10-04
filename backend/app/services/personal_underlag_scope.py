"""The personal file API is confined to its selected workspace as well as owner."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.scope import customer_id_for_user
from app.database.models import StoredObject, UserAccount
from app.database.workspaces import Workspace
from app.services.object_storage import KIND_UNDERLAG
from app.services.workspaces import resolve_workspace


def own_underlag(row: StoredObject | None, *, customer_id: int, user_id: str) -> StoredObject:
    if (
        row is None
        or row.kind != KIND_UNDERLAG
        or row.customer_id != customer_id
        or row.owner_user_id != user_id
    ):
        raise HTTPException(status_code=404, detail="File not found")
    return row


async def personal_workspace(
    session: AsyncSession, user: UserAccount, workspace_id: str | None
) -> Workspace:
    user_id = user.id
    customer_id = await customer_id_for_user(session, user)
    return await resolve_workspace(
        session, customer_id=customer_id, user_id=user_id, workspace_id=workspace_id
    )


def require_company_folders(workspace: Workspace) -> None:
    if workspace.kind != "company":
        raise HTTPException(status_code=400, detail="folders_require_company_workspace")


async def personal_underlag(
    session: AsyncSession,
    user: UserAccount,
    object_id: str,
    workspace_id: str | None,
) -> StoredObject:
    user_id = user.id
    workspace = await personal_workspace(session, user, workspace_id)
    row = own_underlag(
        await session.get(StoredObject, object_id),
        customer_id=workspace.customer_id,
        user_id=user_id,
    )
    if row.workspace_id != workspace.id:
        raise HTTPException(status_code=404, detail="File not found")
    return row


async def list_personal_underlag(
    session: AsyncSession,
    *,
    workspace: Workspace,
    user_id: str,
    module: str | None,
    folder_id: str | None,
) -> list[StoredObject]:
    statement = select(StoredObject).where(
        StoredObject.customer_id == workspace.customer_id,
        StoredObject.workspace_id == workspace.id,
        StoredObject.owner_user_id == user_id,
        StoredObject.kind == KIND_UNDERLAG,
    )
    if module is not None:
        statement = statement.where(
            StoredObject.module == module, StoredObject.folder_id == folder_id
        )
    return list(
        (await session.execute(statement.order_by(StoredObject.created_at.desc()))).scalars()
    )


async def detach_underlag(session: AsyncSession, row: StoredObject) -> StoredObject:
    session.expunge(row)
    await session.rollback()
    return row
