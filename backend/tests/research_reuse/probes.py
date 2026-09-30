"""Small dev-only probes of production steps; never start the research worker.

Database reads are materialized and released before embeddings/model calls.
There is deliberately no replacement implementation of the proposed reuse gate.
"""

from collections.abc import Awaitable, Callable, Sequence
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.answer_review import KnowledgeAnswerReview
from app.database.graph_v2 import GraphFact, GraphNode
from app.llm.research_assessment import build_llm_research_assessor
from app.llm.research_followup import build_llm_follow_up_planner
from app.llm.legal_question_validator import build_llm_legal_question_validator
from app.services.lagen_nu.followup_validation import record_gap_timings
from app.services.execution import get_attempt, get_run, list_runtime_needs
from app.services.research.answer_review import capture_answer_reviews
from app.services.research.gap_planning import plan_question_gaps
from app.services.lagen_nu.question_validation import (
    LegalFollowUpPlannerAdapter,
    LegalNeedNormalizer,
)
from app.services.research.assessment import (
    ResearchAssessor,
    ResearchAssessmentDraft,
)
from app.services.research.followup import (
    FollowUpResearchPlanner,
    RuntimeResearchNeed,
)
from app.services.research.graph_lookup import lookup_question
from app.services.research.reuse_gate import answer_is_sufficient, assess_reuse
from app.services.research.knowledge_question import identity_from_text
from app.services.research.models import (
    ResearchContext,
    ResearchEvidence,
    ResearchNeed,
)

Factory = async_sessionmaker[AsyncSession]
AssessorBuilder = Callable[..., Awaitable[ResearchAssessor]]
GapPlannerBuilder = Callable[..., Awaitable[FollowUpResearchPlanner]]


async def lookup(factory, need, context, embeddings, *, timings=None):
    return await lookup_question(factory, need, context, embeddings, timings=timings)


async def assess(
    factory: Factory,
    need: ResearchNeed,
    items: Sequence[ResearchEvidence],
    context: ResearchContext,
    *,
    builder: AssessorBuilder = build_llm_research_assessor,
    timings: dict[str, float] | None = None,
) -> ResearchAssessmentDraft:
    started = perf_counter()
    async with factory() as session:
        adapter = await builder(
            session, customer_id=context.scope.customer_id, module=context.scope.module
        )
    if timings is not None:
        timings["prompt_load"] = perf_counter() - started
    fresh = [item for item in items if item.metadata.get("reuse", {}).get("freshness") == "fresh"]
    started = perf_counter()
    result = await assess_reuse(adapter, need, fresh)
    if timings is not None:
        timings["assessment"] = perf_counter() - started
    return result


async def build_gap_planner(
    session: AsyncSession,
    *,
    customer_id: int,
    module: str,
) -> FollowUpResearchPlanner:
    planner = await build_llm_follow_up_planner(session, customer_id=customer_id, module=module)
    validator = await build_llm_legal_question_validator(
        session, customer_id=customer_id, module=module
    )
    return LegalFollowUpPlannerAdapter(planner, LegalNeedNormalizer(validator))


async def gaps(
    factory: Factory,
    need: ResearchNeed,
    items: Sequence[ResearchEvidence],
    assessment: ResearchAssessmentDraft,
    *,
    context: ResearchContext,
    builder: GapPlannerBuilder = build_gap_planner,
    timings: dict[str, float] | None = None,
) -> list[RuntimeResearchNeed]:
    if answer_is_sufficient(assessment):
        return []
    started = perf_counter()
    async with factory() as session:
        adapter = await builder(
            session, customer_id=context.scope.customer_id, module=context.scope.module
        )
    if timings is not None:
        timings["prompt_load"] = perf_counter() - started
    started = perf_counter()
    with record_gap_timings(timings):
        result = await plan_question_gaps(adapter, need, assessment, items)
    if timings is not None:
        timings["gap_planning"] = perf_counter() - started
    return result


async def capture(factory: Factory, attempt_id: str) -> dict[str, object]:
    """Exercise real writes, inspect them, then roll back the owned transaction."""
    async with factory() as session:
        attempt = await get_attempt(session, attempt_id)
        if not attempt.evidence_set_id:
            raise ValueError("Step 4 needs an attempt with a persisted EvidenceSet")
        run = await get_run(session, attempt.run_id)
        objective = (attempt.research_objective_snapshot or {}).get("objective")
        if not objective:
            raise ValueError("Step 4 needs a persisted research objective")
        captured = await capture_answer_reviews(
            session,
            attempt_id=attempt.id,
            evidence_set_id=attempt.evidence_set_id,
        )
        main_key = next(
            (row.question_key for row in await list_runtime_needs(session, attempt.id)
             if row.research_need_id == "research-main" or row.question == objective),
            identity_from_text(objective).identity_key,
        )
        main_basis = await session.scalar(
            select(KnowledgeAnswerReview.answer_basis)
            .where(
                KnowledgeAnswerReview.customer_id == run.customer_id,
                KnowledgeAnswerReview.question_key == main_key,
            )
            .order_by(KnowledgeAnswerReview.created_at.desc())
            .limit(1)
        )
        from app.database.models import KnowledgeQuestionRow

        canonical_id = await session.scalar(
            select(KnowledgeQuestionRow.id).where(
                KnowledgeQuestionRow.scope_key == f"customer:{run.customer_id}",
                KnowledgeQuestionRow.identity_key == main_key,
            )
        )
        nodes = list(
            await session.scalars(
                select(GraphNode.id).where(
                    GraphNode.scope_key == f"customer:{run.customer_id}",
                    GraphNode.node_type == "core.question",
                    GraphNode.attributes["canonical_question_id"].as_string() == canonical_id,
                )
            )
        )
        facts = list(
            await session.scalars(
                select(GraphFact.id).where(
                    GraphFact.source_id.in_(nodes),
                    GraphFact.predicate == "research.answered_by",
                    GraphFact.status == "active",
                )
            )
        )
        main_captured = objective in [text for _key, text in captured]
        output = {
            "captured_questions": [text for _key, text in captured],
            "main_basis": main_basis,
            "main_graph_question_ids": nodes,
            "main_graph_fact_ids": facts,
            "contract_passed": bool(main_captured and main_basis and facts),
            "writes": "rolled_back",
        }
        await session.rollback()
        return output
