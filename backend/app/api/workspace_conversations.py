"""Private ElevenLabs sessions, local authenticated tools and workspace history."""

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database.models import UserAccount
from app.database.session import get_session
from app.services import jobs as jobs_service
from app.schemas.workspace import WorkspaceState
from app.services.elevenlabs_agents import ElevenLabsAgentsClient, ElevenLabsError, get_elevenlabs_client
from app.services.workspace.service import require_workspace
from app.services.workspace.tools import execute_workspace_tool
from app.services.workspace_agent_deployment import SERVER_TOOLS
from app.services.workspace_conversation_events import persist_event
from app.services.workspace_conversations import (
    attach_turn_context, clear_thread_messages, operation_key, require_conversation, start_conversation,
    thread_messages,
)

router = APIRouter(prefix="/workspace-chat", tags=["workspace-conversations"])


class StartConversationRequest(BaseModel):
    expert_id: str = Field(min_length=1, max_length=64)
    mode: Literal["text", "voice"]
    language: Literal["sv", "en"] = "sv"


class BindConversationRequest(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=128)


class ConversationEventRequest(BaseModel):
    event_key: str = Field(min_length=1, max_length=160)
    kind: Literal["user", "agent", "correction", "complete"]
    text: str = Field(default="", max_length=100000)
    original_event_key: str | None = Field(default=None, max_length=160)
    workspace_revision: int | None = Field(default=None, ge=0)
    context_snapshot: WorkspaceState | None = None

    @model_validator(mode="after")
    def validate_content(self):
        if self.kind in {"user", "agent"} and not self.text.strip():
            raise ValueError("message text is required")
        if self.kind in {"complete", "correction"} and not self.original_event_key:
            raise ValueError("original_event_key is required")
        return self


class WorkspaceSessionToolRequest(BindConversationRequest):
    agent_turn: int = Field(ge=0)
    arguments_json: str = Field(min_length=2, max_length=100000)
    turn_event_key: str | None = Field(default=None, min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_turn(self):
        if self.agent_turn > 0 and self.turn_event_key is None:
            raise ValueError("turn_event_key is required for a user turn")
        return self


@router.post("/{workspace_id}/sessions")
async def bootstrap(workspace_id: str, payload: StartConversationRequest, response: Response, *,
                    session: AsyncSession = Depends(get_session), user: UserAccount = Depends(get_current_user),
                    client: ElevenLabsAgentsClient = Depends(get_elevenlabs_client)) -> dict:
    try:
        result = await start_conversation(session, workspace_id=workspace_id, user=user, request=payload, client=client)
    except ElevenLabsError as exc:
        raise HTTPException(exc.status, exc.code) from None
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post("/{workspace_id}/sessions/{session_id}/bind")
async def bind(workspace_id: str, session_id: str, payload: BindConversationRequest, *,
               session: AsyncSession = Depends(get_session), user: UserAccount = Depends(get_current_user)) -> dict:
    row = await require_conversation(session, session_id=session_id, workspace_id=workspace_id, user=user)
    if row.conversation_id != payload.conversation_id:
        raise HTTPException(409, "workspace_conversation_binding_mismatch")
    return {"session_id": row.id, "generation": row.generation, "conversation_id": row.conversation_id}


@router.delete("/{workspace_id}/sessions/{session_id}")
async def revoke(workspace_id: str, session_id: str,
                 session: AsyncSession = Depends(get_session), user: UserAccount = Depends(get_current_user)) -> dict:
    row = await require_conversation(session, session_id=session_id, workspace_id=workspace_id, user=user, active=False)
    row.status = "revoked"
    result = {"session_id": row.id, "status": row.status}
    await session.commit()
    return result


@router.post("/{workspace_id}/sessions/{session_id}/events")
async def transcript_event(workspace_id: str, session_id: str, payload: ConversationEventRequest, *,
                           session: AsyncSession = Depends(get_session), user: UserAccount = Depends(get_current_user)) -> dict:
    row = await require_conversation(session, session_id=session_id, workspace_id=workspace_id, user=user)
    return await persist_event(session, provider=row, request=payload)


@router.get("/{workspace_id}/threads/{expert_id}/messages")
async def history(workspace_id: str, expert_id: str,
                  session: AsyncSession = Depends(get_session), user: UserAccount = Depends(get_current_user)) -> dict:
    workspace = await require_workspace(session, workspace_id, user)
    return {"messages": await thread_messages(session, workspace=workspace, expert_id=expert_id), "next_cursor": None}


@router.delete("/{workspace_id}/threads/{expert_id}/messages", status_code=204)
async def clear_history(workspace_id: str, expert_id: str,
                        session: AsyncSession = Depends(get_session), user: UserAccount = Depends(get_current_user)) -> None:
    workspace = await require_workspace(session, workspace_id, user)
    await clear_thread_messages(session, workspace=workspace, expert_id=expert_id)


def parse_arguments(payload: WorkspaceSessionToolRequest) -> dict:
    try:
        arguments = json.loads(payload.arguments_json)
    except ValueError:
        raise HTTPException(422, "invalid_workspace_tool_arguments") from None
    if not isinstance(arguments, dict):
        raise HTTPException(422, "invalid_workspace_tool_arguments")
    return arguments


@router.post("/{workspace_id}/sessions/{session_id}/tools/{tool_name}")
async def session_tool(workspace_id: str, session_id: str, tool_name: str, payload: WorkspaceSessionToolRequest, *,
                       session: AsyncSession = Depends(get_session), user: UserAccount = Depends(get_current_user)) -> dict:
    if tool_name not in (*SERVER_TOOLS, "expert_tool"):
        raise HTTPException(404, "workspace_tool_not_found")
    provider = await require_conversation(session, session_id=session_id, workspace_id=workspace_id, user=user)
    if payload.conversation_id != provider.conversation_id:
        raise HTTPException(401, "invalid_workspace_conversation_binding")
    arguments = parse_arguments(payload)
    await attach_turn_context(session, provider, event_key=payload.turn_event_key)
    if tool_name == "expert_tool":
        from app.services.workspace_expert_tools import execute_expert_tool
        result = await execute_expert_tool(session, provider=provider, user=user, arguments=arguments,
            idempotency_key=operation_key(provider, agent_turn=payload.agent_turn, tool_name=tool_name, arguments=arguments))
    else:
        # The domain command owns this request's transaction. Provider
        # validation adds no pending writes or caller-owned unrelated work.
        result = await execute_workspace_tool(session, workspace_id=provider.workspace_id, user=user,
            tool_name=tool_name, arguments=arguments,
            idempotency_key=operation_key(provider, agent_turn=payload.agent_turn, tool_name=tool_name, arguments=arguments),
            agent_session=provider)
    await session.commit()
    if result.get("status") == "queued" and result.get("job_id"):
        jobs_service.enqueue_job(result["job_id"])
    return result
