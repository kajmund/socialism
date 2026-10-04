"""Materialized file availability and document selection for workspace chat."""

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import UserAccount
from app.database.workspaces import WorkspaceChat
from app.services.expert_session_tools import RESEARCH_TOOL_NAME
from app.services.workspace_chats import list_chat_files


async def document_inventory(
    session: AsyncSession, user: UserAccount, chat: WorkspaceChat
) -> str:
    files = await list_chat_files(session, user, chat)
    return json.dumps(
        [
            {
                "source_object_id": source.id,
                "filename": source.filename,
                "workspace_id": source.workspace_id,
                "knowledge_status": source.knowledge_status,
            }
            for source in files
        ],
        ensure_ascii=False,
    )


def workspace_research_tool_spec() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": RESEARCH_TOOL_NAME,
            "description": (
                "Queue research using selected existing workspace documents. "
                "Returns a pending job ID; the completed answer is delivered later."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The user's actual, standalone question to answer.",
                    },
                    "source_object_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "IDs of the selected existing documents from the inventory. "
                            "Use the named document's ID for a file-specific question. "
                            "An empty list selects no documents; omission selects all "
                            "readable workspace documents. Selected files must be ready."
                        ),
                    },
                },
                "required": ["question"],
                "additionalProperties": False,
            },
        },
    }
