"""Chats retain their workspace; all subsequent operations use this binding."""

from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Persona, StoredObject, UserAccount
from app.database.workspaces import WorkspaceChat, WorkspaceChatMessage
from app.schemas.workspace_chat import (
    WorkspaceChatCreate,
    WorkspaceChatMessageOut,
    WorkspaceChatOut,
)
from app.services.workspaces import (
    require_workspace_customer,
    resolve_readable_workspace_ids,
    resolve_workspace,
)


async def require_chat(
    session: AsyncSession,
    user: UserAccount,
    chat_id: str,
    customer_id: int | None = None,
) -> WorkspaceChat:
    customer = await require_workspace_customer(session, user, customer_id)
    chat = await session.get(WorkspaceChat, chat_id)
    if chat is None or chat.customer_id != customer or chat.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="chat_not_found")
    await resolve_workspace(
        session, customer_id=customer, user_id=user.id, workspace_id=chat.workspace_id
    )
    return chat


async def create_chat(
    session: AsyncSession,
    user: UserAccount,
    body: WorkspaceChatCreate,
    customer_id: int | None = None,
) -> WorkspaceChat:
    customer = await require_workspace_customer(session, user, customer_id)
    workspace = await resolve_workspace(
        session,
        customer_id=customer,
        user_id=user.id,
        workspace_id=body.workspace_id,
    )
    if body.persona_id is not None:
        persona = await session.get(Persona, body.persona_id)
        if persona is None or persona.customer_id != customer or persona.kind != "expert":
            raise HTTPException(status_code=404, detail="expert_not_found")
    chat = WorkspaceChat(
        id=str(uuid4()),
        customer_id=customer,
        workspace_id=workspace.id,
        owner_user_id=user.id,
        persona_id=body.persona_id,
        module="dd",
        title=body.title.strip(),
    )
    session.add(chat)
    await session.flush()
    return chat


async def serialize_chat(session: AsyncSession, chat: WorkspaceChat) -> WorkspaceChatOut:
    rows = list(
        await session.scalars(
            select(WorkspaceChatMessage)
            .where(
                WorkspaceChatMessage.chat_id == chat.id,
                WorkspaceChatMessage.role.in_(("user", "assistant")),
            )
            .order_by(WorkspaceChatMessage.id)
        )
    )
    return WorkspaceChatOut(
        id=chat.id,
        customer_id=chat.customer_id,
        workspace_id=chat.workspace_id,
        persona_id=chat.persona_id,
        module=chat.module,
        title=chat.title,
        messages=[
            WorkspaceChatMessageOut(
                id=row.id,
                role=row.role,
                content=row.content,
                attachment_object_id=row.attachment_object_id,
                job_id=row.job_id,
                created_at=row.created_at.isoformat(),
            )
            for row in rows
        ],
    )


async def list_chat_files(
    session: AsyncSession,
    user: UserAccount,
    chat: WorkspaceChat,
) -> list[StoredObject]:
    workspaces = await resolve_readable_workspace_ids(
        session,
        customer_id=chat.customer_id,
        user_id=user.id,
        workspace_id=chat.workspace_id,
    )
    return list(
        await session.scalars(
            select(StoredObject)
            .where(
                StoredObject.customer_id == chat.customer_id,
                StoredObject.workspace_id.in_(workspaces),
                StoredObject.kind == "underlag",
            )
            .order_by(StoredObject.created_at.desc(), StoredObject.id)
            .execution_options(populate_existing=True)
        )
    )


async def require_chat_file(
    session: AsyncSession,
    user: UserAccount,
    chat: WorkspaceChat,
    object_id: str,
) -> StoredObject:
    files = await list_chat_files(session, user, chat)
    source = next((row for row in files if row.id == object_id), None)
    if source is None:
        raise HTTPException(status_code=404, detail="file_not_found")
    return source
