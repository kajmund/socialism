"""Persist the canonical visible prefix when a voice turn is interrupted."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import PersonaMessage
from app.schemas.domain import EXPERT_CHAT_MODE
from app.serializers import utcnow
from app.services.library_chat_fifo import trim_library_chat
from app.services.sme_expert_turns import finish_expert_turn


async def persist_interrupted_voice_turn(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    request_id: str,
    fence: int,
    turn_id: str,
    persona_id: str,
    user_text: str,
    assistant_text: str,
) -> None:
    async with session_factory() as session:
        await finish_expert_turn(
            session,
            request_id,
            fence=fence,
            status="failed",
            error="cancelled",
        )
        result = await session.scalars(
            select(PersonaMessage).where(
                PersonaMessage.persona_id == persona_id,
                PersonaMessage.sme_expert_turn_request_id == request_id,
            )
        )
        rows = list(result.all())
        user = next((row for row in rows if row.role == "user"), None)
        assistant = next((row for row in rows if row.role == "assistant"), None)
        if user is None:
            user = PersonaMessage(
                persona_id=persona_id,
                mode=EXPERT_CHAT_MODE,
                role="user",
                content=user_text,
                sme_expert_turn_request_id=request_id,
                created_at=utcnow(),
            )
            session.add(user)
        user.voice_turn_id = turn_id
        if assistant_text.strip():
            if assistant is None:
                assistant = PersonaMessage(
                    persona_id=persona_id,
                    mode=EXPERT_CHAT_MODE,
                    role="assistant",
                    sme_expert_turn_request_id=request_id,
                    created_at=utcnow(),
                )
                session.add(assistant)
            assistant.content = assistant_text.strip()
            assistant.voice_turn_id = turn_id
            assistant.interrupted = True
        elif assistant is not None:
            await session.delete(assistant)
        await trim_library_chat(session, persona_id, EXPERT_CHAT_MODE)
        await session.commit()
