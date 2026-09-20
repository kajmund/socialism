"""Shared library + run-interview chat turns (REST and WebSocket)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Literal

from openai import APITimeoutError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import Persona, PersonaMessage, Run
from app.llm.chat import (
    build_run_interview_prompt,
    stream_reply_as_persona,
    suggest_follow_up_questions,
)
from app.llm.vision_content import validate_chat_turn_images
from app.realtime.interview_broadcast import interview_broadcast, interview_key_tuple
from app.schemas.domain import (
    ChatMode,
    EditablePersona,
    ExpertMemoryOut,
    PersonaChatResponse,
    PersonaMessageOut,
)
from app.serializers import format_date, profile_from_dict, utcnow
from app.services.dd.company_mcp import CompanyMcpError
from app.services.dd.expert_keys import persona_catalog_key
from app.services.district_context import area_block_for_name
from app.services.expert_chat_evidence import (
    combine_expert_chat_context,
    reusable_expert_chat_evidence_context,
)
from app.services.expert_chat_research_tool import research_tool_handler_for_chat
from app.services.expert_tools import resolve_chat_tools
from app.services.expertgranskning.memory import ExpertMemoryHit, get_expert_memory
from app.services.expertgranskning.memory_view import serialize_memory_hit
from app.services.oasis_run import previous_attempts
from app.services.prompt_catalog import render_prompt
from app.services.prompt_store import require_prompts_for_persona
from app.services.run_tick_context import build_persona_feed_context

logger = logging.getLogger(__name__)

LibraryTurnWriteGuard = Callable[[AsyncSession], Awaitable[bool]]


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
_LIBRARY_LOCK_WAIT_SECONDS = 30.0
_follow_up_tasks: dict[str, asyncio.Task[list[str]]] = {}
_follow_up_tasks_guard = asyncio.Lock()


async def _chat_turn_lock(key: str) -> asyncio.Lock:
    async with _chat_locks_guard:
        lock = _chat_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _chat_locks[key] = lock
        return lock


@asynccontextmanager
async def _library_chat_lock(persona_id: str, mode: ChatMode):
    lock = await _chat_turn_lock(_library_lock_key(persona_id, mode))
    try:
        await asyncio.wait_for(lock.acquire(), timeout=_LIBRARY_LOCK_WAIT_SECONDS)
    except TimeoutError as exc:
        raise ChatTurnError(
            "Previous chat turn still running; wait a moment and try again",
            status_code=409,
        ) from exc
    try:
        yield
    finally:
        lock.release()


def _llm_reply_timeout_seconds(*, with_tools: bool) -> float:
    base = settings.llm_timeout_seconds
    if with_tools:
        return base * 5
    return base + 15.0


def library_chat_tools(persona: Persona) -> list[str] | None:
    """Library interview/character chat uses tools only for experts."""
    if persona.kind != "expert":
        return None
    return persona.tools


def _library_chat_uses_tools(persona: Persona) -> bool:
    return bool(resolve_chat_tools(library_chat_tools(persona), kind=persona.kind))


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
    return f"interview:{persona_id}:{run_id}:{attempt_id}:{variant_id}:{through_tick_index}"


async def _publish_interview_message(row: PersonaMessage) -> None:
    if row.run_id is None or row.attempt_id is None or row.variant_id is None:
        return
    if row.through_tick_index is None:
        return
    key = interview_key_tuple(
        persona_id=row.persona_id,
        run_id=row.run_id,
        attempt_id=row.attempt_id,
        variant_id=row.variant_id,
        through_tick_index=row.through_tick_index,
    )
    await interview_broadcast.publish(
        key,
        serialize_persona_message(row).model_dump(mode="json"),
    )


async def _discard_user_message(session: AsyncSession, user_row: PersonaMessage) -> None:
    if user_row.id is None:
        return
    existing = await session.get(PersonaMessage, user_row.id)
    if existing is None:
        return
    await session.delete(existing)
    await session.commit()


async def _commit_library_message(
    session: AsyncSession,
    row: PersonaMessage,
    *,
    sme_expert_turn_request_id: str | None,
    persist_guard: LibraryTurnWriteGuard | None,
) -> None:
    if persist_guard is not None and not await persist_guard(session):
        raise ChatTurnError("stale_expert_turn", status_code=409)
    row.sme_expert_turn_request_id = sme_expert_turn_request_id
    session.add(row)
    await session.commit()


def _history_triples(rows: list[PersonaMessage]) -> list[tuple[str, str, str | None]]:
    return [(row.role, row.content, row.image_sha256) for row in rows]


async def expert_memory_context(
    persona: Persona,
    message: str,
    prompts: dict[str, str],
    *,
    image_sha256: str | None = None,
) -> str:
    if persona.kind != "expert":
        return ""
    hits = await get_expert_memory().search(
        customer_id=persona.customer_id,
        expert_id=persona_catalog_key(persona),
        query=message,
        image_sha256=image_sha256,
        sources=frozenset(
            {
                "persona_chat",
                "panel_chat",
                "intent_interview",
                "word_findings",
                "research_receipt",
            }
        ),
    )
    if not hits:
        return ""
    memories = "\n".join(_expert_memory_context_line(hit) for hit in hits)
    return render_prompt(prompts, "chat.expert.memory", memories=memories)


def _expert_memory_context_line(hit: ExpertMemoryHit) -> str:
    if hit.source != "research_receipt":
        return f"- {hit.text}"
    question_id = str(hit.metadata.get("knowledge_question_id") or "unknown")
    attempt_id = str(hit.metadata.get("source_attempt_id") or "unknown")
    return (
        "- [research_receipt; "
        f"knowledge_question_id={question_id}; source_attempt_id={attempt_id}] "
        f"{hit.text}"
    )


async def remember_expert_chat_turn(
    persona: Persona,
    *,
    message: str,
    reply: str,
    image_sha256: str | None,
    source: Literal["persona_chat", "panel_chat"] = "persona_chat",
    session_id: str | None = None,
) -> list[ExpertMemoryOut]:
    if persona.kind != "expert":
        return []
    hits = await get_expert_memory().add_chat_turn(
        customer_id=persona.customer_id,
        expert_id=persona_catalog_key(persona),
        user_message=message,
        assistant_message=reply,
        source=source,
        image_sha256=image_sha256,
        session_id=session_id,
    )
    return [
        serialize_memory_hit(
            hit,
            customer_id=persona.customer_id,
            expert_name=persona.name,
            persona_id=persona.id,
        )
        for hit in hits
    ]


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
        image_sha256=row.image_sha256,
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
        if (
            results.get("posts") is not None or results.get("agents") is not None
        ) and variant_id == "main":
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
    if not any(a.get("persona_id") == persona_id and a.get("role") != "injector" for a in agents):
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
    image_sha256: str | None = None,
    sme_expert_turn_request_id: str | None = None,
    actor_user_id: str | None = None,
    persist_guard: LibraryTurnWriteGuard | None = None,
) -> AsyncIterator[str | PersonaChatResponse]:
    """Yield token strings, then PersonaChatResponse.

    Follow-up chips are fetched separately (WebSocket sends them in the
    background) so a slow structured LLM call cannot block the next turn.
    """
    async with _library_chat_lock(persona_id, mode):
        persona = await session.get(Persona, persona_id)
        if persona is None:
            raise ChatTurnError("Persona not found", status_code=404)

        profile = profile_from_dict(persona.profile, persona.name)
        history_rows = await session.execute(
            select(PersonaMessage)
            .where(*library_chat_filter(persona_id, mode))
            .order_by(PersonaMessage.id.asc())
        )
        history_list = list(history_rows.scalars().all())
        history = _history_triples(history_list)
        area_block = await area_block_for_name(session, profile.ort or persona.district)
        prompts = await require_prompts_for_persona(session, persona)
        try:
            validate_chat_turn_images(history, message, image_sha256)
        except ValueError as exc:
            raise ChatTurnError(str(exc)) from exc
        memory_context = await expert_memory_context(
            persona, message, prompts, image_sha256=image_sha256
        )
        evidence_context = ""
        if persona.kind == "expert":
            evidence_context = await reusable_expert_chat_evidence_context(
                session,
                customer_id=persona.customer_id,
                question=message,
                prompts=prompts,
            )
        chat_tools = library_chat_tools(persona)
        with_tools = _library_chat_uses_tools(persona)
        research_tool_handler = None
        if persona.kind == "expert" and "start_research" in (chat_tools or []):
            research_tool_handler = research_tool_handler_for_chat(
                session,
                persona=persona,
                history=history,
                user_message=message,
            )

        user_row = PersonaMessage(
            persona_id=persona_id,
            mode=mode,
            role="user",
            content=message,
            image_sha256=image_sha256,
            created_at=utcnow(),
        )
        await _commit_library_message(
            session,
            user_row,
            sme_expert_turn_request_id=sme_expert_turn_request_id,
            persist_guard=persist_guard,
        )

        from app.services.actor_profiles import ActorProfileTools

        actor_handler = (
            ActorProfileTools(
                session,
                user_id=actor_user_id,
                customer_id=persona.customer_id,
                conversation=f"expert:{persona_id}:{mode}",
            )
            if actor_user_id and persona.kind == "expert"
            else None
        )
        parts: list[str] = []
        try:
            stream = stream_reply_as_persona(
                profile,
                mode,
                history,
                message,
                prompts=prompts,
                area_block=area_block,
                profile_kind=persona.kind,
                tools=chat_tools,
                extra_system=combine_expert_chat_context(memory_context, evidence_context),
                user_image_sha256=image_sha256,
                research_tool_handler=research_tool_handler,
                actor_tool_handler=actor_handler,
            )
            async with asyncio.timeout(_llm_reply_timeout_seconds(with_tools=with_tools)):
                async for chunk in stream:
                    parts.append(chunk)
                    yield chunk
        except (CompanyMcpError, ValueError) as exc:
            await _discard_user_message(session, user_row)
            status = 502 if isinstance(exc, CompanyMcpError) else 400
            raise ChatTurnError(str(exc), status_code=status) from exc
        except (TimeoutError, APITimeoutError) as exc:
            await _discard_user_message(session, user_row)
            raise ChatTurnError("LLM request timed out", status_code=504) from exc
        except asyncio.CancelledError:
            await _discard_user_message(session, user_row)
            raise
        except Exception:
            await _discard_user_message(session, user_row)
            raise

        reply = "".join(parts).strip()
        if not reply:
            await _discard_user_message(session, user_row)
            raise ChatTurnError("Empty reply from model", status_code=502)

        assistant_row = PersonaMessage(
            persona_id=persona_id,
            mode=mode,
            role="assistant",
            content=reply,
            created_at=utcnow(),
        )
        await _commit_library_message(
            session,
            assistant_row,
            sme_expert_turn_request_id=sme_expert_turn_request_id,
            persist_guard=persist_guard,
        )
        saved_memories = await remember_expert_chat_turn(
            persona,
            message=message,
            reply=reply,
            image_sha256=image_sha256,
        )

        all_rows = await session.execute(
            select(PersonaMessage)
            .where(*library_chat_filter(persona_id, mode))
            .order_by(PersonaMessage.id.asc())
        )
        messages = [serialize_persona_message(row) for row in all_rows.scalars().all()]
        yield PersonaChatResponse(
            reply=reply,
            messages=messages,
            saved_memories=saved_memories,
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
    image_sha256: str | None = None,
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
        prompts = await require_prompts_for_persona(session, persona)
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
        history_list = list(history_rows.scalars().all())
        history = _history_triples(history_list)

        try:
            validate_chat_turn_images(history, message, image_sha256)
        except ValueError as exc:
            raise ChatTurnError(str(exc)) from exc

        user_row = PersonaMessage(
            persona_id=persona_id,
            mode="interview",
            role="user",
            content=message,
            image_sha256=image_sha256,
            created_at=utcnow(),
            run_id=run_id,
            attempt_id=attempt_id,
            variant_id=variant_id,
            through_tick_index=through_tick_index,
            asked_by=asked_by,
        )
        session.add(user_row)
        await session.commit()
        await session.refresh(user_row)
        await _publish_interview_message(user_row)

        parts: list[str] = []
        try:
            async for chunk in stream_reply_as_persona(
                profile,
                "interview",
                history,
                message,
                prompts=prompts,
                system_prompt=system_prompt,
                profile_kind=persona.kind,
                tools=library_chat_tools(persona),
                user_image_sha256=image_sha256,
            ):
                parts.append(chunk)
                yield chunk
        except (CompanyMcpError, ValueError) as exc:
            await _discard_user_message(session, user_row)
            status = 502 if isinstance(exc, CompanyMcpError) else 400
            raise ChatTurnError(str(exc), status_code=status) from exc
        except asyncio.CancelledError:
            await _discard_user_message(session, user_row)
            raise
        except Exception:
            await _discard_user_message(session, user_row)
            raise

        reply = "".join(parts).strip()
        if not reply:
            await _discard_user_message(session, user_row)
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
        await session.refresh(assistant_row)
        await _publish_interview_message(assistant_row)

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
    image_sha256: str | None = None,
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
        image_sha256=image_sha256,
        asked_by=asked_by,
    ):
        if isinstance(item, PersonaChatResponse):
            done = item
    if done is None:
        raise ChatTurnError("Interview turn produced no reply", status_code=502)
    return done


def _follow_up_flight_key(persona_id: str, mode: ChatMode, history: list[tuple[str, str]]) -> str:
    last = history[-1] if history else ("", "")
    return f"{persona_id}:{mode}:{len(history)}:{last[0]}:{last[1]}"


async def library_follow_up_questions(
    session: AsyncSession,
    *,
    persona_id: str,
    mode: ChatMode,
) -> list[str]:
    """Follow-up chips for the library thread.

    Missing persona or active prompts still fail. LLM/parse errors omit chips
    (same as after a successful reply) so opening the composer is not a 500.
    Concurrent callers for the same thread share one LLM call so opening the
    composer cannot pile DeepSeek structured requests in front of the first turn.
    """
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
    prompts = await require_prompts_for_persona(session, persona)
    await session.commit()
    key = _follow_up_flight_key(persona_id, mode, history)
    async with _follow_up_tasks_guard:
        task = _follow_up_tasks.get(key)
        if task is None or task.done():
            task = asyncio.create_task(
                safe_library_follow_ups(
                    profile,
                    mode,
                    history,
                    prompts=prompts,
                )
            )
            _follow_up_tasks[key] = task
    try:
        return await task
    finally:
        async with _follow_up_tasks_guard:
            current = _follow_up_tasks.get(key)
            if current is task and task.done():
                del _follow_up_tasks[key]


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
