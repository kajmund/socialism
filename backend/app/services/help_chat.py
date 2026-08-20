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
from app.llm.tool_messages import assistant_message_dict, tool_result_message
from app.schemas.domain import HelpChatResponse, HelpMessageOut, HelpViewContext
from app.serializers import format_date
from app.services.feedback_tools import help_feedback_tool_specs, run_feedback_tool
from app.services.help_read_context import build_help_context
from app.services.prompt_catalog import ConfigurationLanguage, default_prompts, render_prompt
from app.services.scb_tools import help_scb_tool_specs, run_scb_tool

_FEEDBACK_TOOL_NAMES = frozenset({"feedback_create", "feedback_list", "feedback_get"})
_SCB_TOOL_NAMES = frozenset(
    {
        "scb_search_tables",
        "scb_get_table_meta",
        "scb_query",
        "scb_population_dist",
    }
)

_MAX_TOOL_ROUNDS = 5

# Model sometimes dumps fake tool XML / protocol markup into assistant content.
_LEAKED_TOOL_MARKERS = (
    "DSML",
    "<invoke",
    "</invoke>",
    "<tool_call",
    "</tool_call>",
    "tool_calls",
    "｜DSML｜",
)


class ChatTurnError(Exception):
    def __init__(self, detail: str, *, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def looks_like_leaked_tool_markup(text: str) -> bool:
    """True when content looks like protocol/tool XML rather than a user-facing reply."""
    if not text or not text.strip():
        return False
    lowered = text.lower()
    for marker in _LEAKED_TOOL_MARKERS:
        if marker.lower() in lowered:
            return True
    return False


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
    ground_population: bool = False,
) -> str:
    del ground_population  # legacy WS/REST flag; SCB dist is always available
    prompts = default_prompts(locale)
    parts = [
        render_prompt(prompts, "help.system"),
        render_prompt(prompts, "help.system.scb"),
        render_prompt(prompts, "help.system.feedback"),
    ]
    context = await build_help_context(session, view=view, query=query)
    parts.append(context)
    return "\n\n".join(parts)


def _history_rows(rows: list[HelpMessage]) -> list[dict[str, str]]:
    return [{"role": row.role, "content": row.content} for row in rows]


async def _run_help_tool_loop(
    session: AsyncSession,
    messages: list[dict[str, object]],
    *,
    help_session_id: str,
    view: HelpViewContext | None,
) -> list[dict[str, object]]:
    tools = [*help_scb_tool_specs(), *help_feedback_tool_specs()]
    view_path = view.path if view is not None else None
    working = list(messages)
    for _ in range(_MAX_TOOL_ROUNDS):
        message = await complete_with_tools(working, tools)
        working.append(assistant_message_dict(message))
        tool_calls = getattr(message, "tool_calls", None)
        if not tool_calls:
            return working
        for call in tool_calls:
            name = call.function.name
            raw_args = call.function.arguments or "{}"
            if isinstance(raw_args, dict):
                arguments = raw_args
            else:
                try:
                    arguments = json.loads(raw_args)
                except (json.JSONDecodeError, TypeError):
                    arguments = {}
            try:
                if name in _FEEDBACK_TOOL_NAMES:
                    result = await run_feedback_tool(
                        session,
                        name,
                        arguments,
                        help_session_id=help_session_id,
                        view_path=view_path,
                    )
                elif name in _SCB_TOOL_NAMES:
                    result = await run_scb_tool(name, arguments)
                else:
                    result = f"Unknown tool: {name}"
            except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                result = f"Tool error ({name}): {exc}"
            working.append(
                tool_result_message(tool_call_id=call.id, content=result, name=name)
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
    ground_population: bool = False,
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
            ground_population=ground_population,
        )
        messages = [
            {"role": "system", "content": system_prompt},
            *_history_rows(prior),
            {"role": "user", "content": message},
        ]

        working = await _run_help_tool_loop(
            session,
            messages,
            help_session_id=session_id,
            view=view,
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
            raise ChatTurnError("Help chat produced an empty reply")
        if looks_like_leaked_tool_markup(reply):
            raise ChatTurnError(
                "Help chat produced an invalid reply (tool protocol leaked into text)"
            )

        assistant_row = HelpMessage(session_id=session_id, role="assistant", content=reply)
        session.add(assistant_row)
        await session.commit()
        await session.refresh(assistant_row)

        all_rows = prior + [user_row, assistant_row]
        yield HelpChatResponse(
            reply=reply,
            messages=[serialize_help_message(row) for row in all_rows],
        )
