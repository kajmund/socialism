"""Freeze recent expert chat into a document-generation brief."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PersonaMessage
from app.schemas.domain import EXPERT_CHAT_MODE

_CONVERSATION_TURNS = 16
_CONVERSATION_CHARS = 8000


async def document_conversation_brief(
    session: AsyncSession, expert_id: str | None,
) -> list[dict[str, str]]:
    if not expert_id:
        return []
    rows = (
        await session.scalars(
            select(PersonaMessage)
            .where(
                PersonaMessage.persona_id == expert_id,
                PersonaMessage.mode == EXPERT_CHAT_MODE,
                PersonaMessage.run_id.is_(None),
            )
            .order_by(PersonaMessage.id.desc())
            .limit(_CONVERSATION_TURNS)
        )
    ).all()
    selected: list[dict[str, str]] = []
    used = 0
    for row in rows:
        text = row.content.strip()
        if not text:
            continue
        remaining = _CONVERSATION_CHARS - used
        if remaining <= 0:
            break
        selected.append({"role": row.role, "content": text[:remaining]})
        used += min(len(text), remaining)
    return list(reversed(selected))
