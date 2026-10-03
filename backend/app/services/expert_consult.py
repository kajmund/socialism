"""One-hop consultation between experts in library chat."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Persona, PersonaMessage
from app.llm.chat import reply_as_persona
from app.realtime.library_chat_broadcast import library_chat_broadcast
from app.schemas.domain import ChatMode
from app.serializers import format_date, profile_from_dict, utcnow
from app.services.dd.expert_keys import persona_catalog_key
from app.services.expert_chat_evidence import (
    combine_expert_chat_context,
    reusable_expert_chat_evidence_context,
)
from app.services.consult_competence import (
    COMPETENCE_NOUL_THRESHOLD,
    rank_consult_competence,
)
from app.services.expert_tools import resolve_chat_tools
from app.services.library_chat_fifo import trim_library_chat
from app.services.expertgranskning.memory import get_expert_memory
from app.services.panel.expert_slots import profile_text_for_expert
from app.services.prompt_catalog import render_prompt

ConsultToolHandler = Callable[[dict[str, Any]], Awaitable[str]]

_MEMORY_SOURCES = frozenset(
    {
        "persona_chat",
        "panel_chat",
        "expert_consult",
        "intent_interview",
        "word_findings",
        "research_receipt",
    }
)


async def _memory_context(
    persona: Persona,
    question: str,
    prompts: dict[str, str],
) -> str:
    hits = await get_expert_memory().search(
        customer_id=persona.customer_id,
        expert_id=persona_catalog_key(persona),
        query=question,
        sources=_MEMORY_SOURCES,
    )
    if not hits:
        return ""
    memories = "\n".join(f"- {hit.text}" for hit in hits)
    return render_prompt(prompts, "chat.expert.memory", memories=memories)


def _serialized_message(row: PersonaMessage) -> dict[str, Any]:
    return {
        "id": row.id,
        "mode": row.mode,
        "role": row.role,
        "content": row.content,
        "created_at": format_date(row.created_at) if row.created_at else "",
        "run_id": None,
        "attempt_id": None,
        "variant_id": None,
        "through_tick_index": None,
        "asked_by": None,
        "image_sha256": None,
    }


async def _remember_consult(
    asker: Persona,
    colleague: Persona,
    *,
    question: str,
    answer: str,
) -> None:
    memory = get_expert_memory()
    await asyncio.gather(
        memory.add_chat_turn(
            customer_id=asker.customer_id,
            expert_id=persona_catalog_key(asker),
            user_message=(
                f"Jag frågade {colleague.name} om följande: {question}"
            ),
            assistant_message=answer,
            source="expert_consult",
        ),
        memory.add_chat_turn(
            customer_id=colleague.customer_id,
            expert_id=persona_catalog_key(colleague),
            user_message=f"{asker.name} frågade mig följande: {question}",
            assistant_message=answer,
            source="expert_consult",
        ),
    )


async def _consult(
    session: AsyncSession,
    *,
    asker: Persona,
    mode: ChatMode,
    prompts: dict[str, str],
    question: str,
) -> str:
    candidates = list(
        (
            await session.execute(
                select(Persona)
                .where(
                    Persona.customer_id == asker.customer_id,
                    Persona.kind == "expert",
                    Persona.id != asker.id,
                )
                .order_by(Persona.name.asc())
            )
        ).scalars()
    )
    ranked = [
        (persona.id, profile_text_for_expert(persona))
        for persona in (asker, *candidates)
    ]
    await session.commit()
    scores = await rank_consult_competence(question=question, experts=ranked)
    if scores[asker.id] >= COMPETENCE_NOUL_THRESHOLD:
        raise ValueError("Du har själv kompetens att besvara frågan.")
    if not candidates:
        raise ValueError("Det finns ingen annan expert att fråga.")
    competent = [
        (candidate, scores[candidate.id])
        for candidate in candidates
        if scores[candidate.id] >= COMPETENCE_NOUL_THRESHOLD
    ]
    if not competent:
        raise ValueError("Ingen annan expert har kompetens att besvara frågan.")
    colleague = max(competent, key=lambda pair: pair[1])[0]

    memory_context, evidence_context = await asyncio.gather(
        _memory_context(colleague, question, prompts),
        reusable_expert_chat_evidence_context(
            session,
            customer_id=colleague.customer_id,
            question=question,
            prompts=prompts,
        ),
    )
    colleague_instruction = render_prompt(
        prompts,
        "chat.expert.consult_colleague",
        asker_name=asker.name,
        question=question,
    )
    context = combine_expert_chat_context(memory_context, evidence_context)
    extra_system = "\n\n".join(
        part for part in (context, colleague_instruction) if part
    )
    answer = await reply_as_persona(
        profile_from_dict(colleague.profile, colleague.name),
        mode,
        [],
        question,
        prompts=prompts,
        profile_kind="expert",
        tools=[],
        extra_system=extra_system,
    )
    announcement = render_prompt(
        prompts,
        "chat.expert.consult_announce",
        asker_name=asker.name,
        question=question,
        answer=answer,
    )
    row = PersonaMessage(
        persona_id=colleague.id,
        mode=mode,
        role="assistant",
        content=announcement,
        created_at=utcnow(),
    )
    session.add(row)
    await trim_library_chat(session, colleague.id, mode)
    await session.commit()
    await session.refresh(row)
    await _remember_consult(
        asker,
        colleague,
        question=question,
        answer=answer,
    )

    rows = list(
        (
            await session.execute(
                select(PersonaMessage)
                .where(
                    PersonaMessage.persona_id == colleague.id,
                    PersonaMessage.mode == mode,
                    PersonaMessage.run_id.is_(None),
                )
                .order_by(PersonaMessage.id.asc())
            )
        ).scalars()
    )
    await library_chat_broadcast.publish(
        colleague.customer_id,
        colleague.id,
        {
            "type": "thread.message",
            "thread_type": "expert",
            "thread_id": colleague.id,
            "messages": [_serialized_message(message) for message in rows],
        },
    )
    await library_chat_broadcast.publish(
        asker.customer_id,
        asker.id,
        {
            "type": "consult.answered",
            "thread_type": "expert",
            "thread_id": asker.id,
            "colleague_id": colleague.id,
            "colleague_name": colleague.name,
        },
    )
    return json.dumps(
        {
            "colleague_id": colleague.id,
            "colleague_name": colleague.name,
            "question": question,
            "answer": answer,
            "instruction": render_prompt(
                prompts,
                "chat.expert.consult_inject",
                colleague_name=colleague.name,
            ),
        },
        ensure_ascii=False,
    )


def expert_consult_handler_for_chat(
    session: AsyncSession,
    *,
    asker: Persona,
    mode: ChatMode,
    prompts: dict[str, str],
) -> ConsultToolHandler:
    async def handle(arguments: dict[str, Any]) -> str:
        question = str(arguments.get("question") or "").strip()
        if not question:
            raise ValueError("ask_expert kräver en fråga.")
        return await _consult(
            session,
            asker=asker,
            mode=mode,
            prompts=prompts,
            question=question,
        )

    return handle


def consult_handler_for_persona(
    session: AsyncSession,
    *,
    persona: Persona,
    mode: ChatMode,
    prompts: dict[str, str],
) -> ConsultToolHandler | None:
    tools = resolve_chat_tools(persona.tools, kind=persona.kind)
    if persona.kind != "expert" or "ask_expert" not in tools:
        return None
    return expert_consult_handler_for_chat(
        session,
        asker=persona,
        mode=mode,
        prompts=prompts,
    )
