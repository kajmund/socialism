"""Materialize a frozen answer's original sources and legal interpretations."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import ExecutionAttempt, ExecutionRun

from app.services.execution.service import list_evidence_items
from app.services.research.answer_graph import publish_answer
from app.services.research.knowledge_question import identity_from_text, tenant_question_scope
from app.services.research.models import research_evidence
from app.services.research.question_graph_sql import SqlQuestionEvidenceGraph


async def project_groups(
    session: AsyncSession,
    *,
    attempt: ExecutionAttempt,
    run: ExecutionRun,
    groups: dict,
    evidence_set_id: str,
) -> None:
    from app.database.models import (
        KnowledgeQuestionRow,
        ResearchAssessment,
        ResearchCompletenessPass,
    )
    from app.services.research.execution import assessable_from_item, research_context_from_run

    items = await list_evidence_items(session, evidence_set_id)
    assessment = await session.scalar(
        select(ResearchAssessment)
        .where(ResearchAssessment.attempt_id == attempt.id)
        .order_by(ResearchAssessment.assessment_pass.desc())
        .limit(1)
    )
    completeness = await session.scalar(
        select(ResearchCompletenessPass)
        .where(ResearchCompletenessPass.attempt_id == attempt.id)
        .order_by(ResearchCompletenessPass.completeness_pass.desc())
        .limit(1)
    )
    graph = SqlQuestionEvidenceGraph()
    scope = tenant_question_scope(run.customer_id, run.context.get("workspace_id"))
    objective = (attempt.research_objective_snapshot or {}).get("objective")
    for key, basis in groups.items():
        canonical = await session.scalar(
            select(KnowledgeQuestionRow).where(
                KnowledgeQuestionRow.namespace == scope.namespace,
                KnowledgeQuestionRow.identity_key == key,
            )
        )
        if canonical is None:
            question = await graph.upsert_question(
                session,
                identity_from_text(basis["question"]),
                scope,
            )
            canonical = await session.get(KnowledgeQuestionRow, question.id)
        refs = {
            tuple(row.get(field) for field in ("source_type", "source_id", "source_url", "locator", "content_hash"))
            for row in basis["evidence"]
        }
        relevant = [
            row
            for row in items
            if row.status == "found"
            and (
                basis["question"] == objective
                or (row.source_type, row.source_id, row.source_url, row.locator, row.content_hash) in refs
            )
        ]
        rich = []
        for item in relevant:
            data = assessable_from_item(item)
            rich.append(
                research_evidence(
                    research_need_id=data.research_need_id,
                    source_type=data.source_type,
                    status=data.status,
                    title=data.title,
                    excerpt=data.excerpt,
                    locator=data.locator,
                    source_id=data.source_id,
                    source_url=data.source_url,
                    provider=data.provider,
                    score=data.score,
                    retrieved_at=data.retrieved_at,
                    metadata=data.provenance,
                    legal_result=data.legal_result,
                )
            )
        from app.database.models import ResearchRuntimeNeed

        need_ids = set(
            await session.scalars(
                select(ResearchRuntimeNeed.research_need_id).where(
                    ResearchRuntimeNeed.attempt_id == attempt.id,
                    ResearchRuntimeNeed.question_key == key,
                )
            )
        )
        assessed = [
            row
            for row in (assessment.need_assessments if assessment else [])
            if row["research_need_id"] in need_ids
        ]
        refs = {row.evidence_id for row in rich}
        sufficient = bool(assessed) and all(
            row.get("sufficient")
            and set(row.get("supporting_evidence_ids", [])).intersection(refs)
            and not row.get("contradictions")
            for row in assessed
        )
        if basis["question"] == objective and completeness is not None:
            sufficient = sufficient and completeness.result == "complete"
        await publish_answer(
            session,
            question=canonical,
            context=research_context_from_run(run),
            evidence_set_id=evidence_set_id,
            basis=rich,
            assessment={
                "sufficient": bool(sufficient),
                "needs": assessed,
            },
        )
