"""Panel/LLM adapters for research-question expert assignment."""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Persona
from app.llm.expert_gen import llm_experts_from_underlag
from app.schemas.domain import EditablePersona
from app.serializers import persona_initials, slug_id, utcnow
from app.services.expert_tools import resolve_chat_tools
from app.services.panel.competency import assess_expert_competency
from app.services.panel.expert_slots import profile_text_for_expert
from app.services.panel.schemas import PanelExpertSlot, PanelSessionConfig
from app.services.research.question_expert_assignment import (
    ExpertAssignmentQuestion,
    ExpertCandidateIdentity,
)


class PanelCompetencyQuestionMatcher:
    """Rank all candidates with the panel's evidence-free competency gate."""

    def __init__(self, *, prompts: dict[str, str], locale: str = "sv") -> None:
        self._prompts = dict(prompts)
        self._locale = locale

    async def match_expert(
        self,
        *,
        question: ExpertAssignmentQuestion,
        candidates: tuple[ExpertCandidateIdentity, ...],
    ) -> str | None:
        async def assess(candidate: ExpertCandidateIdentity):
            slot = PanelExpertSlot(
                slot_id=candidate.expert_id,
                label=candidate.name,
                profile=candidate.profile,
            )
            config = PanelSessionConfig(
                protocol="generic_panel",
                module=question.module,
                topic=question.question,
                brief=question.why_needed,
                locale=self._locale,  # type: ignore[arg-type]
                expert_slots=[slot],
            )
            decision = await assess_expert_competency(slot, config, self._prompts)
            return candidate, decision

        assessed = await asyncio.gather(*(assess(candidate) for candidate in candidates))
        competent = [pair for pair in assessed if pair[1].has_domain_competence]
        if not competent:
            return None
        best, _decision = max(competent, key=lambda pair: pair[1].competence_score)
        return best.expert_id


class UnderlagExpertCreator:
    """Reuse the existing expert-profile generator and persist an expert Persona."""

    def __init__(self, *, prompts: dict[str, str], language: str = "sv") -> None:
        self._prompts = dict(prompts)
        self._language = language

    async def create_expert(
        self,
        session: AsyncSession,
        *,
        question: ExpertAssignmentQuestion,
    ) -> ExpertCandidateIdentity:
        source_text = question.question
        if question.why_needed:
            source_text = f"{source_text}\n\nVarför kompetensen behövs: {question.why_needed}"
        generated = await llm_experts_from_underlag(
            source_text,
            1,
            question.module,
            session,
            customer_id=question.customer_id,
            language=self._language,
            prompts=self._prompts,
        )
        candidate = generated[0]
        expert_id = slug_id(candidate.name)
        while await session.get(Persona, expert_id) is not None:
            expert_id = slug_id(candidate.name)
        profile = EditablePersona(
            name=candidate.name,
            initials=persona_initials(candidate.name),
            yrke=candidate.yrkesbakgrund,
            beskrivning=candidate.description,
            kompetensomrade=candidate.kompetensomrade,
            radgivningsstil=candidate.radgivningsstil,
            yrkesbakgrund=candidate.yrkesbakgrund,
            professionell_anekdot=candidate.professionell_anekdot,
        )
        persona = Persona(
            id=expert_id,
            customer_id=question.customer_id,
            kind="expert",
            name=candidate.name,
            age=None,
            occ=candidate.yrkesbakgrund or candidate.name,
            district="—",
            quote=candidate.description,
            origin="research_auto",
            profile=profile.model_dump(),
            tools=resolve_chat_tools(None, kind="expert"),
            updated_at=utcnow(),
        )
        session.add(persona)
        await session.flush()
        return ExpertCandidateIdentity(
            expert_id=persona.id,
            name=persona.name,
            profile=profile_text_for_expert(persona),
        )
