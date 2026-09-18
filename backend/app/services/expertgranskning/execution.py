"""Bridge Expertgranskning to expert-owned research questions and frozen evidence."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import PanelSession, Persona, ResearchQuestion
from app.services.execution.service import (
    add_evidence_items,
    attach_evidence_set,
    claim_freeze_evidence_set,
    create_attempt,
    create_evidence_set,
    create_run,
    get_attempt,
    list_evidence_items,
    mark_ready,
)
from app.services.execution.snapshots import EvidenceItemSnapshot
from app.services.panel.attempt_execution import execute_generic_panel_attempt
from app.services.panel.expert_slots import expert_slot_id_for_persona
from app.services.panel.question_expert_adapters import (
    PanelCompetencyQuestionMatcher,
    UnderlagExpertCreator,
)
from app.services.panel.research import (
    ResearchPlan,
    build_research_plan,
    collect_expert_research_needs,
)
from app.services.panel.schemas import PanelSessionConfig
from app.services.prompt_store import require_active_prompts
from app.services.research.composition import build_standard_research_router
from app.services.research.question_attempt_worker import AttemptResearchQuestionWorker
from app.services.research.question_domain import (
    GeneralQuestionDraft,
    create_general_question,
    create_specific_question,
)
from app.services.research.question_execution import execute_research_question_dag
from app.services.research.question_expert_assignment import (
    assign_unowned_research_questions,
)
from app.services.research_worker import bind_research_components

from . import MODULE_ID
from .sessions import document_text_from_config, review_intent_from_config


def _research_objective(config: PanelSessionConfig) -> str:
    intent = config.review_intent.strip()
    suffix = f" Granskningssyfte: {intent}" if intent else ""
    return (
        "Vilka generella frågor måste besvaras för att expertgranska "
        f"dokumentet {config.topic!r}?{suffix}"
    )


def _research_context(config: PanelSessionConfig) -> dict[str, Any]:
    return {
        "topic": config.topic,
        "review_intent": config.review_intent,
        "document": config.brief,
        "experts": [
            {"id": slot.slot_id, "label": slot.label, "profile": slot.profile}
            for slot in config.expert_slots
        ],
    }


async def _plan_questions(
    config: PanelSessionConfig,
    prompts: dict[str, str],
) -> ResearchPlan:
    proposals = await asyncio.gather(
        *(
            collect_expert_research_needs(slot, config, config.topic, prompts)
            for slot in config.expert_slots
        )
    )
    return await build_research_plan(
        config,
        config.topic,
        list(zip(config.expert_slots, proposals, strict=True)),
        prompts,
    )


async def _slot_persona_ids(
    session: AsyncSession,
    *,
    customer_id: int,
) -> dict[str, str]:
    personas = list(
        (
            await session.execute(
                select(Persona).where(
                    Persona.customer_id == customer_id,
                    Persona.kind == "expert",
                )
            )
        ).scalars()
    )
    return {expert_slot_id_for_persona(persona): persona.id for persona in personas}


async def _persist_questions(
    session: AsyncSession,
    *,
    run_id: str,
    attempt_id: str,
    panel_session_id: str,
    config: PanelSessionConfig,
    plan: ResearchPlan,
    customer_id: int,
) -> None:
    specific = await create_specific_question(
        session,
        run_id=run_id,
        text=_research_objective(config),
        context=_research_context(config),
        origin_kind="expertgranskning",
        origin_ref=panel_session_id,
    )
    persona_by_slot = await _slot_persona_ids(session, customer_id=customer_id)
    for need in plan.needs:
        raised_by = [
            persona_by_slot[slot_id] for slot_id in need.requested_by if slot_id in persona_by_slot
        ]
        if not raised_by:
            raise RuntimeError(f"Research question {need.id} has no customer expert provenance")
        await create_general_question(
            session,
            attempt_id=attempt_id,
            specific_question_id=specific.id,
            draft=GeneralQuestionDraft(
                question=need.question,
                why_needed=need.why_needed,
                raised_by_expert_ids=raised_by,
            ),
        )


def _copy_evidence_item(
    item: Any,
    *,
    research_question_id: str,
    child_attempt_id: str,
) -> EvidenceItemSnapshot:
    provenance = dict(item.provenance or {})
    provenance.update(
        {
            "research_question_id": research_question_id,
            "research_question_attempt_id": child_attempt_id,
        }
    )
    return EvidenceItemSnapshot(
        research_need_id=item.research_need_id,
        source_type=item.source_type,
        status=item.status,
        title=item.title,
        excerpt=item.excerpt,
        locator=item.locator,
        source_id=item.source_id,
        source_url=item.source_url,
        provider=item.provider,
        score=item.score,
        provenance=provenance,
        retrieved_at=item.retrieved_at,
        original_evidence_id=item.original_evidence_id,
        content_hash=item.content_hash,
    )


async def _freeze_aggregate_evidence(
    session: AsyncSession,
    *,
    run_id: str,
    attempt_id: str,
) -> None:
    evidence_set = await create_evidence_set(
        session,
        run_id=run_id,
        created_from_attempt_id=attempt_id,
    )
    questions = list(
        (
            await session.execute(
                select(ResearchQuestion)
                .where(
                    ResearchQuestion.attempt_id == attempt_id,
                    ResearchQuestion.status == "completed",
                    ResearchQuestion.execution_attempt_id.is_not(None),
                )
                .order_by(ResearchQuestion.created_at, ResearchQuestion.id)
            )
        ).scalars()
    )
    for question in questions:
        child_id = question.execution_attempt_id
        if child_id is None:
            continue
        child = await get_attempt(session, child_id)
        if child.evidence_set_id is None:
            raise RuntimeError(f"Research question Attempt has no evidence: {child_id}")
        items = await list_evidence_items(session, child.evidence_set_id)
        await add_evidence_items(
            session,
            evidence_set_id=evidence_set.id,
            items=[
                _copy_evidence_item(
                    item,
                    research_question_id=question.id,
                    child_attempt_id=child_id,
                )
                for item in items
            ],
        )
    frozen = await claim_freeze_evidence_set(session, evidence_set.id)
    if frozen is None:
        raise RuntimeError("Expertgranskning evidence was finalized concurrently")
    await attach_evidence_set(
        session,
        attempt_id=attempt_id,
        evidence_set_id=frozen.id,
    )
    await mark_ready(session, attempt_id)


async def run_expertgranskning_with_research(
    factory: async_sessionmaker[AsyncSession],
    *,
    session_id: str,
    customer_id: int,
) -> str:
    """Plan expert questions, research them in parallel, then run the panel."""
    async with factory() as session:
        panel = await session.get(PanelSession, session_id)
        if panel is None:
            raise ValueError(f"Panel session not found: {session_id}")
        config = PanelSessionConfig.model_validate(panel.config or {})
        prompts = await require_active_prompts(
            session,
            customer_id=customer_id,
            module=MODULE_ID,
            language=config.locale,
        )
        plan = await _plan_questions(config, prompts)
        run = await create_run(
            session,
            customer_id=customer_id,
            module=MODULE_ID,
            title=config.topic,
            context={"consumer": "expertgranskning", "panel_session_id": panel.id},
        )
        attempt = await create_attempt(
            session,
            run_id=run.id,
            attempt_type="generic_panel",
            configuration_snapshot=config.model_dump(mode="json"),
            input_snapshot={
                "topic": config.topic,
                "brief": document_text_from_config(panel.config or {}),
                "review_intent": review_intent_from_config(panel.config or {}),
            },
        )
        await _persist_questions(
            session,
            run_id=run.id,
            attempt_id=attempt.id,
            panel_session_id=panel.id,
            config=config,
            plan=plan,
            customer_id=customer_id,
        )
        await assign_unowned_research_questions(
            session,
            attempt_id=attempt.id,
            matcher=PanelCompetencyQuestionMatcher(prompts=prompts, locale=config.locale),
            creator=UnderlagExpertCreator(prompts=prompts, language=config.locale),
        )
        components = await bind_research_components(
            session,
            customer_id=customer_id,
            module=MODULE_ID,
        )
        research_planner = components["research_planner"]
        if research_planner is None:
            raise RuntimeError("Research planner is required for question execution")
        stored_config = dict(panel.config or {})
        stored_config["execution_run_id"] = run.id
        stored_config["execution_attempt_id"] = attempt.id
        panel.config = stored_config
        panel.research_plan = plan.model_dump(mode="json")
        await session.commit()
        attempt_id = attempt.id
        run_id = run.id

    worker = AttemptResearchQuestionWorker(
        session_factory=factory,
        router_factory=build_standard_research_router,
        research_planner=research_planner,
        assessor=components["assessor"],
        follow_up_planner=components["planner"],
        completeness_reviewer=components["completeness_reviewer"],
    )
    result = await execute_research_question_dag(
        factory,
        attempt_id=attempt_id,
        worker=worker,
    )
    if result.status not in {"completed", "completed_with_gaps"}:
        raise RuntimeError(f"Expertgranskning question research stopped as {result.status}")

    async with factory() as session:
        await _freeze_aggregate_evidence(
            session,
            run_id=run_id,
            attempt_id=attempt_id,
        )
        prompts = await require_active_prompts(
            session,
            customer_id=customer_id,
            module=MODULE_ID,
            language=config.locale,
        )
        await execute_generic_panel_attempt(
            session,
            attempt_id=attempt_id,
            prompts=prompts,
            panel_session_id=session_id,
        )
    return attempt_id
