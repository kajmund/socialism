"""In-app help chat turns (REST and WebSocket)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import HelpMessage
from app.llm import stream_text
from app.schemas.domain import HelpChatResponse, HelpMessageOut
from app.serializers import format_date
from app.services.okf_corpus import manual_context
from app.services.prompt_catalog import ConfigurationLanguage, default_prompts, render_prompt


class ChatTurnError(Exception):
    def __init__(self, detail: str, *, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


_help_locks: dict[str, asyncio.Lock] = {}
_help_locks_guard = asyncio.Lock()


async def _help_turn_lock(session_id: str) -> asyncio.Lock:
    async with _help_locks_guard:
        lock = _help_locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            _help_locks[session_id] = lock
        return lock


def serialize_help_message(row: HelpMessage) -> HelpMessageOut:
    return HelpMessageOut(
        id=row.id,
        role=row.role,  # type: ignore[arg-type]
        content=row.content,
        created_at=format_date(row.created_at) if row.created_at else "",
    )


async def list_help_messages(session: AsyncSession, session_id: str) -> list[HelpMessageOut]:
    stmt = (
        select(HelpMessage)
        .where(HelpMessage.session_id == session_id)
        .order_by(HelpMessage.id.asc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [serialize_help_message(row) for row in rows]


async def clear_help_messages(session: AsyncSession, session_id: str) -> None:
    await session.execute(delete(HelpMessage).where(HelpMessage.session_id == session_id))
    await session.commit()


def _build_system_prompt(*, locale: ConfigurationLanguage, query: str) -> str:
    prompts = default_prompts(locale)
    base = render_prompt(prompts, "help.system")
    context = manual_context(query)
    return f"{base}\n\n# Manual (OKF)\n\n{context}"


def _history_rows(rows: list[HelpMessage]) -> list[dict[str, str]]:
    return [{"role": row.role, "content": row.content} for row in rows]


async def stream_help_chat_turn(
    session: AsyncSession,
    *,
    session_id: str,
    locale: ConfigurationLanguage,
    message: str,
) -> AsyncIterator[str | HelpChatResponse]:
    lock = await _help_turn_lock(session_id)
    async with lock:
        stmt = (
            select(HelpMessage)
            .where(HelpMessage.session_id == session_id)
            .order_by(HelpMessage.id.asc())
        )
        prior = list((await session.execute(stmt)).scalars().all())

        user_row = HelpMessage(session_id=session_id, role="user", content=message)
        session.add(user_row)
        await session.commit()
        await session.refresh(user_row)

        system_prompt = _build_system_prompt(locale=locale, query=message)
        messages = [
            {"role": "system", "content": system_prompt},
            *_history_rows(prior),
            {"role": "user", "content": message},
        ]

        chunks: list[str] = []
        async for piece in stream_text(messages):
            chunks.append(piece)
            yield piece
        reply = "".join(chunks).strip()
        if not reply:
            raise ChatTurnError("Help chat produced an empty reply")

        assistant_row = HelpMessage(session_id=session_id, role="assistant", content=reply)
        session.add(assistant_row)
        await session.commit()
        await session.refresh(assistant_row)

        all_rows = prior + [user_row, assistant_row]
        yield HelpChatResponse(
            reply=reply,
            messages=[serialize_help_message(row) for row in all_rows],
        )
