"""Bind a private voice canvas to the existing customer workspace and chat."""
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import UserAccount
from app.database.workspace_models import VoiceWorkspace
from app.database.workspaces import WorkspaceChat
from app.services.workspace_chats import require_chat
from app.services.workspaces import require_workspace_customer, resolve_workspace


@dataclass(frozen=True)
class WorkspaceContainer:
    workspace_id: str | None = None
    chat_id: str | None = None
    customer_id: int | None = None


async def require_container(session: AsyncSession, canvas: VoiceWorkspace, user: UserAccount) -> WorkspaceChat:
    chat = await require_chat(session, user, canvas.chat_id, canvas.customer_id)
    if (chat.workspace_id != canvas.workspace_id or chat.owner_user_id != canvas.owner_user_id
            or chat.module != canvas.module):
        raise HTTPException(status_code=404, detail="voice_workspace_container_not_found")
    return chat


async def creation_chat(session: AsyncSession, user: UserAccount, container: WorkspaceContainer,
                        *, title: str, module: str, creation_key: str) -> WorkspaceChat:
    customer = await require_workspace_customer(session, user, container.customer_id)
    if container.chat_id is not None:
        chat = await require_chat(session, user, container.chat_id, customer)
        if ((container.workspace_id is not None and chat.workspace_id != container.workspace_id)
                or chat.module != module):
            raise HTTPException(status_code=409, detail="voice_workspace_container_conflict")
        return chat
    workspace = await resolve_workspace(session, customer_id=customer, user_id=user.id,
                                        workspace_id=container.workspace_id)
    # The same creation key must not leave duplicate core chats under concurrent retries.
    chat_id = str(uuid5(NAMESPACE_URL, f"socialism:voice-chat:{user.id}:{creation_key}"))
    insert = sqlite_insert if session.get_bind().dialect.name == "sqlite" else pg_insert
    await session.execute(insert(WorkspaceChat).values(id=chat_id, customer_id=customer,
        workspace_id=workspace.id, owner_user_id=user.id, persona_id=None, module=module,
        title=title.strip()).on_conflict_do_nothing(index_elements=["id"]))
    chat = await require_chat(session, user, chat_id, customer)
    if chat.workspace_id != workspace.id or chat.module != module:
        raise HTTPException(status_code=409, detail="voice_workspace_container_conflict")
    return chat
