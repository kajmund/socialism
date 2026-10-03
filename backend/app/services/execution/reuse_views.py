"""Read projections for referenced research. These objects are never persisted."""

from collections.abc import Awaitable, Callable
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.graph_v2 import GraphFact, GraphNode
from app.database.models import (
    EvidenceSetItem,
    ExecutionAttempt,
    ExecutionRun,
    ResearchAssessment,
    ResearchCompletenessPass,
    ResearchNeedExecution,
    ResearchRuntimeNeed,
)
from app.services.execution.reuse_reference import REUSE_KEY


async def reuse_payloads(
    session: AsyncSession, attempts: list[ExecutionAttempt]
) -> list[tuple[ExecutionAttempt, dict, dict]]:
    bound = [
        (attempt, attempt.input_snapshot[REUSE_KEY])
        for attempt in attempts
        if REUSE_KEY in attempt.input_snapshot
    ]
    if not bound:
        return []
    rows = (
        await session.execute(
            select(GraphFact, GraphNode)
            .join(
                GraphNode,
                GraphNode.id == GraphFact.target_id,
            )
            .where(GraphFact.id.in_([ref["answer_fact_id"] for _, ref in bound]))
        )
    ).all()
    answers = {fact.id: (fact, node) for fact, node in rows}
    runs = {
        run.id: run
        for run in await session.scalars(
            select(ExecutionRun).where(
                ExecutionRun.id.in_({attempt.run_id for attempt, _ref in bound})
            )
        )
    }
    output = []
    for attempt, ref in bound:
        fact, node = answers[ref["answer_fact_id"]]
        if (
            node.attributes["evidence_set_id"] != attempt.evidence_set_id
            or fact.scope_key != node.scope_key
            or fact.scope_key != f"customer:{runs[attempt.run_id].customer_id}"
        ):
            raise RuntimeError("Research reuse reference does not match its frozen result")
        output.append((attempt, ref, node.attributes))
    return output


def evidence_refs(payload: dict) -> list[str]:
    return [item["evidence_id"] for item in payload["basis"]]


def virtual_need(attempt: ExecutionAttempt, ref: dict) -> ResearchRuntimeNeed:
    from app.services.research.followup import RuntimeResearchNeed

    data = asdict(
        RuntimeResearchNeed(
            research_need_id=ref["need_id"],
            question=ref["question"],
            why_needed=ref["why_needed"],
            source_types=ref["source_types"],
            knowledge_question_id=ref["knowledge_question_id"],
        )
    )
    data.pop("generated_from", None)
    return ResearchRuntimeNeed(
        id=f"reuse:{attempt.id}",
        attempt_id=attempt.id,
        created_at=attempt.created_at,
        **data,
    )


async def project_needs(
    session: AsyncSession, rows: list[ResearchRuntimeNeed], attempts: list[ExecutionAttempt]
) -> list[ResearchRuntimeNeed]:
    return [
        *rows,
        *[
            virtual_need(attempt, ref)
            for attempt, ref, _payload in await reuse_payloads(session, attempts)
            if not any(row.attempt_id == attempt.id for row in rows)
        ],
    ]


async def project_assessments(
    session: AsyncSession, rows: list[ResearchAssessment], attempts: list[ExecutionAttempt]
) -> list[ResearchAssessment]:
    output = list(rows)
    for attempt, ref, payload in await reuse_payloads(session, attempts):
        coverage = ref["coverage"]
        output.append(
            ResearchAssessment(
                id=f"reuse:{attempt.id}",
                attempt_id=attempt.id,
                evidence_set_id=attempt.evidence_set_id,
                assessment_pass=1,
                result="sufficient",
                rationale="Reused valid frozen research result",
                need_assessments=[
                    {
                        "research_need_id": ref["need_id"],
                        "sufficient": True,
                        "supporting_evidence_ids": evidence_refs(payload),
                        "missing_or_weak": "",
                        "contradictions": [],
                        "further_information": None,
                    }
                ],
                gaps=[],
                contradictions=[],
                considered_evidence_ids=evidence_refs(payload),
                evidence_fingerprint=ref["answer_fact_id"],
                model_provider="jev" if coverage else None,
                model_name=coverage["model"] if coverage else None,
                model_version=None,
                created_at=attempt.created_at,
            )
        )
    return output


