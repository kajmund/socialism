"""Persist final native transcript events, then enrich context without DB locks."""

import json

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Persona, PersonaMessage, UserAccount
from app.database.transaction_state import has_pending_writes
from app.database.workspace_conversations import WorkspaceConversationEvent, WorkspaceConversationSession
from app.database.workspace_models import VoiceWorkspace
from app.schemas.workspace import WorkspaceState
from app.services.workspace_memory_context import workspace_memory_context
from app.services.workspace_parent_documents import voice_document_inventory
from app.services.prompt_store import require_active_prompts
from app.services.workspace.service import validate_state
from app.services.workspace_conversations import find_event, redact_text, require_conversation
from app.services.workspace_conversation_memory import synchronize_memory
from app.services.workspace_event_selection import PreparedUserSelection, materialize_user_selection, prepare_user_selection


def check_redelivery(existing: WorkspaceConversationEvent, request) -> None:
    incoming = redact_text(request.text)
    if (existing.kind != request.kind or existing.payload.get("input_text") != incoming
            or existing.payload.get("original_event_key") != request.original_event_key):
        raise HTTPException(409, "workspace_event_key_conflict")


async def store_user_context(session: AsyncSession, provider: WorkspaceConversationSession, request, payload: dict, *,
                             selection: PreparedUserSelection | None = None) -> dict:
    workspace = await session.get(VoiceWorkspace, provider.workspace_id)
    state = (await materialize_user_selection(session, selection) if selection is not None else
             WorkspaceState.model_validate(request.context_snapshot if request.context_snapshot is not None else workspace.state))
    if state.expert_id != provider.expert_id:
        raise HTTPException(409, "workspace_conversation_expert_changed")
    await validate_state(session, workspace, state)
    payload.update(workspace_state=state.model_dump(),
                   workspace_revision=request.workspace_revision if request.workspace_revision is not None else workspace.revision)
    return await user_memory_input(session, provider, request.event_key, payload)


async def user_memory_input(session: AsyncSession, provider: WorkspaceConversationSession, event_key: str, payload: dict) -> dict:
    workspace = await session.get(VoiceWorkspace, provider.workspace_id)
    prompts = await require_active_prompts(session, customer_id=provider.customer_id, module=workspace.module, language=provider.language)
    persona = await session.get(Persona, provider.expert_id)
    owner = await session.get(UserAccount, provider.user_id)
    if owner is None:
        raise HTTPException(404, "workspace_conversation_not_found")
    inventory = await voice_document_inventory(session, workspace, owner)
    session.expunge(persona)
    return {"persona": persona, "prompts": prompts, "query": payload["text"], "owner_id": provider.user_id,
            "workspace_parent_id": workspace.workspace_id,
            "context": {"voice_workspace_id": workspace.id, "workspace_id": workspace.workspace_id,
                        "chat_id": workspace.chat_id, "turn_event_key": event_key, "state": payload["workspace_state"],
                        "revision": payload["workspace_revision"], "available_documents": inventory}}


async def store_original_update(session: AsyncSession, provider: WorkspaceConversationSession, request, payload: dict) -> int:
    original = await find_event(session, provider, request.original_event_key or "")
    if original is None or original.kind != "agent" or not original.message_id:
        raise HTTPException(404, "workspace_agent_event_not_found")
    if request.kind == "correction":
        message = await session.get(PersonaMessage, original.message_id)
        message.content = payload["text"]
        original.payload = {**original.payload, "text": payload["text"], "interrupted": True}
    else:
        original.payload = {**original.payload, "completed": True}
    return original.message_id


async def prepare_event(session: AsyncSession, provider: WorkspaceConversationSession, request,
                        selection: PreparedUserSelection | None = None) -> tuple[dict, dict | None]:
    existing = await find_event(session, provider, request.event_key)
    if existing:
        check_redelivery(existing, request)
        memory_input = None
        if request.kind == "user" and existing.payload.get("context") is None:
            memory_input = await user_memory_input(session, provider, request.event_key, existing.payload)
        result = {"message_id": existing.message_id, "duplicate": True, "context": existing.payload.get("context")}
        return result, memory_input
    content = redact_text(request.text)
    payload = {"text": content, "input_text": content, "original_event_key": request.original_event_key}
    memory_input = None
    if request.kind in {"complete", "correction"}:
        message_id = await store_original_update(session, provider, request, payload)
    else:
        if request.kind == "user":
            memory_input = await store_user_context(session, provider, request, payload, selection=selection)
        message = PersonaMessage(persona_id=provider.expert_id, mode="workspace",
                                 role="user" if request.kind == "user" else "assistant", content=content)
        session.add(message)
        await session.flush()
        message_id = message.id
    session.add(WorkspaceConversationEvent(session_id=provider.id, event_key=request.event_key,
                                          kind=request.kind, message_id=message_id, payload=payload))
    await session.flush()
    return {"message_id": message_id, "duplicate": False, "context": None}, memory_input


async def enrich_user_context(session: AsyncSession, provider_id: str, event_key: str, prepared: dict) -> str:
    memories = await workspace_memory_context(prepared["persona"], prepared["query"], prepared["prompts"],
                                              owner_id=prepared["owner_id"], workspace_parent_id=prepared["workspace_parent_id"])
    owner = await session.get(UserAccount, prepared["owner_id"], populate_existing=True)
    if owner is None:
        raise HTTPException(404, "workspace_conversation_not_found")
    provider = await require_conversation(session, session_id=provider_id,
        workspace_id=prepared["context"]["voice_workspace_id"], user=owner)
    event = await find_event(session, provider, event_key)
    # Literal events remain durable if the session was superseded during Mem0.
    if provider.status != "active":
        await session.rollback()
        raise HTTPException(409, "workspace_conversation_superseded")
    workspace = await session.get(VoiceWorkspace, provider.workspace_id, populate_existing=True)
    inventory = await voice_document_inventory(session, workspace, owner)
    context = json.dumps({**prepared["context"], "available_documents": inventory,
                          "expert_memory": memories}, ensure_ascii=False)
    event.payload = {**event.payload, "context": context}
    await session.commit()
    return context


async def persist_event(session: AsyncSession, *, provider: WorkspaceConversationSession, request) -> dict:
    if has_pending_writes(session):
        raise RuntimeError("Conversation events require a clean transaction")
    provider_id = provider.id
    selection = None
    if request.kind == "user" and await find_event(session, provider, request.event_key) is None:
        selection = await prepare_user_selection(session, provider, request)
        provider = selection.provider
    result, prepared = await prepare_event(session, provider, request, selection)
    # The transcript belongs to this request and survives external-memory
    # errors. Redelivery retries enrichment without duplicating chat rows.
    await session.commit()
    if prepared is not None:
        result["context"] = await enrich_user_context(session, provider_id, request.event_key, prepared)
    if request.kind in {"complete", "correction"}:
        await synchronize_memory(session, provider_id, request.original_event_key)
    return result
