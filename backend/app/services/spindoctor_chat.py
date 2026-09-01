"""Spinndoktor chat turns (REST and WebSocket)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Report, SpindoctorMessage
from app.llm import complete_with_tools, stream_text
from app.llm.tool_messages import assistant_message_dict, tool_result_message
from app.modules.registry import module_id_for_report_mode
from app.schemas.domain import (
    SpindoctorChatResponse,
    SpindoctorMessageOut,
    SpindoctorWidgetOut,
)
from app.serializers import format_date, utcnow
from app.services.help_chat import looks_like_leaked_tool_markup
from app.services.jobs import job_session_factory
from app.services.prompt_catalog import ConfigurationLanguage, render_prompt
from app.services.prompt_store import require_active_prompts
from app.services.panel.spinndoctor_profile import (
    render_spinndoctor_identity,
    require_spinndoctor_profile,
)
from app.services.spindoctor_context import build_spindoctor_context
from app.services.spindoctor_board import save_spindoctor_widget
from app.services.spindoctor_mcp_tools import (
    SpindoctorToolContext,
    make_report_snippet_widget,
    run_spindoctor_mcp_tool,
    spindoctor_mcp_tool_specs,
)
from app.services.spindoctor_refs import last_spindoctor_ref

_SPINNDOCTOR_LOCKS: dict[str, asyncio.Lock] = {}
_SPINNDOCTOR_LOCKS_GUARD = asyncio.Lock()
_MAX_TOOL_ROUNDS = 8


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


def _emit_text_chunks(text: str, *, chunk_size: int = 24) -> list[str]:
    if not text:
        return []
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


async def _run_spindoctor_tool_loop(
    session: AsyncSession,
    messages: list[dict[str, object]],
    *,
    ctx: SpindoctorToolContext,
) -> tuple[list[dict[str, object]], list[SpindoctorWidgetOut]]:
    if not ctx.module_id:
        raise ValueError("SpindoctorToolContext.module_id is required")
    tools = spindoctor_mcp_tool_specs(ctx.module_id)
    working = list(messages)
    emitted = len(ctx.widgets)
    new_widgets: list[SpindoctorWidgetOut] = []
    for _ in range(_MAX_TOOL_ROUNDS):
        message = await complete_with_tools(working, tools)
        working.append(assistant_message_dict(message))
        tool_calls = getattr(message, "tool_calls", None)
        if not tool_calls:
            break

        async def _run_tool_call(call: object) -> tuple[object, str, str]:
            name = call.function.name  # type: ignore[attr-defined]
            raw_args = call.function.arguments or "{}"  # type: ignore[attr-defined]
            if isinstance(raw_args, dict):
                arguments = raw_args
            else:
                try:
                    arguments = json.loads(raw_args)
                except (json.JSONDecodeError, TypeError):
                    arguments = {}
            try:
                factory = job_session_factory()
                async with factory() as tool_session:
                    result = await run_spindoctor_mcp_tool(
                        tool_session,
                        name,
                        arguments if isinstance(arguments, dict) else {},
                        ctx=ctx,
                    )
            except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                result = f"Tool error ({name}): {exc}"
            return call, result, name

        tool_results = await asyncio.gather(
            *[_run_tool_call(call) for call in tool_calls]
        )
        for call, result, name in tool_results:
            working.append(
                tool_result_message(tool_call_id=call.id, content=result, name=name)
            )
        while emitted < len(ctx.widgets):
            new_widgets.append(ctx.widgets[emitted])
            emitted += 1
    return working, new_widgets


async def _build_identity_prompt(
    session: AsyncSession,
    *,
    locale: ConfigurationLanguage,
) -> str:
    prompts = await require_active_prompts(session)
    row = await require_spinndoctor_profile(session)
    identity = render_spinndoctor_identity(prompts, row)
    parts = [
        identity,
        render_prompt(prompts, "spinndoctor.system"),
        render_prompt(prompts, "spinndoctor.system.tools"),
        render_prompt(prompts, "spinndoctor.system.widgets"),
    ]
    if locale == "en":
        parts.append("Answer in English unless the user writes in Swedish.")
    else:
        parts.append("Svara på svenska om användaren inte skriver på engelska.")
    return "\n\n".join(parts)


def assemble_spindoctor_messages(
    *,
    identity: str,
    context: str,
    history: list[dict[str, str]],
    user_message: str,
) -> list[dict[str, object]]:
    """Identity and report context are separate messages — not concatenated."""
    return [
        {"role": "system", "content": identity},
        {"role": "system", "content": context},
        *history,
        {"role": "user", "content": user_message},
    ]


def _section_title(section_id: str, *, locale: ConfigurationLanguage) -> str:
    titles_sv = {
        "mottagande": "Mottagande",
        "budskapsstilar": "Budskapsstilar",
        "amneskontroll": "Ämneskontroll",
        "opinionsledare": "Opinionsledare",
        "valjargrupper": "Väljargrupper",
        "rekommendation": "Rekommendation",
        "appendix": "Appendix",
        "sammanfattning": "Sammanfattning",
        "kandidat": "Kandidat",
        "delfragor": "Delfrågor",
        "poangmatris": "Poängmatris",
        "kallbilaga": "Källbilaga",
    }
    titles_en = {
        "mottagande": "Reception",
        "budskapsstilar": "Message styles",
        "amneskontroll": "Topic control",
        "opinionsledare": "Opinion leaders",
        "valjargrupper": "Voter groups",
        "rekommendation": "Recommendation",
        "appendix": "Appendix",
        "sammanfattning": "Summary",
        "kandidat": "Candidate",
        "delfragor": "Sub-questions",
        "poangmatris": "Score matrix",
        "kallbilaga": "Sources",
    }
    table = titles_en if locale == "en" else titles_sv
    return table.get(section_id, section_id)


async def stream_spindoctor_chat_turn(
    session: AsyncSession,
    *,
    report_id: str,
    locale: ConfigurationLanguage,
    message: str,
) -> AsyncIterator[str | SpindoctorWidgetOut | SpindoctorChatResponse]:
    lock = await _spindoctor_turn_lock(report_id)
    async with lock:
        try:
            _report, context = await build_spindoctor_context(session, report_id=report_id)
        except ValueError as exc:
            raise SpindoctorChatTurnError(str(exc)) from exc

        stmt = (
            select(SpindoctorMessage)
            .where(SpindoctorMessage.report_id == report_id)
            .order_by(SpindoctorMessage.id.asc())
        )
        prior = list((await session.execute(stmt)).scalars().all())

        question_sent_at = utcnow()
        report_row = await session.get(Report, report_id)
        module_id = module_id_for_report_mode(
            report_row.mode if report_row is not None else "quick"
        )
        ctx = SpindoctorToolContext(
            report_id=report_id,
            module_id=module_id,
            question_sent_at=question_sent_at,
        )

        user_row = SpindoctorMessage(report_id=report_id, role="user", content=message)
        session.add(user_row)
        await session.commit()
        await session.refresh(user_row)

        identity = await _build_identity_prompt(session, locale=locale)
        messages = assemble_spindoctor_messages(
            identity=identity,
            context=context,
            history=_history_rows(prior),
            user_message=message,
        )

        working, tool_widgets = await _run_spindoctor_tool_loop(
            session,
            messages,
            ctx=ctx,
        )
        for widget in tool_widgets:
            yield await save_spindoctor_widget(session, report_id, widget)

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

        section_ref = last_spindoctor_ref(reply)
        if section_ref:
            snippet = await make_report_snippet_widget(
                ctx,
                section_id=section_ref,
                title=_section_title(section_ref, locale=locale),
            )
            yield await save_spindoctor_widget(session, report_id, snippet)

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
