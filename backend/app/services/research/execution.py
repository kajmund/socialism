"""Attempt-scoped research orchestration. No panel, Word, or UI."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import EvidenceSetItem, ExecutionAttempt, ExecutionRun
from app.services.execution.errors import ExecutionStatusError
from app.services.execution.service import (
    add_evidence_items,
    attach_evidence_set,
    claim_attempt_researching,
    create_evidence_set,
    fail_attempt,
    fail_evidence_set,
    freeze_evidence_set,
    get_attempt,
    get_run,
    list_evidence_items,
    mark_ready,
)
from app.services.knowledge.models import KnowledgeScope
from app.services.research.models import ResearchContext, ResearchError, ResearchPlan
from app.services.research.plan import research_plan_to_snapshot, validate_research_plan
from app.services.research.router import ResearchRouter


class ResearchExecutionError(ResearchError):
    """Orchestration could not finish; Attempt and EvidenceSet are marked failed."""


@dataclass(frozen=True)
class AttemptResearchResult:
    attempt_id: str
    evidence_set_id: str | None
    status: str
    found_count: int
    not_found_count: int
    error_count: int


def research_context_from_run(run: ExecutionRun) -> ResearchContext:
    """Tenant scope comes from the Run only. Callers cannot override it."""
    raw = run.context if isinstance(run.context, dict) else {}
    case_id = raw.get("case_id")
    if case_id is not None:
        text = str(case_id).strip()
        case_id = text or None
    else:
        case_id = None
    return ResearchContext(
        scope=KnowledgeScope(
            customer_id=run.customer_id,
            case_id=case_id,
            module=run.module,
        )
    )


def _counts(items: list[EvidenceSetItem]) -> tuple[int, int, int]:
    found = sum(1 for item in items if item.status == "found")
    not_found = sum(1 for item in items if item.status == "not_found")
    error = sum(1 for item in items if item.status == "error")
    return found, not_found, error


async def _result_from_attempt(
    session: AsyncSession,
    attempt: ExecutionAttempt,
) -> AttemptResearchResult:
    items: list[EvidenceSetItem] = []
    if attempt.evidence_set_id is not None:
        items = await list_evidence_items(session, attempt.evidence_set_id)
    found, not_found, error = _counts(items)
    return AttemptResearchResult(
        attempt_id=attempt.id,
        evidence_set_id=attempt.evidence_set_id,
        status=attempt.status,
        found_count=found,
        not_found_count=not_found,
        error_count=error,
    )


async def _fail_claimed_research(
    session: AsyncSession,
    *,
    attempt_id: str,
    evidence_set_id: str | None,
) -> None:
    if evidence_set_id is not None:
        await fail_evidence_set(session, evidence_set_id)
    attempt = await get_attempt(session, attempt_id)
    if attempt.status == "researching":
        await fail_attempt(session, attempt_id)
    await session.commit()


async def execute_attempt_research(
    session: AsyncSession,
    *,
    attempt_id: str,
    research_plan: ResearchPlan,
    router: ResearchRouter,
) -> AttemptResearchResult:
    """Run ResearchPlan through ResearchRouter and freeze an EvidenceSet.

    Scope is always taken from ExecutionRun. Source-level error/not_found
    stay on the Attempt as ready. Orchestration failure marks both failed.
    """
    attempt = await get_attempt(session, attempt_id)
    if attempt.status == "ready":
        return await _result_from_attempt(session, attempt)
    if attempt.status == "researching":
        raise ExecutionStatusError(
            f"Attempt {attempt.id} research is already in progress"
        )
    if attempt.status != "created":
        raise ExecutionStatusError(
            f"Cannot start research on attempt {attempt.id} with status={attempt.status}"
        )

    plan = validate_research_plan(research_plan)
    run = await get_run(session, attempt.run_id)
    claimed = False
    evidence_set_id: str | None = None
    try:
        attempt = await claim_attempt_researching(
            session,
            attempt_id,
            research_plan_snapshot=research_plan_to_snapshot(plan),
        )
        if attempt.status == "ready":
            return await _result_from_attempt(session, attempt)
        claimed = True
        evidence_set = await create_evidence_set(
            session,
            run_id=run.id,
            created_from_attempt_id=attempt.id,
        )
        evidence_set_id = evidence_set.id
        await attach_evidence_set(
            session,
            attempt_id=attempt.id,
            evidence_set_id=evidence_set.id,
        )
        await session.commit()

        context = research_context_from_run(run)
        collected = []
        for need in plan.needs:
            collected.extend(await router.execute_need(need, context))

        await add_evidence_items(
            session,
            evidence_set_id=evidence_set.id,
            items=collected,
        )
        await freeze_evidence_set(session, evidence_set.id)
        await mark_ready(session, attempt.id)
        await session.commit()
        return await _result_from_attempt(session, await get_attempt(session, attempt.id))
    except Exception as exc:
        if isinstance(exc, ExecutionStatusError) and not claimed:
            raise
        await session.rollback()
        if claimed:
            await _fail_claimed_research(
                session,
                attempt_id=attempt_id,
                evidence_set_id=evidence_set_id,
            )
        raise ResearchExecutionError(f"Attempt {attempt_id} research failed") from exc
