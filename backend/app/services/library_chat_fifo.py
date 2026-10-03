"""Library chat keeps the newest messages and drops the oldest."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PersonaMessage

LIBRARY_CHAT_MESSAGE_LIMIT = 40


async def trim_library_chat(
    session: AsyncSession,
    persona_id: str,
    mode: str,
) -> bool:
    """Delete library rows beyond the newest limit. Run-scoped interviews stay."""
    await session.flush()
    result = await session.execute(
        select(PersonaMessage)
        .where(
            PersonaMessage.persona_id == persona_id,
            PersonaMessage.mode == mode,
            PersonaMessage.run_id.is_(None),
        )
        .order_by(PersonaMessage.id.desc())
        .offset(LIBRARY_CHAT_MESSAGE_LIMIT)
    )
    stale = list(result.scalars().all())
    if not stale:
        return False
    for row in stale:
        await session.delete(row)
    await session.flush()
    return True


async def trim_and_commit_library_chat(
    session: AsyncSession,
    persona_id: str,
    mode: str,
) -> None:
    await trim_library_chat(session, persona_id, mode)
    await session.commit()


async def load_library_chat(
    session: AsyncSession,
    persona_id: str,
    mode: str,
) -> list[PersonaMessage]:
    removed = await trim_library_chat(session, persona_id, mode)
    result = await session.execute(
        select(PersonaMessage)
        .where(
            PersonaMessage.persona_id == persona_id,
            PersonaMessage.mode == mode,
            PersonaMessage.run_id.is_(None),
        )
        .order_by(PersonaMessage.id.asc())
    )
    rows = list(result.scalars().all())
    if removed:
        await session.commit()
    return rows
