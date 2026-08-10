"""In-app help chat turns (REST and WebSocket)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import HelpMessage
from app.llm import complete_with_tools, stream_text
from app.schemas.domain import HelpChatResponse, HelpMessageOut, HelpViewContext
from app.serializers import format_date
from app.services.help_read_context import build_help_context
from app.services.prompt_catalog import ConfigurationLanguage, default_prompts, render_prompt
from app.services.scb_tools import SCB_TOOL_SPECS, run_scb_tool

_MAX_TOOL_ROUNDS = 5


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


async def _build_system_prompt(
    session: AsyncSession,
    *,
    locale: ConfigurationLanguage,
    query: str,
    view: HelpViewContext | None,
    use_scb: bool = False,
) -> str:
    prompts = default_prompts(locale)
    base = render_prompt(prompts, "help.system")
    if use_scb:
        base = f"{base}\n\n{render_prompt(prompts, 'help.system.scb')}"
    context = await build_help_context(session, view=view, query=query)
    return f"{base}\n\n{context}"


def _history_rows(rows: list[HelpMessage]) -> list[dict[str, str]]:
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


async def _run_scb_tool_loop(messages: list[dict[str, object]]) -> list[dict[str, object]]:
    working = list(messages)
    for _ in range(_MAX_TOOL_ROUNDS):
        message = await complete_with_tools(working, SCB_TOOL_SPECS)
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
                result = await run_scb_tool(name, arguments)
            except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                result = f"SCB tool error ({name}): {exc}"
            working.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": result,
                }
            )
    return working


def _emit_text_chunks(text: str, *, chunk_size: int = 24) -> list[str]:
    if not text:
        return []
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


async def stream_help_chat_turn(
    session: AsyncSession,
    *,
    session_id: str,
    locale: ConfigurationLanguage,
    message: str,
    view: HelpViewContext | None = None,
    use_scb: bool = False,
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

        system_prompt = await _build_system_prompt(
            session,
            locale=locale,
            query=message,
            view=view,
            use_scb=use_scb,
        )
        messages = [
            {"role": "system", "content": system_prompt},
            *_history_rows(prior),
            {"role": "user", "content": message},
        ]

        working = await _run_scb_tool_loop(messages) if use_scb else messages
        last = working[-1]
        prebuilt_reply = ""
        if last.get("role") == "assistant" and last.get("content"):
            prebuilt_reply = str(last["content"]).strip()

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
