"""Persist a spoken expert turn in the in-character thread.

Memory is scheduled only when this turn_id is stored for the first time.
A repeat returns the same chat rows and does not write Mem0 again.
"""

from datetime import datetime

from fastapi import BackgroundTasks, HTTPException
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.scope import assert_kund_access
from app.database.models import Persona, PersonaMessage, UserAccount
from app.schemas.domain import EXPERT_CHAT_MODE, PersonaLiveMemoryRequest, PersonaMessageOut
from app.serializers import format_date, utcnow
from app.services.library_chat_fifo import trim_library_chat
from app.services.persona_chat import remember_expert_chat_turn


class LiveVoiceTranscriptRequest(PersonaLiveMemoryRequest):
    turn_id: str = Field(min_length=1, max_length=64)
    follow_up: bool = False


async def publish_live_voice_turn(
    session: AsyncSession,
    background_tasks: BackgroundTasks,
    *,
    persona_id: str,
    user: UserAccount,
    body: LiveVoiceTranscriptRequest,
) -> list[PersonaMessageOut]:
    persona = await session.get(Persona, persona_id)
    if persona is None:
        raise HTTPException(status_code=404, detail="Persona not found")
    assert_kund_access(user, persona.customer_id)
    if persona.kind != "expert":
        raise HTTPException(status_code=404, detail="Expert not found")
    rows, created = await store_live_voice_transcript(
        session,
        persona_id=persona.id,
        turn_id=body.turn_id,
        user_message=body.user_message,
        assistant_message=body.assistant_message,
        follow_up=body.follow_up,
    )
    messages = [_message_out(row) for row in rows]
    if not created:
        return messages
    await trim_library_chat(session, persona.id, EXPERT_CHAT_MODE)
    session.expunge(persona)
    await session.commit()
    background_tasks.add_task(
        remember_expert_chat_turn,
        persona,
        message=body.user_message,
        reply=body.assistant_message,
        image_sha256=None,
        session_id=body.session_id,
    )
    return messages


async def store_live_voice_transcript(
    session: AsyncSession,
    *,
    persona_id: str,
    turn_id: str,
    user_message: str,
    assistant_message: str,
    follow_up: bool = False,
) -> tuple[list[PersonaMessage], bool]:
    """Return the chat rows and whether this turn was stored now."""
    existing = await _load_turn(session, persona_id, turn_id)
    if existing:
        return existing, False
    now = utcnow()
    rows = _turn_rows(
        persona_id=persona_id,
        turn_id=turn_id,
        user_message=user_message,
        assistant_message=assistant_message,
        follow_up=follow_up,
        now=now,
    )
    try:
        async with session.begin_nested():
            session.add_all(rows)
            await session.flush()
    except IntegrityError:
        raced = await _load_turn(session, persona_id, turn_id)
        if len(raced) != len(rows):
            raise
        return raced, False
    return rows, True


def _turn_rows(
    *,
    persona_id: str,
    turn_id: str,
    user_message: str,
    assistant_message: str,
    follow_up: bool,
    now: datetime,
) -> list[PersonaMessage]:
    assistant_row = PersonaMessage(
        persona_id=persona_id,
        mode=EXPERT_CHAT_MODE,
        role="assistant",
        content=assistant_message,
        voice_turn_id=turn_id,
        created_at=now,
    )
    if follow_up:
        return [assistant_row]
    return [
        PersonaMessage(
            persona_id=persona_id,
            mode=EXPERT_CHAT_MODE,
            role="user",
            content=user_message,
            voice_turn_id=turn_id,
            created_at=now,
        ),
        assistant_row,
    ]


def _message_out(row: PersonaMessage) -> PersonaMessageOut:
    return PersonaMessageOut(
        id=row.id,
        mode=row.mode,  # type: ignore[arg-type]
        role=row.role,  # type: ignore[arg-type]
        content=row.content,
        created_at=format_date(row.created_at) if row.created_at else "",
        run_id=row.run_id,
        attempt_id=row.attempt_id,
        variant_id=row.variant_id,
        through_tick_index=row.through_tick_index,
        image_sha256=row.image_sha256,
    )


async def _load_turn(
    session: AsyncSession,
    persona_id: str,
    turn_id: str,
) -> list[PersonaMessage]:
    result = await session.execute(
        select(PersonaMessage)
        .where(
            PersonaMessage.persona_id == persona_id,
            PersonaMessage.voice_turn_id == turn_id,
        )
        .order_by(PersonaMessage.id.asc())
    )
    return list(result.scalars().all())
