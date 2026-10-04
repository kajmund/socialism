"""Workspace-only chat history and the shared modal/tool research entry point."""

import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import complete_text, complete_with_tools
from app.database.models import Persona, UserAccount
from app.database.workspaces import Workspace, WorkspaceChat, WorkspaceChatMessage
from app.schemas.workspace_chat import WorkspaceResearchRequest
from app.services.expert_session_tools import RESEARCH_TOOL_NAME
from app.services.prompt_catalog import render_prompt
from app.services.prompt_store import require_active_prompts
from app.services.workspace_chat_documents import document_inventory, workspace_research_tool_spec
from app.services.workspace_chats import require_chat
from app.services.workspace_research_start import queue_workspace_research

_locks: dict[str, asyncio.Lock] = {}


@asynccontextmanager
async def chat_turn_lock(chat_id: str):
    lock = _locks.setdefault(chat_id, asyncio.Lock())
    if lock.locked():
        raise HTTPException(status_code=409, detail="chat_turn_running")
    await lock.acquire()
    try:
        yield
    finally:
        lock.release()


async def _turn_messages(
    session: AsyncSession, user: UserAccount, chat: WorkspaceChat
) -> list[dict]:
    workspace = await session.get(Workspace, chat.workspace_id)
    persona = await session.get(Persona, chat.persona_id) if chat.persona_id else None
    prompts = await require_active_prompts(
        session, customer_id=chat.customer_id, module=chat.module, language="sv"
    )
    identity = persona.name if persona is not None else workspace.name
    profile = json.dumps(persona.profile, ensure_ascii=False) if persona is not None else ""
    system = render_prompt(
        prompts,
        "chat.workspace.system",
        workspace_name=workspace.name,
        assistant_name=identity,
        profile=profile,
        available_documents=await document_inventory(session, user, chat),
    )
    rows = list(
        await session.scalars(
            select(WorkspaceChatMessage)
            .where(
                WorkspaceChatMessage.chat_id == chat.id,
                WorkspaceChatMessage.role.in_(("user", "assistant")),
            )
            .order_by(WorkspaceChatMessage.id.desc())
            .limit(40)
        )
    )
    return [
        {"role": "system", "content": system},
        *[{"role": row.role, "content": row.content} for row in reversed(rows)],
    ]


async def _run_tool_calls(session, user, chat, reply, *, messages) -> str:
    calls = reply.tool_calls
    if len(calls) != 1 or calls[0].function.name != RESEARCH_TOOL_NAME:
        raise HTTPException(status_code=502, detail="invalid_workspace_tool_call")
    call = calls[0]
    try:
        arguments = json.loads(call.function.arguments)
        request = WorkspaceResearchRequest(
            question=arguments["question"],
            source_object_ids=arguments.get("source_object_ids"),
            entrypoint="tool",
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="invalid_research_tool_arguments") from exc
    job = await queue_workspace_research(session, user, chat, request)
    result = json.dumps({"job_id": job.id, "status": "pending", "result": None}, ensure_ascii=False)
    messages.extend(
        [
            {
                "role": "assistant",
                "content": reply.content,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": call.id, "content": result},
        ]
    )
    return await complete_text(messages, prompt_key="chat.workspace.system")


async def workspace_chat_turn(
    session: AsyncSession,
    user: UserAccount,
    chat_id: str,
    content: str,
    *,
    customer_id: int | None = None,
) -> WorkspaceChat:
    if not content.strip():
        raise HTTPException(status_code=422, detail="chat_message_required")
    async with chat_turn_lock(chat_id):
        chat = await require_chat(session, user, chat_id, customer_id)
        session.add(WorkspaceChatMessage(chat_id=chat.id, role="user", content=content.strip()))
        if not chat.title:
            chat.title = content.strip()[:120]
        await session.flush()
        messages = await _turn_messages(session, user, chat)
        # Materialize ORM fields before deliberately releasing the input transaction.
        await session.commit()
        completion = await complete_with_tools(
            messages, [workspace_research_tool_spec()], prompt_key="chat.workspace.system"
        )
        reply = completion
        text = (
            await _run_tool_calls(session, user, chat, reply, messages=messages)
            if reply.tool_calls
            else reply.content
        )
        if not text or not text.strip():
            raise HTTPException(status_code=502, detail="empty_chat_reply")
        session.add(WorkspaceChatMessage(chat_id=chat.id, role="assistant", content=text.strip()))
        await session.commit()
        return chat
