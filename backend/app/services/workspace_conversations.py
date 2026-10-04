"""Authorize provider sessions and reserve generations before external work."""

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import PersonaMessage, UserAccount
from app.database.workspace_conversations import WorkspaceConversationEvent, WorkspaceConversationSession
from app.database.workspace_models import VoiceWorkspace
from app.schemas.workspace import WorkspaceState
from app.services.elevenlabs_agents import ElevenLabsAgentsClient
from app.services.workspace_memory_context import workspace_memory_context
from app.services.workspace_parent_documents import voice_document_inventory
from app.services.workspace.service import require_expert, require_workspace, validate_state
from app.services.workspace_agent_deployment import (
    deploy_agent_snapshot, prepare_agent_snapshot,
)


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def redact_text(text: str) -> str:
    if len(settings.elevenlabs_api_key) >= 16:
        text = text.replace(settings.elevenlabs_api_key, "<REDACTED>")
    text = re.sub(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "<REDACTED>", text)
    return re.sub(r"([?&](?:conversation_signature|signature|token|api_key)=)[^&\s]+",
                  r"\1<REDACTED>", text, flags=re.IGNORECASE)


async def require_conversation(session: AsyncSession, *, session_id: str, workspace_id: str,
                               user: UserAccount, active: bool = True) -> WorkspaceConversationSession:
    workspace = await require_workspace(session, workspace_id, user)
    row = (await session.execute(select(WorkspaceConversationSession).where(
        WorkspaceConversationSession.id == session_id).with_for_update())).scalar_one_or_none()
    if row is None or row.workspace_id != workspace.id or row.user_id != user.id or row.customer_id != workspace.customer_id:
        raise HTTPException(404, "workspace_conversation_not_found")
    if active and (row.status != "active" or aware(row.expires_at) <= datetime.now(UTC)):
        raise HTTPException(401, "workspace_conversation_expired_or_revoked")
    if active and workspace.state.get("expert_id") != row.expert_id:
        raise HTTPException(409, "workspace_conversation_expert_changed")
    return row


async def reserve_conversation(session: AsyncSession, *, workspace_id: str, user: UserAccount, request) -> dict:
    workspace = await require_workspace(session, workspace_id, user)
    await session.execute(select(VoiceWorkspace).where(VoiceWorkspace.id == workspace.id).with_for_update())
    # Reload after acquiring the generation lock: another bootstrap may have
    # committed while this request waited for the row.
    await session.refresh(workspace)
    persona = await require_expert(session, workspace, request.expert_id)
    state = WorkspaceState.model_validate({**workspace.state, "expert_id": request.expert_id})
    await validate_state(session, workspace, state)
    if workspace.state != state.model_dump():
        workspace.state = state.model_dump()
        workspace.revision += 1
    snapshot = await prepare_agent_snapshot(session, persona=persona, language=request.language, module=workspace.module)
    await session.execute(update(WorkspaceConversationSession).where(
        WorkspaceConversationSession.workspace_id == workspace.id,
        WorkspaceConversationSession.status.in_(("starting", "active"))).values(status="revoked"))
    maximum = await session.scalar(select(func.max(WorkspaceConversationSession.generation)).where(
        WorkspaceConversationSession.workspace_id == workspace.id))
    row = WorkspaceConversationSession(
        id=str(uuid4()), workspace_id=workspace.id, user_id=user.id, customer_id=workspace.customer_id,
        expert_id=request.expert_id, mode=request.mode, language=request.language, generation=(maximum or 0) + 1,
        status="starting", expires_at=datetime.now(UTC) + timedelta(seconds=settings.elevenlabs_session_ttl_seconds),
        prompt_version=snapshot.prompt_version, agent_version="", agent_id="")
    session.add(row)
    await session.flush()
    session.add(WorkspaceConversationEvent(session_id=row.id, event_key="session-context", kind="init",
        payload={"workspace_state": state.model_dump(), "workspace_revision": workspace.revision}))
    history = await thread_messages(session, workspace=workspace, expert_id=request.expert_id)
    prepared = {"session_id": row.id, "snapshot": snapshot, "persona": persona, "owner_id": user.id,
                "query": history[-1]["content"] if history else workspace.title,
                "workspace_parent_id": workspace.workspace_id,
                "context": {"voice_workspace_id": workspace.id, "workspace_id": workspace.workspace_id,
                            "chat_id": workspace.chat_id, "revision": workspace.revision, "state": state.model_dump(),
                            "expert_id": request.expert_id, "history": history[-40:],
                            "available_documents": await voice_document_inventory(session, workspace, user)}}
    session.expunge(persona)
    await session.commit()
    return prepared


