"""Read completed Graph answers without materializing a new evidence episode."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.graph_v2 import GraphFact, GraphIdentifier, GraphNode
from app.database.models import (
    EvidenceSet,
    ExecutionAttempt,
    ExecutionRun,
    KnowledgeQuestionRow,
    SpecificQuestion,
)
from app.services.research.answer_graph import (
    ANSWER_PREDICATE,
    ANSWER_TYPE,
    BASIS,
    _context_matches,
    _current_basis,
)
from app.services.research.workspace_grounding import basis_workspace_allowed
from app.services.research.graph_grounding import GraphResearchError, fact_is_current
from app.services.research.knowledge_question import knowledge_question_identity_key
from app.services.research.models import ResearchContext, ResearchEvidence, ResearchNeed
from app.services.research.planner import ResearchObjective

TRANSIENT_CONTEXT = frozenset(
    {
        "research_question_id",
        "knowledge_question_id",
        "specific_question_id",
        "assigned_expert_id",
    }
)


@dataclass(frozen=True)
class SavedResearch:
    fact_id: str
    question_id: str
    question: str
    evidence_set_id: str
    source_attempt_id: str
    basis: list[ResearchEvidence]
    assessment: dict
    context: dict


async def meaningful_context(session: AsyncSession, objective: ResearchObjective) -> dict:
    context = {
        key: value for key, value in objective.context.items() if key not in TRANSIENT_CONTEXT
    }
    specific_id = objective.context.get("specific_question_id")
    if specific_id:
        specific = await session.get(SpecificQuestion, specific_id)
        if specific is None:
            raise GraphResearchError(
                "Research result context references a missing specific question"
            )
        context["specific_question"] = specific.text
        context["specific_question_context"] = specific.context
    return context


async def exact_answers(
    session: AsyncSession, need: ResearchNeed, context: ResearchContext
) -> list[str]:
    rows = await session.scalars(
        select(GraphFact.id)
        .join(GraphIdentifier, GraphIdentifier.node_id == GraphFact.source_id)
        .join(KnowledgeQuestionRow, KnowledgeQuestionRow.id == GraphIdentifier.identifier)
        .where(
            GraphFact.scope_key == f"customer:{context.scope.customer_id}",
            GraphIdentifier.scope_key == GraphFact.scope_key,
            GraphIdentifier.namespace == "research.question_id",
            KnowledgeQuestionRow.scope_key == GraphFact.scope_key,
            KnowledgeQuestionRow.identity_key == knowledge_question_identity_key(need.question),
            GraphFact.predicate == ANSWER_PREDICATE,
            GraphFact.status == "active",
        )
        .order_by(GraphFact.created_at.desc(), GraphFact.id)
        .limit(8)
    )
    return list(rows)


async def load_saved_answer(
    session: AsyncSession,
    fact_id: str,
    context: ResearchContext,
    *,
    now: datetime,
) -> SavedResearch | None:
    row = (
        await session.execute(
            select(GraphFact, GraphNode, EvidenceSet, ExecutionAttempt, ExecutionRun)
            .join(GraphNode, GraphNode.id == GraphFact.target_id)
            .join(
                EvidenceSet, EvidenceSet.id == GraphNode.attributes["evidence_set_id"].as_string()
            )
            .join(ExecutionAttempt, ExecutionAttempt.evidence_set_id == EvidenceSet.id)
            .join(ExecutionRun, ExecutionRun.id == EvidenceSet.run_id)
            .where(
                GraphFact.id == fact_id,
                GraphFact.scope_key == f"customer:{context.scope.customer_id}",
                GraphNode.scope_key == GraphFact.scope_key,
                GraphNode.node_type == ANSWER_TYPE,
                GraphFact.predicate == ANSWER_PREDICATE,
                ExecutionRun.customer_id == context.scope.customer_id,
                ExecutionRun.module == context.scope.module,
                ExecutionAttempt.run_id == EvidenceSet.run_id,
                ExecutionAttempt.status.in_(("ready", "completed")),
            )
            .order_by(ExecutionAttempt.created_at)
            .limit(1)
        )
    ).one_or_none()
    if row is None:
        return None
    fact, node, frozen, owner, run = row
    assessment = node.attributes.get("assessment", {})
    if (
        frozen.status != "frozen"
        or not fact_is_current(fact, now)
        or not _context_matches(fact, context)
        or run.context.get("case_id") != context.scope.case_id
    ):
        return None
    if not assessment.get("sufficient") or any(
        item.get("contradictions") for item in assessment.get("needs", [])
    ):
        return None
    basis = BASIS.validate_python(node.attributes.get("basis"))
    refs = {item.evidence_id for item in basis}
    assessed = assessment.get("needs", [])
    supported = bool(assessed) and all(
        row.get("sufficient") and refs.intersection(row.get("supporting_evidence_ids", []))
        for row in assessed
    )
    if not supported or not basis or not await basis_workspace_allowed(session, basis, context) or not await _current_basis(session, basis, fact.scope_key, now):
        return None
    question_node = await session.get(GraphNode, fact.source_id)
    if question_node is None or question_node.scope_key != fact.scope_key:
        raise GraphResearchError("Saved research question crossed its tenant boundary")
    snapshot = owner.research_objective_snapshot
    if snapshot is None:
        return None
    return SavedResearch(
        fact.id,
        question_node.attributes["canonical_question_id"],
        question_node.name,
        frozen.id,
        owner.id,
        basis,
        assessment,
        {
            "objective": await meaningful_context(session, ResearchObjective(**snapshot)),
            "run": run.context,
        },
    )


async def requested_context(
    session: AsyncSession, objective: ResearchObjective, run: ExecutionRun
) -> dict:
    return {"objective": await meaningful_context(session, objective), "run": run.context}
