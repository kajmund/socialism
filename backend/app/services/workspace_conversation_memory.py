"""Deduplicate completed turns and repair late corrections outside DB transactions."""

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Persona, PersonaMessage
from app.database.workspace_conversations import WorkspaceConversationEvent, WorkspaceConversationSession
from app.database.workspace_models import VoiceWorkspace
from app.services.expertgranskning.memory import get_expert_memory, memory_belongs_to
from app.services.workspace_memory_scope import WORKSPACE_MEMORY_SOURCE, workspace_memory_expert_id


async def claim_memory(session: AsyncSession, provider_id: str, event_key: str) -> dict | None:
    event = (await session.execute(select(WorkspaceConversationEvent).where(
        WorkspaceConversationEvent.session_id == provider_id, WorkspaceConversationEvent.event_key == event_key)
        .with_for_update())).scalar_one()
    if not event.payload.get("completed"):
        await session.rollback()
        return None
    provider = await session.get(WorkspaceConversationSession, provider_id)
    assistant = await session.get(PersonaMessage, event.message_id)
    previous = (await session.execute(select(PersonaMessage).join(
        WorkspaceConversationEvent, WorkspaceConversationEvent.message_id == PersonaMessage.id).where(
        WorkspaceConversationEvent.session_id == provider_id, WorkspaceConversationEvent.kind == "user",
        PersonaMessage.id < event.message_id).order_by(PersonaMessage.id.desc()).limit(1))).scalar_one_or_none()
    digest = hashlib.sha256(json_bytes([previous.content if previous else "", assistant.content])).hexdigest()
    lease = event.payload.get("memory_lease_until", "")
    if event.payload.get("memory_digest") == digest or (lease and datetime.fromisoformat(lease) > datetime.now(UTC)):
        await session.rollback()
        return None
    persona = await session.get(Persona, provider.expert_id)
    workspace = await session.get(VoiceWorkspace, provider.workspace_id)
    claim = str(uuid4())
    prepared = {"event_id": event.id, "claim": claim, "digest": digest, "persona": persona,
                "user_text": previous.content if previous else "", "assistant_text": assistant.content,
                "memory_ids": event.payload.get("memory_ids", []),
                "scope": f"workspace:{workspace.workspace_id}:chat:{workspace.chat_id}:native:{provider_id}:{event_key}",
                "memory_expert_id": workspace_memory_expert_id(persona, provider.user_id,
                                                               workspace_parent_id=workspace.workspace_id)}
    event.payload = {**event.payload, "memory_claim": claim, "memory_state": "processing",
                     "memory_lease_until": (datetime.now(UTC) + timedelta(minutes=5)).isoformat()}
    session.expunge(persona)
    await session.commit()
    return prepared


def json_bytes(value: object) -> bytes:
    import json
    return json.dumps(value, ensure_ascii=False).encode()


async def replace_turn_memory(prepared: dict) -> list[str]:
    persona = prepared["persona"]
    memory = get_expert_memory()
    for memory_id in prepared["memory_ids"]:
        hit = await memory.get(memory_id=memory_id)
        if (hit and memory_belongs_to(hit, customer_id=persona.customer_id, expert_id=prepared["memory_expert_id"])
                and hit.metadata.get("session_id") == prepared["scope"]):
            await memory.delete(memory_id=memory_id)
    if not prepared["user_text"] or not prepared["assistant_text"].strip():
        return []
    hits = await memory.add_chat_turn(customer_id=persona.customer_id, expert_id=prepared["memory_expert_id"],
        user_message=prepared["user_text"], assistant_message=prepared["assistant_text"],
        source=WORKSPACE_MEMORY_SOURCE, session_id=prepared["scope"])
    return [hit.id for hit in hits]


async def finish_memory(session: AsyncSession, prepared: dict, memory_ids: list[str] | None) -> None:
    event = (await session.execute(select(WorkspaceConversationEvent).where(
        WorkspaceConversationEvent.id == prepared["event_id"]).with_for_update())).scalar_one()
    if event.payload.get("memory_claim") == prepared["claim"]:
        payload = {**event.payload, "memory_lease_until": "", "memory_state": "failed" if memory_ids is None else "saved"}
        if memory_ids is not None:
            payload.update(memory_digest=prepared["digest"], memory_ids=memory_ids)
        event.payload = payload
    await session.commit()


async def synchronize_memory(session: AsyncSession, provider_id: str, event_key: str) -> None:
    # A correction may be persisted while the first extraction is pending.
    # The lease admits one writer; that writer rechecks the latest literal text.
    while prepared := await claim_memory(session, provider_id, event_key):
        saved = False
        try:
            memory_ids = await replace_turn_memory(prepared)
            await finish_memory(session, prepared, memory_ids)
            saved = True
        finally:
            if not saved:
                await finish_memory(session, prepared, None)
