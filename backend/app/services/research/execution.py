"""Attempt-scoped research orchestration. No panel, Word, or UI.

Initial ResearchNeed rows execute concurrently with a bounded limit.
Each need persists its own evidence before the Attempt-level barrier
freezes the EvidenceSet. Follow-up waves can later seed more
ResearchNeedExecution rows while the Attempt is still researching.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database.models import (
    EvidenceSet,
    EvidenceSetItem,
    ExecutionAttempt,
    ExecutionRun,
    ResearchAssessment,
    ResearchNeedExecution,
    ResearchRuntimeNeed,
)
from app.services.execution.errors import ExecutionStatusError
from app.services.execution.models import (
    INITIAL_RESEARCH_WAVE,
    TERMINAL_NEED_EXECUTION_STATUSES,
)
from app.services.execution.service import (
    add_evidence_items,
    attach_evidence_set,
    claim_attempt_researching,
    claim_freeze_evidence_set,
    claim_need_execution_running,
    complete_need_execution,
    create_evidence_set,
    fail_attempt,
    fail_evidence_set,
    fail_need_execution,
    fail_open_need_executions,
    get_attempt,
    get_evidence_set,
    get_need_execution,
    get_research_assessment,
    get_run,
    list_evidence_items,
    list_need_executions,
    list_runtime_needs,
    mark_ready,
    persist_research_assessment,
    persist_runtime_needs,
    runtime_need_from_row,
    seed_need_executions,
    set_research_loop_state,
)
from app.services.knowledge.models import KnowledgeScope
from app.services.research.assessment import (
    AssessableEvidence,
    ProgrammaticResearchAssessor,
    ResearchAssessmentError,
    ResearchAssessor,
    assessment_draft_from_row,
    evidence_fingerprint,
    sanitize_assessment_draft,
)
from app.services.research.followup import (
    FollowUpPlannerError,
    FollowUpResearchPlanner,
    NoOpFollowUpPlanner,
    RuntimeResearchNeed,
    next_assessment_pass,
    plan_from_runtime_needs,
    runtime_needs_from_plan,
    take_needs_within_budget,
    validate_follow_up_drafts,
)
from app.services.research.models import (
    InvalidResearchPlanError,
    ResearchContext,
    ResearchError,
    ResearchEvidence,
    ResearchNeed,
    ResearchPlan,
)
from app.services.research.plan import (
    research_plan_from_snapshot,
    research_plan_to_snapshot,
    validate_research_plan,
)
from app.services.research.router import ResearchRouter

ResearchRouterFactory = Callable[[AsyncSession], ResearchRouter]


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


def _concurrency_limit(value: int | None) -> int:
    limit = settings.research_need_concurrency if value is None else value
    if limit < 1:
        raise ValueError("research_need_concurrency must be >= 1")
    return limit


def _session_factory(session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    bind = session.bind
    if bind is None:
        raise ResearchExecutionError("AsyncSession has no bind; cannot open worker sessions")
    return async_sessionmaker(bind, expire_on_commit=False, class_=AsyncSession)


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
    attempt = await get_attempt(session, attempt_id)
    if attempt.status in {"ready", "running", "completed"}:
        return
    if evidence_set_id is not None:
        evidence_set = await get_evidence_set(session, evidence_set_id)
        if evidence_set.status == "building":
            await fail_evidence_set(session, evidence_set_id)
    await fail_open_need_executions(session, attempt_id)
    attempt = await get_attempt(session, attempt_id)
    if attempt.status == "researching":
        await fail_attempt(session, attempt_id)
    await session.commit()


async def _retrieve_need(
    *,
    factory: async_sessionmaker[AsyncSession],
    need: ResearchNeed,
    context: ResearchContext,
    router: ResearchRouter | None,
    router_factory: ResearchRouterFactory | None,
) -> list[ResearchEvidence]:
    if router_factory is not None:
        async with factory() as retrieve_session:
            worker_router = router_factory(retrieve_session)
            return await worker_router.execute_need(need, context)
    if router is None:
        raise ResearchExecutionError("ResearchRouter is required")
    return await router.execute_need(need, context)


async def _execute_one_need(
    *,
    factory: async_sessionmaker[AsyncSession],
    persist_lock: asyncio.Lock,
    retrieve_slots: asyncio.Semaphore,
    execution_id: str,
    need: ResearchNeed,
    context: ResearchContext,
    evidence_set_id: str,
    router: ResearchRouter | None,
    router_factory: ResearchRouterFactory | None,
) -> None:
    async with persist_lock, factory() as claim_session:
        row = await claim_need_execution_running(claim_session, execution_id)
        await claim_session.commit()
        if row.status in TERMINAL_NEED_EXECUTION_STATUSES:
            return

    try:
        async with retrieve_slots:
            evidence = await _retrieve_need(
                factory=factory,
                need=need,
                context=context,
                router=router,
                router_factory=router_factory,
            )
    except BaseException:
        async with persist_lock, factory() as fail_session:
            await fail_need_execution(fail_session, execution_id)
            await fail_session.commit()
        raise

    async with persist_lock, factory() as persist_session:
        row = await get_need_execution(persist_session, execution_id)
        if row.status in TERMINAL_NEED_EXECUTION_STATUSES:
            return
        await add_evidence_items(
            persist_session,
            evidence_set_id=evidence_set_id,
            items=evidence,
        )
        await complete_need_execution(persist_session, execution_id)
        await persist_session.commit()


async def _run_need_executions(
    *,
    factory: async_sessionmaker[AsyncSession],
    pending: list[tuple[str, str]],
    evidence_set_id: str,
    plan: ResearchPlan,
    context: ResearchContext,
    router: ResearchRouter | None,
    router_factory: ResearchRouterFactory | None,
    concurrency: int,
) -> None:
    if not pending:
        return
    needs_by_id = {need.id: need for need in plan.needs}
    persist_lock = asyncio.Lock()
    retrieve_slots = asyncio.Semaphore(concurrency)

    async def worker(execution_id: str, need_id: str) -> None:
        need = needs_by_id[need_id]
        await _execute_one_need(
            factory=factory,
            persist_lock=persist_lock,
            retrieve_slots=retrieve_slots,
            execution_id=execution_id,
            need=need,
            context=context,
            evidence_set_id=evidence_set_id,
            router=router,
            router_factory=router_factory,
        )

    await asyncio.gather(
        *(worker(execution_id, need_id) for execution_id, need_id in pending)
    )


def assessable_from_item(item: EvidenceSetItem) -> AssessableEvidence:
    return AssessableEvidence(
        evidence_id=item.original_evidence_id or item.id,
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
        provenance=dict(item.provenance or {}),
        retrieved_at=item.retrieved_at,
        content_hash=item.content_hash,
    )


def _loop_limits(
    max_follow_up_waves: int | None, max_needs: int | None
) -> tuple[int, int]:
    waves = (
        settings.research_max_follow_up_waves
        if max_follow_up_waves is None
        else max_follow_up_waves
    )
    needs = (
        settings.research_max_needs_per_attempt if max_needs is None else max_needs
    )
    if waves < 0:
        raise ValueError("research_max_follow_up_waves must be >= 0")
    if needs < 1:
        raise ValueError("research_max_needs_per_attempt must be >= 1")
    return waves, needs


async def _pending_need_pairs(
    session: AsyncSession, attempt_id: str
) -> list[tuple[str, str]]:
    return [
        (row.id, row.research_need_id)
        for row in await list_need_executions(session, attempt_id)
        if row.status not in TERMINAL_NEED_EXECUTION_STATUSES
    ]


async def _runtime_plan(session: AsyncSession, attempt_id: str) -> ResearchPlan:
    rows = await list_runtime_needs(session, attempt_id)
    return plan_from_runtime_needs([runtime_need_from_row(row) for row in rows])


async def _assess_persisted_evidence(
    session: AsyncSession,
    *,
    attempt: ExecutionAttempt,
    evidence_set_id: str,
    plan: ResearchPlan,
    assessor: ResearchAssessor,
    assessment_pass: int,
) -> ResearchAssessment:
    """Judge persisted EvidenceSet items. Insufficient is a valid outcome."""
    existing = await get_research_assessment(
        session, attempt.id, assessment_pass=assessment_pass
    )
    if existing is not None:
        return existing
    items = await list_evidence_items(session, evidence_set_id)
    evidence = [assessable_from_item(item) for item in items]
    try:
        draft = await assessor.assess(plan, evidence)
    except ResearchAssessmentError:
        raise
    except Exception as exc:
        raise ResearchAssessmentError(
            f"Attempt {attempt.id} evidence assessment failed"
        ) from exc
    draft = sanitize_assessment_draft(draft, plan=plan, evidence=evidence)
    return await persist_research_assessment(
        session,
        attempt_id=attempt.id,
        evidence_set_id=evidence_set_id,
        draft=draft,
        evidence_fingerprint=evidence_fingerprint(evidence),
        assessment_pass=assessment_pass,
    )


async def _assert_need_barrier(
    session: AsyncSession, *, attempt_id: str, evidence_set_id: str
) -> None:
    executions = await list_need_executions(session, attempt_id)
    if any(row.status == "failed" for row in executions):
        raise ResearchExecutionError(
            f"Attempt {attempt_id} research failed: a need execution failed"
        )
    if any(row.status not in TERMINAL_NEED_EXECUTION_STATUSES for row in executions):
        raise ResearchExecutionError(
            f"Attempt {attempt_id} research barrier not met; EvidenceSet stays building"
        )
    if any(row.status != "completed" for row in executions):
        raise ResearchExecutionError(
            f"Attempt {attempt_id} research failed: need executions are not completed"
        )
    evidence_set = await get_evidence_set(session, evidence_set_id)
    if evidence_set.status != "building":
        raise ResearchExecutionError(
            f"Attempt {attempt_id} EvidenceSet {evidence_set_id} left building "
            f"(status={evidence_set.status}) before the research loop stopped"
        )


async def _freeze_ready_attempt(
    session: AsyncSession,
    *,
    attempt_id: str,
    evidence_set_id: str,
) -> None:
    attempt = await get_attempt(session, attempt_id)
    if attempt.status == "ready":
        return
    frozen = await claim_freeze_evidence_set(session, evidence_set_id)
    if frozen is None:
        evidence_set = await get_evidence_set(session, evidence_set_id)
        if evidence_set.status == "frozen" and attempt.status == "researching":
            await mark_ready(session, attempt_id)
            await session.commit()
            return
        raise ResearchExecutionError(
            f"Attempt {attempt_id} cannot freeze EvidenceSet {evidence_set_id} "
            f"(status={evidence_set.status})"
        )
    if attempt.status != "researching":
        raise ResearchExecutionError(
            f"Attempt {attempt_id} cannot become ready from status={attempt.status}"
        )
    await mark_ready(session, attempt_id)
    await session.commit()


async def _plan_and_persist_follow_ups(
    session: AsyncSession,
    *,
    attempt: ExecutionAttempt,
    snapshot_plan: ResearchPlan,
    assessment: ResearchAssessment,
    evidence_set_id: str,
    planner: FollowUpResearchPlanner,
    wave_number: int,
    max_needs: int,
) -> list[RuntimeResearchNeed] | str:
    previous = [runtime_need_from_row(row) for row in await list_runtime_needs(session, attempt.id)]
    if len(previous) >= max_needs:
        return "max_needs"
    items = await list_evidence_items(session, evidence_set_id)
    evidence = [assessable_from_item(item) for item in items]
    draft = assessment_draft_from_row(assessment)
    try:
        raw_drafts = await planner.plan_follow_ups(
            plan=snapshot_plan,
            assessment=draft,
            evidence=evidence,
            previous_needs=previous,
        )
    except FollowUpPlannerError:
        raise
    except Exception as exc:
        raise FollowUpPlannerError(
            f"Attempt {attempt.id} follow-up planning failed"
        ) from exc
    accepted = validate_follow_up_drafts(
        raw_drafts,
        previous_needs=previous,
        wave_number=wave_number,
        assessment_pass=assessment.assessment_pass,
    )
    accepted = take_needs_within_budget(
        accepted, current_count=len(previous), max_needs=max_needs
    )
    if not accepted:
        return "no_novel_followups" if len(previous) < max_needs else "max_needs"
    await persist_runtime_needs(session, attempt_id=attempt.id, needs=accepted)
    seeded = await seed_need_executions(
        session,
        attempt_id=attempt.id,
        need_ids=[need.research_need_id for need in accepted],
    )
    pending = [
        row.research_need_id
        for row in seeded
        if row.research_need_id in {need.research_need_id for need in accepted}
        and row.status not in TERMINAL_NEED_EXECUTION_STATUSES
    ]
    if not pending:
        return "no_novel_followups"
    return accepted


async def _run_research_loop(
    *,
    factory: async_sessionmaker[AsyncSession],
    attempt_id: str,
    evidence_set_id: str,
    snapshot_plan: ResearchPlan,
    context: ResearchContext,
    router: ResearchRouter | None,
    router_factory: ResearchRouterFactory | None,
    assessor: ResearchAssessor,
    planner: FollowUpResearchPlanner,
    concurrency: int,
    max_follow_up_waves: int,
    max_needs: int,
) -> None:
    wave = INITIAL_RESEARCH_WAVE
    while True:
        async with factory() as wave_session:
            pending = await _pending_need_pairs(wave_session, attempt_id)
            runtime_plan = await _runtime_plan(wave_session, attempt_id)
            if not runtime_plan.needs:
                runtime_plan = snapshot_plan
        if pending:
            await _run_need_executions(
                factory=factory,
                pending=pending,
                evidence_set_id=evidence_set_id,
                plan=runtime_plan,
                context=context,
                router=router,
                router_factory=router_factory,
                concurrency=concurrency,
            )
        async with factory() as barrier_session:
            await _assert_need_barrier(
                barrier_session, attempt_id=attempt_id, evidence_set_id=evidence_set_id
            )
            attempt = await get_attempt(barrier_session, attempt_id)
            if attempt.status == "ready":
                return
            if attempt.research_plan_snapshot is not None:
                snapshot_plan = research_plan_from_snapshot(attempt.research_plan_snapshot)
            assessment = await _assess_persisted_evidence(
                barrier_session,
                attempt=attempt,
                evidence_set_id=evidence_set_id,
                plan=snapshot_plan,
                assessor=assessor,
                assessment_pass=next_assessment_pass(wave),
            )
            await set_research_loop_state(
                barrier_session,
                attempt_id,
                research_wave=wave,
                stop_reason=None,
            )
            await barrier_session.commit()

            if assessment.result == "sufficient":
                await set_research_loop_state(
                    barrier_session,
                    attempt_id,
                    research_wave=wave,
                    stop_reason="sufficient",
                )
                await _freeze_ready_attempt(
                    barrier_session,
                    attempt_id=attempt_id,
                    evidence_set_id=evidence_set_id,
                )
                return

            if wave >= max_follow_up_waves:
                await set_research_loop_state(
                    barrier_session,
                    attempt_id,
                    research_wave=wave,
                    stop_reason="max_iterations",
                )
                await _freeze_ready_attempt(
                    barrier_session,
                    attempt_id=attempt_id,
                    evidence_set_id=evidence_set_id,
                )
                return

            follow_up_wave = wave + 1
            planned = await _plan_and_persist_follow_ups(
                barrier_session,
                attempt=attempt,
                snapshot_plan=snapshot_plan,
                assessment=assessment,
                evidence_set_id=evidence_set_id,
                planner=planner,
                wave_number=follow_up_wave,
                max_needs=max_needs,
            )
            if isinstance(planned, str):
                await set_research_loop_state(
                    barrier_session,
                    attempt_id,
                    research_wave=wave,
                    stop_reason=planned,
                )
                await _freeze_ready_attempt(
                    barrier_session,
                    attempt_id=attempt_id,
                    evidence_set_id=evidence_set_id,
                )
                return
            await set_research_loop_state(
                barrier_session,
                attempt_id,
                research_wave=follow_up_wave,
                stop_reason=None,
            )
            await barrier_session.commit()
            wave = follow_up_wave


async def execute_attempt_research(
    session: AsyncSession,
    *,
    attempt_id: str,
    research_plan: ResearchPlan,
    router: ResearchRouter | None = None,
    router_factory: ResearchRouterFactory | None = None,
    assessor: ResearchAssessor | None = None,
    planner: FollowUpResearchPlanner | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    concurrency: int | None = None,
    max_follow_up_waves: int | None = None,
    max_needs: int | None = None,
) -> AttemptResearchResult:
    """Run ResearchNeeds in bounded waves, assess, and freeze once the loop stops.

    Scope is always taken from ExecutionRun. Source-level error/not_found
    complete that need and do not fail the Attempt. A sufficient assessment or
    an explicit research-budget stop freezes the EvidenceSet and marks the
    Attempt ready. Assessor/planner/model/parsing/worker failure marks both
    Attempt and EvidenceSet failed without freezing.
    """
    if router is None and router_factory is None:
        raise ResearchExecutionError("ResearchRouter is required")

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
    bound_assessor = assessor or ProgrammaticResearchAssessor()
    bound_planner = planner or NoOpFollowUpPlanner()
    wave_limit, need_limit = _loop_limits(max_follow_up_waves, max_needs)
    if len(plan.needs) > need_limit:
        raise InvalidResearchPlanError(
            f"ResearchPlan has {len(plan.needs)} needs; "
            f"research_max_needs_per_attempt={need_limit}"
        )
    run = await get_run(session, attempt.run_id)
    need_concurrency = _concurrency_limit(concurrency)
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
        await persist_runtime_needs(
            session,
            attempt_id=attempt.id,
            needs=runtime_needs_from_plan(plan),
        )
        await seed_need_executions(
            session,
            attempt_id=attempt.id,
            need_ids=[need.id for need in plan.needs],
        )
        context = research_context_from_run(run)
        factory = session_factory or _session_factory(session)
        await session.commit()

        await _run_research_loop(
            factory=factory,
            attempt_id=attempt_id,
            evidence_set_id=evidence_set.id,
            snapshot_plan=plan,
            context=context,
            router=router,
            router_factory=router_factory,
            assessor=bound_assessor,
            planner=bound_planner,
            concurrency=need_concurrency,
            max_follow_up_waves=wave_limit,
            max_needs=need_limit,
        )
        async with factory() as final_session:
            result = await _result_from_attempt(
                final_session, await get_attempt(final_session, attempt_id)
            )
        await _refresh_caller_state(session, attempt_id, evidence_set_id)
        return result
    except BaseException as exc:
        if isinstance(exc, ExecutionStatusError) and not claimed:
            raise
        await session.rollback()
        if claimed:
            factory = session_factory or _session_factory(session)
            async with factory() as fail_session:
                await _fail_claimed_research(
                    fail_session,
                    attempt_id=attempt_id,
                    evidence_set_id=evidence_set_id,
                )
            await _refresh_caller_state(session, attempt_id, evidence_set_id)
        if isinstance(exc, Exception):
            raise ResearchExecutionError(f"Attempt {attempt_id} research failed") from exc
        raise


async def _refresh_caller_state(
    session: AsyncSession,
    attempt_id: str,
    evidence_set_id: str | None,
) -> None:
    cached_attempt = await session.get(ExecutionAttempt, attempt_id)
    if cached_attempt is not None:
        await session.refresh(cached_attempt)
    if evidence_set_id is None:
        return
    cached_set = await session.get(EvidenceSet, evidence_set_id)
    if cached_set is not None:
        await session.refresh(cached_set)
    cached_needs = await session.execute(
        select(ResearchNeedExecution).where(
            ResearchNeedExecution.attempt_id == attempt_id
        )
    )
    for row in cached_needs.scalars():
        session.expire(row)
    cached_runtime = await session.execute(
        select(ResearchRuntimeNeed).where(ResearchRuntimeNeed.attempt_id == attempt_id)
    )
    for row in cached_runtime.scalars():
        session.expire(row)
    cached_assessments = await session.execute(
        select(ResearchAssessment).where(ResearchAssessment.attempt_id == attempt_id)
    )
    for row in cached_assessments.scalars():
        session.expire(row)
