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
from app.services.expertgranskning.memory import get_expert_memory
from app.services.panel.competency import assess_expert_competency
from app.services.panel.expert_slots import profile_text_for_expert
from app.services.panel.schemas import PanelExpertSlot, PanelSessionConfig
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


def _slot(persona: Persona) -> PanelExpertSlot:
    return PanelExpertSlot(
        slot_id=persona.id,
        label=persona.name,
        profile=profile_text_for_expert(persona),
        tools=[],
    )


def _config(question: str, slots: list[PanelExpertSlot]) -> PanelSessionConfig:
    return PanelSessionConfig(
        protocol="generic_panel",
        module="dd",
        topic=question,
        brief=question,
        locale="sv",
        expert_slots=slots,
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
    asker_slot = _slot(asker)
    asker_decision = await assess_expert_competency(
        asker_slot,
        _config(question, [asker_slot]),
        prompts,
    )
    if asker_decision.has_domain_competence:
        raise ValueError("Du har själv kompetens att besvara frågan.")

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
    if not candidates:
        raise ValueError("Det finns ingen annan expert att fråga.")

    slots = [_slot(candidate) for candidate in candidates]
    config = _config(question, slots)
    decisions = await asyncio.gather(
        *(assess_expert_competency(slot, config, prompts) for slot in slots)
    )
    competent = [
        (candidate, decision)
        for candidate, decision in zip(candidates, decisions, strict=True)
        if decision.has_domain_competence
    ]
    if not competent:
        raise ValueError("Ingen annan expert har kompetens att besvara frågan.")
    colleague, _decision = max(
        competent,
        key=lambda pair: pair[1].competence_score,
    )

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