async def activate_conversation(session: AsyncSession, prepared: dict, deployment: dict, connection: dict) -> dict:
    row = (await session.execute(select(WorkspaceConversationSession).where(
        WorkspaceConversationSession.id == prepared["session_id"]).with_for_update())).scalar_one()
    owner = await session.get(UserAccount, prepared["owner_id"], populate_existing=True)
    if owner is None:
        raise HTTPException(404, "workspace_conversation_not_found")
    workspace = await require_workspace(session, row.workspace_id, owner)
    if row.status != "starting" or workspace.state.get("expert_id") != row.expert_id or aware(row.expires_at) <= datetime.now(UTC):
        await session.rollback()
        raise HTTPException(409, "workspace_conversation_superseded")
    prepared["context"]["available_documents"] = await voice_document_inventory(session, workspace, owner)
    row.agent_id, row.agent_version = deployment["agent_id"], deployment["agent_version"]
    row.conversation_id, row.status = connection["conversation_id"], "active"
    result = {"session_id": row.id, "generation": row.generation, "expires_at": aware(row.expires_at).isoformat(),
              "agent_id": row.agent_id, "agent_version": row.agent_version, "prompt_version": row.prompt_version,
              **connection, "dynamic_variables": {}, "context": json.dumps(prepared["context"], ensure_ascii=False)}
    await session.commit()
    return result


async def abandon_conversation(session: AsyncSession, session_id: str) -> None:
    await session.rollback()
    await session.execute(update(WorkspaceConversationSession).where(
        WorkspaceConversationSession.id == session_id, WorkspaceConversationSession.status == "starting").values(status="failed"))
    await session.commit()


async def start_conversation(session: AsyncSession, *, workspace_id: str, user: UserAccount,
                              request, client: ElevenLabsAgentsClient) -> dict:
    # This request owns its unit of work. Only its intentional state/session
    # writes are committed before provider HTTP and Mem0 are allowed to run.
    prepared = await reserve_conversation(session, workspace_id=workspace_id, user=user, request=request)
    completed = False
    try:
        deployment = await deploy_agent_snapshot(session, prepared["snapshot"], client)
        connection = await client.connection(agent_id=deployment["agent_id"],
                                             agent_version=deployment["agent_version"], mode=request.mode)
        memories = await workspace_memory_context(prepared["persona"], prepared["query"],
                                                  prepared["snapshot"].prompts, owner_id=prepared["owner_id"],
                                                  workspace_parent_id=prepared["workspace_parent_id"])
        prepared["context"]["expert_memory"] = memories
        result = await activate_conversation(session, prepared, deployment, connection)
        completed = True
        return result
    finally:
        if not completed:
            await abandon_conversation(session, prepared["session_id"])


async def thread_messages(session: AsyncSession, *, workspace: VoiceWorkspace, expert_id: str, limit: int = 200) -> list[dict]:
    await require_expert(session, workspace, expert_id)
    stmt = (select(PersonaMessage, WorkspaceConversationEvent, WorkspaceConversationSession)
            .join(WorkspaceConversationEvent, WorkspaceConversationEvent.message_id == PersonaMessage.id)
            .join(WorkspaceConversationSession, WorkspaceConversationSession.id == WorkspaceConversationEvent.session_id)
            .where(WorkspaceConversationSession.workspace_id == workspace.id, WorkspaceConversationSession.expert_id == expert_id,
                   WorkspaceConversationEvent.kind.in_(("user", "agent")))
            .order_by(PersonaMessage.id.desc()).limit(limit))
    rows = (await session.execute(stmt)).all()
    return [{"id": message.id, "role": "user" if message.role == "user" else "agent", "content": message.content,
             "created_at": aware(message.created_at).isoformat(), "event_key": event.event_key, "session_id": provider.id}
            for message, event, provider in reversed(rows)]


async def find_event(session: AsyncSession, provider: WorkspaceConversationSession, key: str) -> WorkspaceConversationEvent | None:
    return (await session.execute(select(WorkspaceConversationEvent).where(
        WorkspaceConversationEvent.session_id == provider.id, WorkspaceConversationEvent.event_key == key))).scalar_one_or_none()


async def attach_turn_context(session: AsyncSession, provider: WorkspaceConversationSession, *, event_key: str | None) -> None:
    turn = await find_event(session, provider, event_key or "session-context")
    if turn is None or turn.kind != ("user" if event_key else "init"):
        raise HTTPException(409, "workspace_tool_turn_binding_missing")
    provider.turn_state = turn.payload.get("workspace_state", {})
    provider.turn_revision = turn.payload.get("workspace_revision")
    provider.turn_event_key = turn.event_key
    if turn.kind == "init":
        provider.turn_user_text, provider.turn_previous_agent_text = "", ""
        return
    previous = (await session.execute(select(WorkspaceConversationEvent).where(
        WorkspaceConversationEvent.session_id == provider.id, WorkspaceConversationEvent.kind == "agent",
        WorkspaceConversationEvent.message_id < turn.message_id).order_by(
        WorkspaceConversationEvent.message_id.desc()).limit(1))).scalar_one_or_none()
    provider.turn_user_text = turn.payload.get("text", "")
    provider.turn_previous_agent_text = previous.payload.get("text", "") if previous else ""


def operation_key(provider: WorkspaceConversationSession, *, agent_turn: int, tool_name: str, arguments: dict) -> str:
    canonical = json.dumps([provider.id, agent_turn, tool_name, arguments], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
