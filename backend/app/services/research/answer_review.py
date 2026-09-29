"""Capture each question's final multi-source answer basis at the freeze boundary."""

import hashlib
import json
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    DomainResearchResultRecord,
    EvidencePassage,
    EvidenceSetItem,
    EvidenceSetItemNeed,
    EvidenceSource,
    KnowledgeQuestionRow,
    ResearchAssessment,
    ResearchRuntimeNeed,
)
from app.services.execution.service import get_attempt, get_run, mark_ready
from app.services.knowledge.answer_review import record_answer_review
from app.services.graph_v2.questions import question_node
from app.services.graph_v2.revalidation import enqueue_question_revalidation
from app.services.research.progress import emit_research_frozen_ready

_IDENTITY_FIELDS = ("source_type", "source_id", "source_url", "locator", "content_hash")


async def complete_research_freeze(
    session: AsyncSession, *, attempt_id: str, evidence_set_id: str
) -> None:
    """Research only records durable work; TTL classification runs separately."""
    frozen_questions = await capture_answer_reviews(
        session, attempt_id=attempt_id, evidence_set_id=evidence_set_id,
    )
    run = await get_run(session, (await get_attempt(session, attempt_id)).run_id)
    await _enqueue_graph_revalidation(
        session, customer_id=run.customer_id, evidence_set_id=evidence_set_id,
        questions=frozen_questions,
    )
    ready = await mark_ready(session, attempt_id)
    await emit_research_frozen_ready(
        session,
        attempt_id=attempt_id,
        evidence_set_id=evidence_set_id,
        stop_reason=ready.research_stop_reason,
    )


async def capture_answer_reviews(
    session: AsyncSession, *, attempt_id: str, evidence_set_id: str
) -> tuple[tuple[str, str], ...]:
    attempt = await get_attempt(session, attempt_id)
    run = await get_run(session, attempt.run_id)
    needs = (
        await session.execute(
            select(
                ResearchRuntimeNeed.research_need_id,
                ResearchRuntimeNeed.question_key,
                ResearchRuntimeNeed.question,
            ).where(ResearchRuntimeNeed.attempt_id == attempt_id)
        )
    ).all()
    evidence = await _evidence_by_need(session, evidence_set_id)
    assessment = (
        await session.execute(
            select(ResearchAssessment.need_assessments)
            .where(ResearchAssessment.attempt_id == attempt_id)
            .order_by(ResearchAssessment.assessment_pass.desc())
            .limit(1)
        )
    ).scalar_one_or_none() or []
    assessments = {row["research_need_id"]: row for row in assessment}
    groups: dict[str, dict] = {}
    for need_id, key, question in needs:
        basis = groups.setdefault(
            key,
            {
                "question": question,
                "scope": {"module": run.module, "case_id": run.context.get("case_id")},
                "evidence": {},
                "assessments": [],
            },
        )
        basis["evidence"].update(evidence.get(need_id, {}))
        if need_id in assessments:
            # Runtime need/supporting IDs are attempt-local, not version identity.
            basis["assessments"].append(
                {
                    k: v
                    for k, v in assessments[need_id].items()
                    if k not in {"research_need_id", "supporting_evidence_ids"}
                }
            )
    frozen_questions: list[tuple[str, str]] = []
    for key, basis in groups.items():
        if not basis["evidence"]:
            continue
        basis["evidence"] = [basis["evidence"][ref] for ref in sorted(basis["evidence"])]
        basis["assessments"] = sorted(
            basis["assessments"], key=lambda row: json.dumps(row, sort_keys=True)
        )
        await record_answer_review(
            session,
            customer_id=run.customer_id,
            question_key=key,
            answer_basis=basis,
        )
        frozen_questions.append((key, basis["question"]))
    return tuple(frozen_questions)


async def _enqueue_graph_revalidation(
    session: AsyncSession, *, customer_id: int, evidence_set_id: str,
    questions: tuple[tuple[str, str], ...],
) -> None:
    """Start graph review only after all providers contributed to the frozen basis."""
    tenant_scope = f"customer:{customer_id}"
    for key, _text in questions:
        question = await session.scalar(
            select(KnowledgeQuestionRow)
            .where(
                KnowledgeQuestionRow.identity_key == key,
                KnowledgeQuestionRow.scope_key == tenant_scope,
            )
            .limit(1)
        )
        if question is None:
            question = await session.scalar(
                select(KnowledgeQuestionRow)
                .where(
                    KnowledgeQuestionRow.identity_key == key,
                    KnowledgeQuestionRow.scope_key == "shared",
                )
                .limit(1)
            )
        if question is None:
            continue
        node = await question_node(session, question)
        await enqueue_question_revalidation(
            session, customer_id=customer_id, question_node_id=node.id,
            evidence_set_id=evidence_set_id,
        )


async def _evidence_by_need(session: AsyncSession, evidence_set_id: str) -> dict:
    # Project only this set's content; do not eager-load historical graphs/raw documents.
    rows = (
        await session.execute(
            select(
                func.coalesce(
                    EvidenceSetItemNeed.research_need_id, EvidenceSetItem.research_need_id
                ).label("need_id"),
                EvidenceSetItem.source_type,
                func.coalesce(EvidenceSource.provider, EvidenceSetItem.provider).label("provider"),
                func.coalesce(EvidenceSource.source_id, EvidenceSetItem.source_id).label(
                    "source_id"
                ),
                func.coalesce(EvidenceSource.source_url, EvidenceSetItem.source_url).label(
                    "source_url"
                ),
                func.coalesce(EvidencePassage.excerpt, EvidenceSetItem.excerpt).label("excerpt"),
                func.coalesce(EvidencePassage.locator, EvidenceSetItem.locator).label("locator"),
                EvidenceSetItem.content_hash,
                DomainResearchResultRecord.result.label("interpretation"),
            )
            .outerjoin(
                EvidenceSetItemNeed, EvidenceSetItemNeed.evidence_set_item_id == EvidenceSetItem.id
            )
            .outerjoin(EvidencePassage, EvidencePassage.id == EvidenceSetItem.passage_id)
            .outerjoin(EvidenceSource, EvidenceSource.id == EvidencePassage.source_id)
            .outerjoin(
                DomainResearchResultRecord,
                DomainResearchResultRecord.id == EvidenceSetItem.domain_result_id,
            )
            .where(
                EvidenceSetItem.evidence_set_id == evidence_set_id,
                EvidenceSetItem.status == "found",
            )
        )
    ).mappings()
    evidence: dict[str, dict] = defaultdict(dict)
    for row in rows:
        snapshot = {k: v for k, v in row.items() if k != "need_id"}
        # Identity is the cited source content only. Excerpts of derived evidence,
        # interpretations and providers are LLM/adapter output and may be worded
        # differently on rediscovery; they stay in the payload, not in the hash.
        identity = {k: snapshot[k] for k in _IDENTITY_FIELDS}
        ref = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        evidence[row["need_id"]][ref] = {"ref": ref, **snapshot}
    return evidence