async def project_completeness(
    session: AsyncSession, rows: list[ResearchCompletenessPass], attempts: list[ExecutionAttempt]
) -> list[ResearchCompletenessPass]:
    from app.services.research.knowledge_question import research_question_key

    output = list(rows)
    for attempt, ref, payload in await reuse_payloads(session, attempts):
        output.append(
            ResearchCompletenessPass(
                id=f"reuse:{attempt.id}",
                attempt_id=attempt.id,
                evidence_set_id=attempt.evidence_set_id,
                completeness_pass=1,
                result="complete",
                rationale="Reused valid frozen research result",
                missing_questions=[],
                considered_evidence_ids=evidence_refs(payload),
                considered_question_keys=[research_question_key(ref["question"])],
                evidence_fingerprint=ref["answer_fact_id"],
                question_fingerprint=research_question_key(ref["question"]),
                model_provider=None,
                model_name=None,
                model_version=None,
                created_at=attempt.created_at,
            )
        )
    return output


async def project_executions(
    session: AsyncSession, rows: list[ResearchNeedExecution], attempts: list[ExecutionAttempt]
) -> list[ResearchNeedExecution]:
    return [
        *rows,
        *[
            ResearchNeedExecution(
                id=f"reuse:{attempt.id}",
                attempt_id=attempt.id,
                research_need_id=ref["need_id"],
                status="completed",
                created_at=attempt.created_at,
                started_at=attempt.created_at,
                completed_at=attempt.created_at,
            )
            for attempt, ref, _payload in await reuse_payloads(session, attempts)
        ],
    ]


async def overview_assessments(
    session: AsyncSession, rows: list[ResearchAssessment], attempts: list[ExecutionAttempt]
) -> dict[str, ResearchAssessment]:
    return {row.attempt_id: row for row in await project_assessments(session, rows, attempts)}


def overview_needs(rows: list[ResearchRuntimeNeed]) -> dict[tuple[str, str], ResearchRuntimeNeed]:
    return {
        (need.attempt_id, need.knowledge_question_id): need
        for need in rows
        if need.knowledge_question_id
    }


def items_for_reuse(
    attempt: ExecutionAttempt, items: list[EvidenceSetItem], payload: dict
) -> list[EvidenceSetItem]:
    if REUSE_KEY not in attempt.input_snapshot:
        return items
    refs = set(evidence_refs(payload))
    return [item for item in items if item.original_evidence_id in refs]


async def overview_items(
    session: AsyncSession,
    attempt: ExecutionAttempt,
    items_by_set: dict,
    need_ids_by_item: dict,
    *,
    evidence_set_id: str | None,
    research_need_id: str,
) -> list[EvidenceSetItem]:
    if REUSE_KEY in attempt.input_snapshot:
        payloads = await reuse_payloads(session, [attempt])
        return items_for_reuse(attempt, items_by_set.get(evidence_set_id, []), payloads[0][2])
    return _items_for_need(
        items_by_set,
        need_ids_by_item,
        evidence_set_id=evidence_set_id,
        research_need_id=research_need_id,
    )


async def reuse_evidence_summaries(
    session: AsyncSession, evidence_set_ids: list[str], *, run_id: str | None = None
) -> dict[str, tuple[str, int, int, int]]:
    from app.database.models import EvidenceSet, ExecutionAttempt
    from app.services.execution.service import list_evidence_summaries
    from app.services.research.result_execution import may_attach_reused_set

    scoped = await list_evidence_summaries(session, evidence_set_ids, run_id=run_id)
    if run_id is None or len(scoped) == len(set(evidence_set_ids)):
        return scoped
    rows = (
        await session.execute(
            select(ExecutionAttempt, EvidenceSet)
            .join(
                EvidenceSet,
                EvidenceSet.id == ExecutionAttempt.evidence_set_id,
            )
            .where(
                ExecutionAttempt.run_id == run_id,
                EvidenceSet.id.in_(set(evidence_set_ids) - scoped.keys()),
            )
        )
    ).all()
    allowed = [
        frozen.id
        for attempt, frozen in rows
        if await may_attach_reused_set(session, attempt, frozen)
    ]
    return {**scoped, **await list_evidence_summaries(session, allowed)}


def _items_for_need(
    items_by_set: dict[str, list[EvidenceSetItem]],
    need_ids_by_item: dict[str, set[str]],
    *,
    evidence_set_id: str | None,
    research_need_id: str,
) -> list[EvidenceSetItem]:
    if not evidence_set_id:
        return []
    return [
        item
        for item in items_by_set.get(evidence_set_id, [])
        if research_need_id in need_ids_by_item.get(item.id, set())
    ]


async def project_attempt_rows[T](
    session: AsyncSession,
    rows: list[T],
    attempt_ids: list[str],
    projector: Callable[[AsyncSession, list[T], list[ExecutionAttempt]], Awaitable[list[T]]],
) -> list[T]:
    attempts = list(
        await session.scalars(select(ExecutionAttempt).where(ExecutionAttempt.id.in_(attempt_ids)))
    )
    return await projector(session, rows, attempts)
