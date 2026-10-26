"""Read completed Graph answers without materializing a new evidence episode."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


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
from app.services.overgraph.answers_owner import (
    answer_facts_via_owner,
    entity_attributes_via_owner,
)
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.labels import FACT
from app.services.overgraph.model import GraphRecord
from app.services.overgraph.answers import answer_facts, entity_attributes
from app.services.overgraph.owner_runtime import get_owner_runtime
from app.services.overgraph.views import fact_view
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


def _answers_in_scope(catalog, question_id, customer_id, now):
    return answer_facts(
        catalog, question_id, customer_id, limit=8, now=now,
        exact_scope=f"customer:{customer_id}",
    )


async def exact_answers(
    session: AsyncSession, need: ResearchNeed, context: ResearchContext, *, now: datetime,
) -> list[str]:
    scope_key = f"customer:{context.scope.customer_id}"
    question_id = await session.scalar(
        select(KnowledgeQuestionRow.id).where(
            KnowledgeQuestionRow.scope_key == scope_key,
            KnowledgeQuestionRow.identity_key == knowledge_question_identity_key(need.question),
        )
    )
    if question_id is None:
        return []
    owner = get_owner_runtime().client
    if owner is not None:
        facts = await answer_facts_via_owner(
            owner, question_id, context.scope.customer_id, now=now,
        )
    else:
        catalog = require_knowledge()
        facts = await catalog.run(
            _answers_in_scope, catalog, question_id, context.scope.customer_id, now,
        )
    return [fact.id for fact in facts]


def _saved_answer_parts(catalog, fact_id: str, scope_key: str):
    row = catalog.get_by_key(FACT, fact_id)
    if row is None:
        return None
    fact = fact_view(row)
    if fact.scope_key != scope_key or fact.predicate != ANSWER_PREDICATE:
        return None
    target = entity_attributes(catalog, fact.target_id)
    source = entity_attributes(catalog, fact.source_id)
    if target is None or source is None or target.node_type != ANSWER_TYPE:
        return None
    if target.scope_key != fact.scope_key or source.scope_key != fact.scope_key:
        raise GraphResearchError("Saved research question crossed its tenant boundary")
    return fact, target, source


async def _saved_answer_owner(session: AsyncSession, evidence_set_id: str, context):
    return (
        await session.execute(
            select(EvidenceSet, ExecutionAttempt, ExecutionRun)
            .join(ExecutionAttempt, ExecutionAttempt.evidence_set_id == EvidenceSet.id)
            .join(ExecutionRun, ExecutionRun.id == EvidenceSet.run_id)
            .where(
                EvidenceSet.id == evidence_set_id,
                ExecutionRun.customer_id == context.scope.customer_id,
                ExecutionRun.module == context.scope.module,
                ExecutionAttempt.run_id == EvidenceSet.run_id,
                ExecutionAttempt.status.in_(("ready", "completed")),
            )
            .order_by(ExecutionAttempt.created_at)
            .limit(1)
        )
    ).one_or_none()


def _answer_is_usable(attributes, basis, fact, context, *, now, frozen, run) -> bool:
    if frozen.status != "frozen" or run.context.get("case_id") != context.scope.case_id:
        return False
    if not fact_is_current(fact, now) or not _context_matches(fact, context):
        return False
    assessment = attributes.get("assessment", {})
    if not assessment.get("sufficient") or any(
        item.get("contradictions") for item in assessment.get("needs", [])
    ):
        return False
    refs = {item.evidence_id for item in basis}
    assessed = assessment.get("needs", [])
    return bool(assessed) and all(
        need.get("sufficient") and refs.intersection(need.get("supporting_evidence_ids", []))
        for need in assessed
    )


async def _saved_answer_supported(session, basis, fact, context, *, now) -> bool:
    if not await basis_workspace_allowed(session, basis, context):
        return False
    return await _current_basis(
        session, basis, fact.scope_key, now, client=get_owner_runtime().client,
    )


async def _saved_answer_parts_owner(
    client, fact_id: str, scope_key: str,
):
    response = await client.read([{"label": FACT, "key": fact_id}])
    props = response["values"].get(f"{FACT}:{fact_id}")
    if props is None:
        return None
    fact = fact_view(GraphRecord(
        key=fact_id, labels=(FACT,), props=dict(props),
        engine_id=response["ids"].get(f"{FACT}:{fact_id}"),
    ))
    if fact.scope_key != scope_key or fact.predicate != ANSWER_PREDICATE:
        return None
    target = await entity_attributes_via_owner(client, fact.target_id)
    source = await entity_attributes_via_owner(client, fact.source_id)
    if target is None or source is None or target.node_type != ANSWER_TYPE:
        return None
    if target.scope_key != fact.scope_key or source.scope_key != fact.scope_key:
        return None
    return fact, target, source


async def load_saved_answer(
    session: AsyncSession,
    fact_id: str,
    context: ResearchContext,
    *,
    now: datetime,
) -> SavedResearch | None:
    owner = get_owner_runtime().client
    if owner is not None:
        parts = await _saved_answer_parts_owner(
            owner, fact_id, f"customer:{context.scope.customer_id}",
        )
    else:
        catalog = require_knowledge()
        parts = await catalog.run(
            _saved_answer_parts, catalog, fact_id, f"customer:{context.scope.customer_id}",
        )
    if parts is None:
        return None
    fact, target, source = parts
    evidence_set_id = str(target.attributes.get("evidence_set_id") or "")
    owner_row = (
        await _saved_answer_owner(session, evidence_set_id, context) if evidence_set_id else None
    )
    if owner_row is None:
        return None
    frozen, owner, run = owner_row
    basis = BASIS.validate_python(target.attributes.get("basis"))
    usable = bool(basis) and _answer_is_usable(
        target.attributes, basis, fact, context, now=now, frozen=frozen, run=run,
    )
    if not usable or not await _saved_answer_supported(session, basis, fact, context, now=now):
        return None
    snapshot = owner.research_objective_snapshot
    if snapshot is None:
        return None
    return SavedResearch(
        fact.id,
        str(source.attributes.get("canonical_question_id") or ""),
        source.name,
        frozen.id,
        owner.id,
        basis,
        target.attributes.get("assessment", {}),
        {
            "objective": await meaningful_context(session, ResearchObjective(**snapshot)),
            "run": run.context,
        },
    )


async def requested_context(
    session: AsyncSession, objective: ResearchObjective, run: ExecutionRun
) -> dict:
    return {"objective": await meaningful_context(session, objective), "run": run.context}
