"""Spinndoktor chat turns (REST and WebSocket)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import SpindoctorMessage
from app.llm import complete_with_tools, stream_text
from app.schemas.domain import SpindoctorChatResponse, SpindoctorMessageOut
from app.serializers import format_date
from app.services.help_chat import looks_like_leaked_tool_markup
from app.services.prompt_catalog import ConfigurationLanguage, render_prompt
from app.services.prompt_store import require_active_prompts
from app.services.spindoctor_context import build_spindoctor_context
from app.services.spindoctor_tools import (
    SPINDOCTOR_TOOL_NAMES,
    run_spindoctor_tool,
    spindoctor_tool_specs,
)

_SPINNDOCTOR_LOCKS: dict[str, asyncio.Lock] = {}
_SPINNDOCTOR_LOCKS_GUARD = asyncio.Lock()
_MAX_TOOL_ROUNDS = 5


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
    lock = await _spindoctor_turn_lock(report_id)
    async with lock:
        await session.execute(
            delete(SpindoctorMessage).where(SpindoctorMessage.report_id == report_id)
        )
        await session.commit()


def _history_rows(rows: list[SpindoctorMessage]) -> list[dict[str, str]]:
    return [{"role": row.role, "content": row.content} for row in rows]


def _assistant_message_dict(message: object) -> dict[str, object]:
    tool_calls = getattr(message, "tool_calls", None)
    payload: dict[str, object] = {
        "role": "assistant",
        "content": getattr(message, "content", None) or "",
    }
    if tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                },
            }
            for call in tool_calls
        ]
    return payload


def _emit_text_chunks(text: str, *, chunk_size: int = 24) -> list[str]:
    if not text:
        return []
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


async def _run_spindoctor_tool_loop(
    session: AsyncSession,
    messages: list[dict[str, object]],
    *,
    report_id: str,
) -> list[dict[str, object]]:
    tools = spindoctor_tool_specs()
    working = list(messages)
    for _ in range(_MAX_TOOL_ROUNDS):
        message = await complete_with_tools(working, tools)
        working.append(_assistant_message_dict(message))
        tool_calls = getattr(message, "tool_calls", None)
        if not tool_calls:
            return working
        for call in tool_calls:
            name = call.function.name
            raw_args = call.function.arguments or "{}"
            try:
                arguments = json.loads(raw_args)
            except json.JSONDecodeError:
                arguments = {}
            try:
                if name in SPINDOCTOR_TOOL_NAMES:
                    result = await run_spindoctor_tool(
                        session,
                        name,
                        arguments if isinstance(arguments, dict) else {},
                        report_id=report_id,
                    )
                else:
                    result = f"Unknown tool: {name}"
            except ValueError as exc:
                result = f"Tool error ({name}): {exc}"
            working.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": result,
                }
            )
    return working


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
        render_prompt(prompts, "spinndoctor.system.tools"),
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

        working = await _run_spindoctor_tool_loop(
            session,
            messages,
            report_id=report_id,
        )
        last = working[-1]
        prebuilt_reply = ""
        if last.get("role") == "assistant" and last.get("content"):
            candidate = str(last["content"]).strip()
            if candidate and not looks_like_leaked_tool_markup(candidate):
                prebuilt_reply = candidate

        chunks: list[str] = []
        if prebuilt_reply:
            for piece in _emit_text_chunks(prebuilt_reply):
                chunks.append(piece)
                yield piece
        else:
            async for piece in stream_text(working):
                chunks.append(piece)
                yield piece
        reply = "".join(chunks).strip()
        if not reply:
            raise SpindoctorChatTurnError("Spinndoktor produced an empty reply")
        if looks_like_leaked_tool_markup(reply):
            raise SpindoctorChatTurnError(
                "Spinndoktor produced an invalid reply (tool protocol leaked into text)"
            )

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
