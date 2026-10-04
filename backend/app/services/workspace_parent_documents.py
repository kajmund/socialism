"""Materialized document discovery within the active and company workspaces."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import UserAccount
from app.database.workspace_models import VoiceWorkspace
from app.database.workspaces import WorkspaceChat
from app.services.workspace.containers import require_container
from app.services.workspace_chats import list_chat_files


async def available_documents(
    session: AsyncSession, user: UserAccount, chat: WorkspaceChat
) -> list[dict]:
    return [
        {
            "source_object_id": source.id,
            "filename": source.filename,
            "workspace_id": source.workspace_id,
            "knowledge_status": source.knowledge_status,
        }
        for source in await list_chat_files(session, user, chat)
    ]


async def voice_document_inventory(
    session: AsyncSession, workspace: VoiceWorkspace, user: UserAccount
) -> list[dict]:
    chat = await require_container(session, workspace, user)
    return await available_documents(session, user, chat)
