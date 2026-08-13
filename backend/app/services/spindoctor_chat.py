"""Spinndoktor chat turns (REST and WebSocket)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import SpindoctorMessage
from app.llm import stream_text
from app.schemas.domain import SpindoctorChatResponse, SpindoctorMessageOut
from app.serializers import format_date
from app.services.prompt_catalog import ConfigurationLanguage, render_prompt
from app.services.prompt_store import require_active_prompts
from app.services.spindoctor_context import build_spindoctor_context

_SPINNDOCTOR_LOCKS: dict[str, asyncio.Lock] = {}
_SPINNDOCTOR_LOCKS_GUARD = asyncio.Lock()


class SpindoctorChatTurnError(Exception):
    def __init__(self, detail: str, *, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


async def _spindoctor_turn_lock(report_id: str) -> asyncio.Lock:
    async with _SPINNDOCTOR_LOCKS_GUARD:
        lock = _SPINNDOCTOR_LOCKS.get(report_id)
        if lock is None:
            lock = asyncio.Lock()
            _SPINNDOCTOR_LOCKS[report_id] = lock
        return lock


def serialize_spindoctor_message(row: SpindoctorMessage) -> SpindoctorMessageOut:
    return SpindoctorMessageOut(
        id=row.id,
        role=row.role,  # type: ignore[arg-type]
        content=row.content,
        created_at=format_date(row.created_at) if row.created_at else "",
    )


async def list_spindoctor_messages(
    session: AsyncSession,
    report_id: str,
) -> list[SpindoctorMessageOut]:
    stmt = (
        select(SpindoctorMessage)
        .where(SpindoctorMessage.report_id == report_id)
        .order_by(SpindoctorMessage.id.asc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [serialize_spindoctor_message(row) for row in rows]


async def clear_spindoctor_messages(session: AsyncSession, report_id: str) -> None:
    await session.execute(
        delete(SpindoctorMessage).where(SpindoctorMessage.report_id == report_id)
    )
    await session.commit()


def _history_rows(rows: list[SpindoctorMessage]) -> list[dict[str, str]]:
    return [{"role": row.role, "content": row.content} for row in rows]


async def _build_system_prompt(
    session: AsyncSession,
    *,
    report_id: str,
    locale: ConfigurationLanguage,
) -> str:
    prompts = await require_active_prompts(session)
    _report, context = await build_spindoctor_context(session, report_id=report_id)
    parts = [
        render_prompt(prompts, "spinndoctor.system"),
        context,
    ]
    if locale == "en":
        parts.append("Answer in English unless the user writes in Swedish.")
    else:
        parts.append("Svara på svenska om användaren inte skriver på engelska.")
    return "\n\n".join(parts)


async def stream_spindoctor_chat_turn(
    session: AsyncSession,
    *,
    report_id: str,
    locale: ConfigurationLanguage,
    message: str,
) -> AsyncIterator[str | SpindoctorChatResponse]:
    lock = await _spindoctor_turn_lock(report_id)
    async with lock:
        try:
            await build_spindoctor_context(session, report_id=report_id)
        except ValueError as exc:
            raise SpindoctorChatTurnError(str(exc)) from exc

        stmt = (
            select(SpindoctorMessage)
            .where(SpindoctorMessage.report_id == report_id)
            .order_by(SpindoctorMessage.id.asc())
        )
        prior = list((await session.execute(stmt)).scalars().all())

        user_row = SpindoctorMessage(report_id=report_id, role="user", content=message)
        session.add(user_row)
        await session.commit()
        await session.refresh(user_row)

        system_prompt = await _build_system_prompt(
            session,
            report_id=report_id,
            locale=locale,
        )
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
            raise SpindoctorChatTurnError("Spinndoktor produced an empty reply")

        assistant_row = SpindoctorMessage(
            report_id=report_id,
            role="assistant",
            content=reply,
        )
        session.add(assistant_row)
        await session.commit()
        await session.refresh(assistant_row)

        all_rows = prior + [user_row, assistant_row]
        yield SpindoctorChatResponse(
            reply=reply,
            messages=[serialize_spindoctor_message(row) for row in all_rows],
        )
