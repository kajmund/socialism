"""Publish frozen question evidence and durable expert knowledge receipts."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    EvidenceSet,
    EvidenceSetItem,
    EvidenceSetItemNeed,
    ExecutionAttempt,
    ExecutionRun,
    ExpertKnowledgeReceipt,
    KnowledgeQuestionRow,
    Persona,
    ResearchQuestion,
    ResearchQuestionExpert,
    SpecificQuestion,
)
from app.services.dd.expert_keys import persona_catalog_key
from app.services.execution.service import new_id
from app.services.expertgranskning.memory import get_expert_memory
from app.services.research.knowledge_question import (
    KnowledgeQuestion,
    KnowledgeQuestionScope,
    evidence_visibility,
    stable_evidence_ref,
)
from app.services.research.models import utc_now
from app.services.research.question_graph import (
    ANSWERED_BY,
    QuestionEvidenceGraph,
    QuestionEvidenceLink,
)


@dataclass(frozen=True)
class ExpertKnowledgeMemory:
    customer_id: int
    persona_id: str
    memory_expert_id: str
    question: str
    knowledge_question_id: str
    source_attempt_id: str


async def publish_research_question_knowledge(
    session: AsyncSession,
    *,
    research_question_id: str,
    graph: QuestionEvidenceGraph,
) -> list[ExpertKnowledgeMemory]:
    loaded = (
        await session.execute(
            select(
                ResearchQuestion,
                KnowledgeQuestionRow,
                SpecificQuestion,
                ExecutionAttempt,
                ExecutionRun,
            )
            .join(
                KnowledgeQuestionRow,
                KnowledgeQuestionRow.id == ResearchQuestion.knowledge_question_id,
            )
            .join(
                SpecificQuestion,
                SpecificQuestion.id == ResearchQuestion.specific_question_id,
            )
            .join(ExecutionAttempt, ExecutionAttempt.id == ResearchQuestion.attempt_id)
            .join(ExecutionRun, ExecutionRun.id == ExecutionAttempt.run_id)
            .where(ResearchQuestion.id == research_question_id)
        )
    ).one_or_none()
    if loaded is None:
        raise ValueError(f"Research question not found: {research_question_id}")
    question, canonical_row, specific, _parent, run = loaded
    if question.execution_attempt_id is None:
        raise ValueError("Research question has no child Attempt")
    child = await session.get(ExecutionAttempt, question.execution_attempt_id)
    if child is None or child.run_id != run.id or child.status not in {"ready", "completed"}:
        raise ValueError("Research question child Attempt is not ready")
    if child.evidence_set_id is None:
        raise ValueError("Research question child Attempt has no EvidenceSet")
    evidence_set = await session.get(EvidenceSet, child.evidence_set_id)
    if evidence_set is None or evidence_set.status != "frozen":
        raise ValueError("Expert knowledge requires a frozen EvidenceSet")

    canonical = _canonical_question(canonical_row)
    items_query = select(EvidenceSetItem).where(
        EvidenceSetItem.evidence_set_id == evidence_set.id,
        EvidenceSetItem.status == "found",
    )
    if question.runtime_need_id is not None:
        items_query = items_query.join(
            EvidenceSetItemNeed,
            EvidenceSetItemNeed.evidence_set_item_id == EvidenceSetItem.id,
        ).where(
            EvidenceSetItemNeed.research_need_id == question.runtime_need_id
        )
    items = list(
        (
            await session.execute(items_query.order_by(EvidenceSetItem.ordinal, EvidenceSetItem.id))
        ).scalars()
    )
    if not items:
        return []
    for item in items:
        await graph.upsert_answer(
            session,
            _answer_link(
                canonical,
                item,
                run=run,
                source_attempt_id=child.id,
            ),
        )

    expert_links = list(
        (
            await session.execute(
                select(ResearchQuestionExpert).where(
                    ResearchQuestionExpert.question_id == question.id
                )
            )
        ).scalars()
    )
    expert_ids = {link.expert_id for link in expert_links}
    experts = {
        persona.id: persona
        for persona in (
            await session.execute(
                select(Persona).where(
                    Persona.id.in_(expert_ids),
                    Persona.customer_id == run.customer_id,
                    Persona.kind == "expert",
                )
            )
        ).scalars()
    }
    missing_experts = expert_ids - experts.keys()
    if missing_experts:
        missing = ", ".join(sorted(missing_experts))
        raise ValueError(f"Research question has invalid expert provenance: {missing}")
    confirmed = utc_now()
    memories: dict[str, ExpertKnowledgeMemory] = {}
    for link in expert_links:
        existing = (
            await session.execute(
                select(ExpertKnowledgeReceipt).where(
                    ExpertKnowledgeReceipt.expert_id == link.expert_id,
                    ExpertKnowledgeReceipt.knowledge_question_id == canonical.id,
                    ExpertKnowledgeReceipt.source_attempt_id == child.id,
                    ExpertKnowledgeReceipt.role == link.role,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                ExpertKnowledgeReceipt(
                    id=new_id(),
                    customer_id=run.customer_id,
                    expert_id=link.expert_id,
                    knowledge_question_id=canonical.id,
                    research_question_id=question.id,
                    source_attempt_id=child.id,
                    evidence_set_id=evidence_set.id,
                    role=link.role,
                    origin_kind=specific.origin_kind,
                    origin_ref=specific.origin_ref,
                    confirmed_at=confirmed,
                )
            )
        else:
            existing.confirmed_at = confirmed
            existing.evidence_set_id = evidence_set.id
            existing.research_question_id = question.id
        memories[link.expert_id] = ExpertKnowledgeMemory(
            customer_id=run.customer_id,
            persona_id=link.expert_id,
            memory_expert_id=persona_catalog_key(experts[link.expert_id]),
            question=canonical.display_text,
            knowledge_question_id=canonical.id,
            source_attempt_id=child.id,
        )
    await session.flush()
    return list(memories.values())


async def publish_completed_attempt_knowledge(
    session: AsyncSession,
    *,
    attempt_id: str,
    graph: QuestionEvidenceGraph,
) -> list[ExpertKnowledgeMemory]:
    """Publish every completed DAG question, including researched follow-ups."""
    question_ids = list(
        (
            await session.execute(
                select(ResearchQuestion.id)
                .where(
                    ResearchQuestion.attempt_id == attempt_id,
                    ResearchQuestion.status == "completed",
                    ResearchQuestion.execution_attempt_id.is_not(None),
                )
                .order_by(ResearchQuestion.created_at, ResearchQuestion.id)
            )
        ).scalars()
    )
    memories: dict[tuple[str, str, str], ExpertKnowledgeMemory] = {}
    for question_id in question_ids:
        published = await publish_research_question_knowledge(
            session,
            research_question_id=question_id,
            graph=graph,
        )
        for receipt in published:
            key = (
                receipt.persona_id,
                receipt.knowledge_question_id,
                receipt.source_attempt_id,
            )
            memories[key] = receipt
    return list(memories.values())


async def remember_published_question(memories: list[ExpertKnowledgeMemory]) -> None:
    memory = get_expert_memory()
    for receipt in memories:
        await memory.add_research_receipt(
            customer_id=receipt.customer_id,
            expert_id=receipt.memory_expert_id,
            question=receipt.question,
            knowledge_question_id=receipt.knowledge_question_id,
            source_attempt_id=receipt.source_attempt_id,
        )


def _canonical_question(row: KnowledgeQuestionRow) -> KnowledgeQuestion:
    return KnowledgeQuestion(
        id=row.id,
        identity_key=row.identity_key,
        normalized_text=row.normalized_text,
        display_text=row.display_text,
        scope=KnowledgeQuestionScope(
            visibility=row.visibility,  # type: ignore[arg-type]
            customer_id=row.customer_id,
        ),
        embedding_model=row.embedding_model,
        embedding_version=row.embedding_version,
        embedding_dimension=row.embedding_dimension,
        created_at=row.created_at,
    )


def _answer_link(
    question: KnowledgeQuestion,
    item: EvidenceSetItem,
    *,
    run: ExecutionRun,
    source_attempt_id: str,
) -> QuestionEvidenceLink:
    provenance = dict(item.provenance or {})
    provenance["knowledge_module"] = run.module
    raw_context = run.context if isinstance(run.context, dict) else {}
    case_id = raw_context.get("case_id")
    if item.source_type == "case_knowledge" and case_id is not None:
        provenance["knowledge_case_id"] = str(case_id)
    return QuestionEvidenceLink(
        question_id=question.id,
        evidence_ref=stable_evidence_ref(
            provider=item.provider,
            source_id=item.source_id,
            locator=item.locator,
            excerpt=item.excerpt,
        ),
        passage_id=item.passage_id,
        relation=ANSWERED_BY,
        title=item.title,
        excerpt=item.excerpt,
        locator=item.locator,
        source_id=item.source_id,
        source_url=item.source_url,
        source_type=item.source_type,
        provider=item.provider,
        provenance=provenance,
        retrieved_at=item.retrieved_at,
        observed_at=utc_now(),
        freshness="fresh",
        version=None,
        visibility=evidence_visibility(item.provenance),
        source_attempt_id=source_attempt_id,
    )
