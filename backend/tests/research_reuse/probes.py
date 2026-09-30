"""Small dev-only probes of production steps; never start the research worker.

Database reads are materialized and released before embeddings/model calls.
There is deliberately no replacement implementation of the proposed reuse gate.
"""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.answer_review import KnowledgeAnswerReview
from app.database.graph_v2 import GraphFact, GraphFactQuestionDependency, GraphFactSource, GraphNode
from app.services.graph_v2.identity import normalized
from app.llm.research_assessment import build_llm_research_assessor
from app.llm.research_followup import build_llm_follow_up_planner
from app.llm.legal_question_validator import build_llm_legal_question_validator
from app.services.execution import get_attempt, get_run
from app.services.execution.snapshots import snapshot_research_evidence
from app.services.research.answer_review import capture_answer_reviews
from app.services.knowledge.embeddings import EmbeddingProvider
from app.services.lagen_nu.question_validation import (
    LegalFollowUpPlannerAdapter,
    LegalNeedNormalizer,
)
from app.services.research.assessment import (
    AssessableEvidence,
    ResearchAssessor,
    ResearchAssessmentDraft,
)
from app.services.research.followup import (
    FollowUpResearchPlanner,
    RuntimeResearchNeed,
    runtime_needs_from_plan,
    validate_follow_up_drafts,
)
from app.services.research.graph_reuse import lookup_graph_evidence
from app.services.research.knowledge_question import identity_from_text
from app.services.research.models import (
    ResearchContext,
    ResearchEvidence,
    ResearchNeed,
    ResearchPlan,
)

Factory = async_sessionmaker[AsyncSession]
AssessorBuilder = Callable[..., Awaitable[ResearchAssessor]]
GapPlannerBuilder = Callable[..., Awaitable[FollowUpResearchPlanner]]


@dataclass
class PreparedEmbedding:
    model: str
    dimension: int
    vector: list[float]
    provider_id: str = "prepared-live-query"

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if len(texts) != 1:
            raise ValueError("The step probe accepts exactly one question")
        return [self.vector]


async def lookup(
    factory: Factory,
    need: ResearchNeed,
    context: ResearchContext,
    embeddings: EmbeddingProvider,
    *,
    timings: dict[str, float] | None = None,
) -> list[ResearchEvidence]:
    # Embed before entering the graph read session: SELECT itself retains a connection.
    started = perf_counter()
    vectors = await embeddings.embed([need.question])
    if timings is not None:
        timings["embedding"] = perf_counter() - started
    if len(vectors) != 1:
        raise ValueError("Query embedding must contain one vector")
    prepared = PreparedEmbedding(embeddings.model, embeddings.dimension, vectors[0])
    started = perf_counter()
    async with factory() as session:
        result = await lookup_graph_evidence(session, need=need, context=context, embedder=prepared)
    if timings is not None:
        timings["graph_read"] = perf_counter() - started
    return result


def assessable(items: Sequence[ResearchEvidence]) -> list[AssessableEvidence]:
    output = []
    for item in items:
        snapshot = snapshot_research_evidence(item)
        output.append(
            AssessableEvidence(
                evidence_id=item.evidence_id,
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
                provenance=item.metadata,
                retrieved_at=item.retrieved_at,
                content_hash=snapshot.content_hash,
                legal_result=item.legal_result,
            )
        )
    return output


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
    result = await adapter.assess(ResearchPlan(needs=[need]), assessable(fresh))
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
    if assessment.result == "sufficient":
        return []
    started = perf_counter()
    async with factory() as session:
        adapter = await builder(
            session, customer_id=context.scope.customer_id, module=context.scope.module
        )
    if timings is not None:
        timings["prompt_load"] = perf_counter() - started
    plan = ResearchPlan(needs=[need])
    previous = runtime_needs_from_plan(plan)
    started = perf_counter()
    drafts = await adapter.plan_follow_ups(
        plan=plan,
        assessment=assessment,
        evidence=assessable(items),
        previous_needs=previous,
        available_source_types=need.source_types,
    )
    if timings is not None:
        timings["gap_planning"] = perf_counter() - started
    return validate_follow_up_drafts(
        drafts,
        previous_needs=previous,
        wave_number=1,
        assessment_pass=1,
        allowed_source_types=need.source_types,
    )


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
        main_key = identity_from_text(objective).identity_key
        main_basis = await session.scalar(
            select(KnowledgeAnswerReview.answer_basis)
            .where(
                KnowledgeAnswerReview.customer_id == run.customer_id,
                KnowledgeAnswerReview.question_key == main_key,
            )
            .order_by(KnowledgeAnswerReview.created_at.desc())
            .limit(1)
        )
        nodes = list(
            await session.scalars(
                select(GraphNode.id).where(
                    GraphNode.scope_key == f"customer:{run.customer_id}",
                    GraphNode.node_type == "core.question",
                    GraphNode.normalized_name == normalized(objective),
                )
            )
        )
        facts = list(
            await session.scalars(
                select(GraphFact.id)
                .distinct()
                .join(
                    GraphFactQuestionDependency, GraphFactQuestionDependency.fact_id == GraphFact.id
                )
                .join(GraphFactSource, GraphFactSource.fact_id == GraphFact.id)
                .where(
                    GraphFactQuestionDependency.question_node_id.in_(nodes),
                    GraphFact.scope_key.in_(("shared", f"customer:{run.customer_id}")),
                    GraphFact.status == "active",
                    GraphFactSource.source_kind == "text_unit",
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
