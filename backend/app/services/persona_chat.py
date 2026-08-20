"""Shared library + run-interview chat turns (REST and WebSocket)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Persona, PersonaMessage, Run
from app.llm.chat import (
    build_run_interview_prompt,
    stream_reply_as_persona,
    suggest_follow_up_questions,
)
from app.schemas.domain import (
    ChatMode,
    EditablePersona,
    PersonaChatResponse,
    PersonaMessageOut,
)
from app.serializers import format_date, profile_from_dict, utcnow
from app.services.district_context import area_block_for_name
from app.services.oasis_run import previous_attempts
from app.services.prompt_store import require_active_prompts
from app.services.run_tick_context import build_persona_feed_context

logger = logging.getLogger(__name__)


class ChatTurnError(Exception):
    def __init__(self, detail: str, *, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class ChatSuggestions:
    questions: list[str]


_chat_locks: dict[str, asyncio.Lock] = {}
_chat_locks_guard = asyncio.Lock()


async def _chat_turn_lock(key: str) -> asyncio.Lock:
    async with _chat_locks_guard:
        lock = _chat_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _chat_locks[key] = lock
        return lock


def _library_lock_key(persona_id: str, mode: ChatMode) -> str:
    return f"library:{persona_id}:{mode}"


def _interview_lock_key(
    *,
    persona_id: str,
    run_id: int,
    attempt_id: str,
    variant_id: str,
    through_tick_index: int,
) -> str:
    return (
        f"interview:{persona_id}:{run_id}:{attempt_id}:"
        f"{variant_id}:{through_tick_index}"
    )


def serialize_persona_message(row: PersonaMessage) -> PersonaMessageOut:
    asked_by = row.asked_by if row.asked_by in {"doctor", "human"} else None
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
        asked_by=asked_by,  # type: ignore[arg-type]
    )


def library_chat_filter(persona_id: str, mode: ChatMode):
    return (
        PersonaMessage.persona_id == persona_id,
        PersonaMessage.mode == mode,
        PersonaMessage.run_id.is_(None),
    )


def run_interview_filter(
    *,
    persona_id: str,
    run_id: int,
    attempt_id: str,
    variant_id: str,
    through_tick_index: int,
):
    return (
        PersonaMessage.persona_id == persona_id,
        PersonaMessage.mode == "interview",
        PersonaMessage.run_id == run_id,
        PersonaMessage.attempt_id == attempt_id,
        PersonaMessage.variant_id == variant_id,
        PersonaMessage.through_tick_index == through_tick_index,
    )


def _find_attempt_variant(
    results: dict[str, Any] | None,
    attempt_id: str,
    variant_id: str,
) -> dict[str, Any]:
    attempts = previous_attempts(results)
    attempt = next((a for a in attempts if a.get("id") == attempt_id), None)
    if attempt is None and attempt_id == "legacy" and results:
        variants = results.get("variants") or []
        for variant in variants:
            if variant.get("id") == variant_id:
                return variant
        if results.get("posts") is not None or results.get("agents") is not None:
            if variant_id == "main":
                return {
                    "id": "main",
                    "agents": results.get("agents") or [],
                    "posts": results.get("posts") or [],
                    "comments": results.get("comments") or [],
                    "trace": results.get("trace") or [],
                    "tick_markers": results.get("tick_markers") or [],
                    "ticks_run": results.get("ticks_run"),
                }
    if attempt is None:
        raise ChatTurnError("Result attempt not found", status_code=404)
    for variant in attempt.get("variants") or []:
        if variant.get("id") == variant_id:
            return variant
    raise ChatTurnError("Result variant not found", status_code=404)


def validate_interview_variant(
    run: Run,
    variant: dict[str, Any],
    *,
    persona_id: str,
    through_tick_index: int,
) -> None:
    if run.status == "running":
        raise ChatTurnError(
            "Cannot interview while the run is simulating",
            status_code=409,
        )
    markers = variant.get("tick_markers") or []
    ticks_run = int(variant.get("ticks_run") or 0)
    if through_tick_index < 0 or through_tick_index >= len(markers):
        raise ChatTurnError("through_tick_index out of range")
    if ticks_run > 0 and through_tick_index > ticks_run - 1:
        raise ChatTurnError("through_tick_index beyond ticks_run")
    agents = variant.get("agents") or []
    if not any(
        a.get("persona_id") == persona_id and a.get("role") != "injector"
        for a in agents
    ):
        raise ChatTurnError(
            "Persona not found in this simulation variant",
            status_code=404,
        )


async def stream_library_chat_turn(
    session: AsyncSession,
    *,
    persona_id: str,
    mode: ChatMode,
    message: str,
) -> AsyncIterator[str | PersonaChatResponse | ChatSuggestions]:
    """Yield token strings, then PersonaChatResponse, then follow-up chips."""
    lock = await _chat_turn_lock(_library_lock_key(persona_id, mode))
    async with lock:
        persona = await session.get(Persona, persona_id)
        if persona is None:
            raise ChatTurnError("Persona not found", status_code=404)

        profile = profile_from_dict(persona.profile, persona.name)
        history_rows = await session.execute(
            select(PersonaMessage)
            .where(*library_chat_filter(persona_id, mode))
            .order_by(PersonaMessage.id.asc())
        )
        history = [(row.role, row.content) for row in history_rows.scalars().all()]
        area_block = await area_block_for_name(session, profile.ort or persona.district)
        prompts = await require_active_prompts(session)

        user_row = PersonaMessage(
            persona_id=persona_id,
            mode=mode,
            role="user",
            content=message,
            created_at=utcnow(),
        )
        session.add(user_row)
        await session.commit()

        parts: list[str] = []
        async for chunk in stream_reply_as_persona(
            profile,
            mode,
            history,
            message,
            prompts=prompts,
            area_block=area_block,
        ):
            parts.append(chunk)
            yield chunk

        reply = "".join(parts).strip()
        if not reply:
            raise ChatTurnError("Empty reply from model", status_code=502)

        assistant_row = PersonaMessage(
            persona_id=persona_id,
            mode=mode,
            role="assistant",
            content=reply,
            created_at=utcnow(),
        )
        session.add(assistant_row)
        await session.commit()

        all_rows = await session.execute(
            select(PersonaMessage)
            .where(*library_chat_filter(persona_id, mode))
            .order_by(PersonaMessage.id.asc())
        )
        messages = [serialize_persona_message(row) for row in all_rows.scalars().all()]
        yield PersonaChatResponse(reply=reply, messages=messages)
        yield ChatSuggestions(
            questions=await safe_library_follow_ups(
                profile,
                mode,
                [(row.role, row.content) for row in messages],
                prompts=prompts,
            )
        )


async def stream_run_interview_turn(
    session: AsyncSession,
    *,
    run_id: int,
    attempt_id: str,
    variant_id: str,
    persona_id: str,
    through_tick_index: int,
    message: str,
    asked_by: Literal["doctor", "human"] = "human",
) -> AsyncIterator[str | PersonaChatResponse]:
    lock = await _chat_turn_lock(
        _interview_lock_key(
            persona_id=persona_id,
            run_id=run_id,
            attempt_id=attempt_id,
            variant_id=variant_id,
            through_tick_index=through_tick_index,
        )
    )
    async with lock:
        run = await session.get(Run, run_id)
        if run is None:
            raise ChatTurnError("Run not found", status_code=404)
        persona = await session.get(Persona, persona_id)
        if persona is None:
            raise ChatTurnError("Persona not found", status_code=404)

        variant = _find_attempt_variant(
            run.results if isinstance(run.results, dict) else None,
            attempt_id,
            variant_id,
        )
        validate_interview_variant(
            run,
            variant,
            persona_id=persona_id,
            through_tick_index=through_tick_index,
        )

        try:
            feed_context, meta = build_persona_feed_context(
                variant,
                persona_id=persona_id,
                through_tick_index=through_tick_index,
            )
        except ValueError as exc:
            raise ChatTurnError(str(exc)) from exc

        profile = profile_from_dict(persona.profile, persona.name)
        area_block = await area_block_for_name(session, profile.ort or persona.district)
        prompts = await require_active_prompts(session)
        system_prompt = build_run_interview_prompt(
            profile,
            feed_context,
            prompts=prompts,
            day=int(meta["day"]),
            tick_index=int(meta["tick_index"]),
            area_block=area_block,
        )

        history_rows = await session.execute(
            select(PersonaMessage)
            .where(
                *run_interview_filter(
                    persona_id=persona_id,
                    run_id=run_id,
                    attempt_id=attempt_id,
                    variant_id=variant_id,
                    through_tick_index=through_tick_index,
                )
            )
            .order_by(PersonaMessage.id.asc())
        )
        history = [(row.role, row.content) for row in history_rows.scalars().all()]

        user_row = PersonaMessage(
            persona_id=persona_id,
            mode="interview",
            role="user",
            content=message,
            created_at=utcnow(),
            run_id=run_id,
            attempt_id=attempt_id,
            variant_id=variant_id,
            through_tick_index=through_tick_index,
            asked_by=asked_by,
        )
        session.add(user_row)
        await session.commit()

        parts: list[str] = []
        async for chunk in stream_reply_as_persona(
            profile,
            "interview",
            history,
            message,
            prompts=prompts,
            system_prompt=system_prompt,
        ):
            parts.append(chunk)
            yield chunk

        reply = "".join(parts).strip()
        if not reply:
            raise ChatTurnError("Empty reply from model", status_code=502)

        assistant_row = PersonaMessage(
            persona_id=persona_id,
            mode="interview",
            role="assistant",
            content=reply,
            created_at=utcnow(),
            run_id=run_id,
            attempt_id=attempt_id,
            variant_id=variant_id,
            through_tick_index=through_tick_index,
        )
        session.add(assistant_row)
        await session.commit()

        all_rows = await session.execute(
            select(PersonaMessage)
            .where(
                *run_interview_filter(
                    persona_id=persona_id,
                    run_id=run_id,
                    attempt_id=attempt_id,
                    variant_id=variant_id,
                    through_tick_index=through_tick_index,
                )
            )
            .order_by(PersonaMessage.id.asc())
        )
        messages = [serialize_persona_message(row) for row in all_rows.scalars().all()]
        yield PersonaChatResponse(reply=reply, messages=messages)


async def complete_run_interview_turn(
    session: AsyncSession,
    *,
    run_id: int,
    attempt_id: str,
    variant_id: str,
    persona_id: str,
    through_tick_index: int,
    message: str,
    asked_by: Literal["doctor", "human"] = "human",
) -> PersonaChatResponse:
    """Run one interview turn to completion (used by Spinndoktor MCP tools)."""
    done: PersonaChatResponse | None = None
    async for item in stream_run_interview_turn(
        session,
        run_id=run_id,
        attempt_id=attempt_id,
        variant_id=variant_id,
        persona_id=persona_id,
        through_tick_index=through_tick_index,
        message=message,
        asked_by=asked_by,
    ):
        if isinstance(item, PersonaChatResponse):
            done = item
    if done is None:
        raise ChatTurnError("Interview turn produced no reply", status_code=502)
    return done


async def library_follow_up_questions(
    session: AsyncSession,
    *,
    persona_id: str,
    mode: ChatMode,
) -> list[str]:
    """Generate follow-up chips from the current library thread. Fails loud."""
    persona = await session.get(Persona, persona_id)
    if persona is None:
        raise ChatTurnError("Persona not found", status_code=404)
    profile = profile_from_dict(persona.profile, persona.name)
    history_rows = await session.execute(
        select(PersonaMessage)
        .where(*library_chat_filter(persona_id, mode))
        .order_by(PersonaMessage.id.asc())
    )
    history = [(row.role, row.content) for row in history_rows.scalars().all()]
    prompts = await require_active_prompts(session)
    return await suggest_follow_up_questions(
        profile,
        mode,
        history,
        prompts=prompts,
    )


async def safe_library_follow_ups(
    profile: EditablePersona,
    mode: ChatMode,
    history: list[tuple[str, str]],
    *,
    prompts: dict[str, str],
) -> list[str]:
    """After a successful reply, omit chips rather than failing the turn."""
    try:
        return await suggest_follow_up_questions(
            profile,
            mode,
            history,
            prompts=prompts,
        )
    except Exception:
        logger.exception("Follow-up suggestion generation failed")
        return []
