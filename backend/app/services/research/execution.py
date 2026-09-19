"""Attempt-scoped research orchestration. No panel, Word, or UI.

Initial ResearchNeed rows execute concurrently with a bounded limit.
Each need persists its own evidence before the Attempt-level barrier
freezes the EvidenceSet. Follow-up waves can later seed more
ResearchNeedExecution rows while the Attempt is still researching.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from contextvars import ContextVar
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
    ResearchCompletenessPass,
    ResearchEvidenceQuality,
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
    get_research_completeness,
    get_research_completeness_by_fingerprint,
    get_run,
    list_evidence_items,
    list_evidence_quality,
    list_need_executions,
    list_research_assessments,
    list_research_completeness_passes,
    list_runtime_needs,
    mark_ready,
    persist_evidence_quality,
    persist_research_assessment,
    persist_research_completeness,
    persist_runtime_needs,
    runtime_need_from_row,
    seed_need_executions,
    set_attempt_snapshots,
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
from app.services.research.completeness import (
    GLOBAL_NEED_ORIGIN,
    ProgrammaticResearchCompletenessReviewer,
    ResearchCompletenessError,
    ResearchCompletenessReviewer,
    completeness_draft_from_row,
    has_capability_unavailable_gap,
    missing_questions_to_follow_up_drafts,
    next_completeness_pass,
    question_fingerprint,
    sanitize_completeness_draft,
)
from app.services.research.composition import standard_available_source_types
from app.services.research.provider import filter_source_types_for_scope
from app.services.research.registry import standard_capability_descriptors
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
from app.services.research.planner import (
    InvalidResearchObjectiveError,
    ResearchObjective,
    ResearchPlanner,
    ResearchPlannerError,
    plan_from_planner_drafts,
    research_objective_from_snapshot,
    research_objective_to_snapshot,
)
from app.services.research.progress import (
    ProgressTracker,
    emit_assessment_persisted,
    emit_capability_unavailable,
    emit_completeness_persisted,
    emit_evidence_item,
    emit_initial_plan_accepted,
    emit_need_completed,
    emit_need_failed,
    emit_need_queued,
    emit_need_running,
    emit_objective_accepted,
    emit_research_failed,
    emit_research_frozen_ready,
    emit_runtime_need_created,
)
from app.services.research.provider import KnowledgeProviderDescriptor
from app.services.research.quality import (
    EVIDENCE_QUALITY_POLICY_VERSION,
    EvidenceQualityDraft,
    EvidenceRelevanceAssessor,
    QualityEvidenceInput,
    QualityFlag,
    assess_evidence_quality,
    quality_model_identity_key,
)
from app.services.research.question_graph import (
    DisabledQuestionEvidenceGraph,
    QuestionEvidenceGraph,
)
from app.services.research.question_reuse import (
    merge_reused_with_provider,
    safe_lookup_reusable_evidence,
    safe_upsert_persisted_evidence,
    should_skip_providers,
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
    knowledge_module = str(raw.get("knowledge_module") or run.module).strip()
    return ResearchContext(
        scope=KnowledgeScope(
            customer_id=run.customer_id,
            case_id=case_id,
            module=knowledge_module,
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


_write_fence: ContextVar[asyncio.Event | None] = ContextVar(
    "research_write_fence", default=None
)


def _raise_if_write_fenced() -> None:
    fence = _write_fence.get()
    if fence is not None and fence.is_set():
        raise asyncio.CancelledError


async def fail_incomplete_research(
    session: AsyncSession,
    *,
    attempt_id: str,
    evidence_set_id: str | None = None,
) -> None:
    """Fail-close created or researching research. No-op for terminal Attempt."""
    attempt = await get_attempt(session, attempt_id)
    if attempt.status not in {"created", "researching"}:
        return
    _raise_if_write_fenced()
    with ProgressTracker() as progress:
        target_set_id = evidence_set_id or attempt.evidence_set_id
        if target_set_id is not None:
            evidence_set = await get_evidence_set(session, target_set_id)
            if evidence_set.status == "building":
                await fail_evidence_set(session, target_set_id)
        failed_needs = await fail_open_need_executions(session, attempt_id)
        for row in failed_needs:
            if row.status == "failed":
                await emit_need_failed(session, execution=row)
        attempt = await get_attempt(session, attempt_id)
        if attempt.status in {"created", "researching"}:
            await fail_attempt(session, attempt_id)
            await emit_research_failed(session, attempt_id=attempt_id)
        await session.commit()
        await progress.publish_committed()


async def _fail_claimed_research(
    session: AsyncSession,
    *,
    attempt_id: str,
    evidence_set_id: str | None,
) -> None:
    await fail_incomplete_research(
        session, attempt_id=attempt_id, evidence_set_id=evidence_set_id
    )


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


async def _candidates_then_providers(
    *,
    factory: async_sessionmaker[AsyncSession],
    need: ResearchNeed,
    context: ResearchContext,
    router: ResearchRouter | None,
    router_factory: ResearchRouterFactory | None,
    question_graph: QuestionEvidenceGraph,
    attempt_id: str,
) -> list[ResearchEvidence]:
    """Graph candidates re-enter EvidenceSet. v1 still retrieves live."""
    async with factory() as graph_session:
        reused = await safe_lookup_reusable_evidence(
            graph_session,
            graph=question_graph,
            need=need,
            context=context,
            exclude_attempt_id=attempt_id,
        )
    if reused and should_skip_providers(need, reused):
        return list(reused)
    provider = await _retrieve_need(
        factory=factory,
        need=need,
        context=context,
        router=router,
        router_factory=router_factory,
    )
    return merge_reused_with_provider(reused, provider)


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
    question_graph: QuestionEvidenceGraph,
    attempt_id: str,
) -> None:
    async with persist_lock, factory() as claim_session:
        with ProgressTracker() as progress:
            row = await claim_need_execution_running(claim_session, execution_id)
            if row.status == "running":
                await emit_need_running(claim_session, execution=row)
            await claim_session.commit()
            await progress.publish_committed()
        if row.status in TERMINAL_NEED_EXECUTION_STATUSES:
            return

    try:
        async with retrieve_slots:
            evidence = await _candidates_then_providers(
                factory=factory,
                need=need,
                context=context,
                router=router,
                router_factory=router_factory,
                question_graph=question_graph,
                attempt_id=attempt_id,
            )
    except BaseException as exc:
        if isinstance(exc, asyncio.CancelledError):
            raise
        _raise_if_write_fenced()
        async with persist_lock, factory() as fail_session:
            with ProgressTracker() as progress:
                failed = await fail_need_execution(fail_session, execution_id)
                await emit_need_failed(fail_session, execution=failed)
                await fail_session.commit()
                await progress.publish_committed()
        raise

    async with persist_lock, factory() as persist_session:
        _raise_if_write_fenced()
        with ProgressTracker() as progress:
            row = await get_need_execution(persist_session, execution_id)
            if row.status in TERMINAL_NEED_EXECUTION_STATUSES:
                return
            stored = await add_evidence_items(
                persist_session,
                evidence_set_id=evidence_set_id,
                items=evidence,
            )
            for item in stored:
                await emit_evidence_item(
                    persist_session, attempt_id=row.attempt_id, item=item
                )
            completed = await complete_need_execution(persist_session, execution_id)
            await emit_need_completed(persist_session, execution=completed)
            await persist_session.commit()
            await progress.publish_committed()

    async with persist_lock, factory() as graph_session:
        _raise_if_write_fenced()
        await safe_upsert_persisted_evidence(
            graph_session,
            graph=question_graph,
            need=need,
            context=context,
            evidence=evidence,
            source_attempt_id=attempt_id,
        )


async def _run_need_executions(
    *,
    factory: async_sessionmaker[AsyncSession],
    pending: list[tuple[str, str]],
    evidence_set_id: str,
    plan: ResearchPlan,
    context: ResearchContext,
    router: ResearchRouter | None,
    router_factory: ResearchRouterFactory | None,
    question_graph: QuestionEvidenceGraph,
    attempt_id: str,
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
            question_graph=question_graph,
            attempt_id=attempt_id,
        )

    await asyncio.gather(
        *(worker(execution_id, need_id) for execution_id, need_id in pending)
    )


async def _emit_seeded_runtime_needs(
    session: AsyncSession,
    *,
    attempt_id: str,
    accepted_ids: set[str],
    stored: list[ResearchRuntimeNeed],
    seeded: list[ResearchNeedExecution],
) -> None:
    for row in stored:
        if row.research_need_id in accepted_ids:
            await emit_runtime_need_created(session, attempt_id=attempt_id, need=row)
    for row in seeded:
        if row.research_need_id in accepted_ids:
            await emit_need_queued(session, execution=row)


def assessable_from_item(
    item: EvidenceSetItem,
    quality: EvidenceQualityDraft | None = None,
) -> AssessableEvidence:
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
        quality=quality,
    )


def quality_input_from_item(item: EvidenceSetItem) -> QualityEvidenceInput:
    return QualityEvidenceInput(
        item_id=item.id,
        original_evidence_id=item.original_evidence_id,
        research_need_id=item.research_need_id,
        source_type=item.source_type,
        status=item.status,
        title=item.title,
        excerpt=item.excerpt,
        locator=item.locator,
        source_id=item.source_id,
        source_url=item.source_url,
        provider=item.provider,
        provenance=dict(item.provenance or {}),
        retrieved_at=item.retrieved_at,
        content_hash=item.content_hash,
    )


def quality_draft_from_row(row: ResearchEvidenceQuality) -> EvidenceQualityDraft:
    raw_flags = row.flags if isinstance(row.flags, list) else []
    flags = []
    for item in raw_flags:
        if isinstance(item, dict) and item.get("code"):
            flags.append(
                QualityFlag(code=str(item["code"]), detail=str(item.get("detail") or ""))
            )
    return EvidenceQualityDraft(
        evidence_set_item_id=row.evidence_set_item_id,
        original_evidence_id=row.original_evidence_id,
        scoring_policy_version=row.scoring_policy_version,
        authority=row.authority,
        relevance=row.relevance,
        currentness=row.currentness,
        source_nature=row.source_nature,
        source_timestamp=row.source_timestamp,
        independence_key=row.independence_key,
        independent_source_count=row.independent_source_count,
        flags=flags,
        rationale=row.rationale,
        declared_signals=dict(row.declared_signals or {}),
        model_provider=row.model_provider,
        model_name=row.model_name,
        model_version=row.model_version,
    )


def _loop_limits(
    max_follow_up_waves: int | None,
    max_needs: int | None,
    max_completeness_passes: int | None = None,
) -> tuple[int, int, int]:
    waves = (
        settings.research_max_follow_up_waves
        if max_follow_up_waves is None
        else max_follow_up_waves
    )
    needs = (
        settings.research_max_needs_per_attempt if max_needs is None else max_needs
    )
    completeness = (
        settings.research_max_completeness_passes
        if max_completeness_passes is None
        else max_completeness_passes
    )
    if waves < 0:
        raise ValueError("research_max_follow_up_waves must be >= 0")
    if needs < 1:
        raise ValueError("research_max_needs_per_attempt must be >= 1")
    if completeness < 1:
        raise ValueError("research_max_completeness_passes must be >= 1")
    return waves, needs, completeness


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


def _quality_descriptors(
    router: ResearchRouter | None,
    descriptors: tuple[KnowledgeProviderDescriptor, ...] | None,
) -> tuple[KnowledgeProviderDescriptor, ...]:
    if descriptors is not None:
        return descriptors
    registered = getattr(router, "registered_descriptors", None)
    if callable(registered):
        return tuple(registered())
    return standard_capability_descriptors()


async def _persist_evidence_quality(
    session: AsyncSession,
    *,
    evidence_set_id: str,
    plan: ResearchPlan,
    descriptors: tuple[KnowledgeProviderDescriptor, ...],
    relevance_assessor: EvidenceRelevanceAssessor | None,
) -> list[EvidenceQualityDraft]:
    """Score persisted items before local sufficiency. Does not mutate items."""
    items = await list_evidence_items(session, evidence_set_id)
    existing = await list_evidence_quality(
        session,
        evidence_set_id,
        scoring_policy_version=EVIDENCE_QUALITY_POLICY_VERSION,
    )
    existing_keys = {
        (row.evidence_set_item_id, row.scoring_policy_version, row.model_identity_key)
        for row in existing
    }
    drafts = await assess_evidence_quality(
        [quality_input_from_item(item) for item in items],
        needs=plan.needs,
        descriptors=descriptors,
        relevance_assessor=relevance_assessor,
    )
    missing = [
        draft
        for draft in drafts
        if (
            draft.evidence_set_item_id,
            draft.scoring_policy_version,
            quality_model_identity_key(
                model_provider=draft.model_provider,
                model_name=draft.model_name,
                model_version=draft.model_version,
            ),
        )
        not in existing_keys
    ]
    if missing:
        await persist_evidence_quality(
            session, evidence_set_id=evidence_set_id, drafts=missing
        )
    stored = await list_evidence_quality(
        session,
        evidence_set_id,
        scoring_policy_version=EVIDENCE_QUALITY_POLICY_VERSION,
    )
    return [quality_draft_from_row(row) for row in stored]


def _quality_by_item(
    drafts: list[EvidenceQualityDraft],
) -> dict[str, EvidenceQualityDraft]:
    return {draft.evidence_set_item_id: draft for draft in drafts}


async def _assess_persisted_evidence(
    session: AsyncSession,
    *,
    attempt: ExecutionAttempt,
    evidence_set_id: str,
    plan: ResearchPlan,
    assessor: ResearchAssessor,
    assessment_pass: int,
    quality: list[EvidenceQualityDraft] | None = None,
) -> ResearchAssessment:
    """Judge persisted EvidenceSet items. Insufficient is a valid outcome."""
    existing = await get_research_assessment(
        session, attempt.id, assessment_pass=assessment_pass
    )
    if existing is not None:
        return existing
    items = await list_evidence_items(session, evidence_set_id)
    quality_map = _quality_by_item(quality or [])
    evidence = [
        assessable_from_item(item, quality=quality_map.get(item.id)) for item in items
    ]
    try:
        draft = await assessor.assess(plan, evidence)
    except ResearchAssessmentError:
        raise
    except Exception as exc:
        raise ResearchAssessmentError(
            f"Attempt {attempt.id} evidence assessment failed"
        ) from exc
    draft = sanitize_assessment_draft(draft, plan=plan, evidence=evidence)
    assessment = await persist_research_assessment(
        session,
        attempt_id=attempt.id,
        evidence_set_id=evidence_set_id,
        draft=draft,
        evidence_fingerprint=evidence_fingerprint(evidence),
        assessment_pass=assessment_pass,
    )
    await emit_assessment_persisted(session, assessment=assessment)
    return assessment


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
    _raise_if_write_fenced()
    attempt = await get_attempt(session, attempt_id)
    if attempt.status == "ready":
        return
    frozen = await claim_freeze_evidence_set(session, evidence_set_id)
    if frozen is None:
        evidence_set = await get_evidence_set(session, evidence_set_id)
        if evidence_set.status == "frozen" and attempt.status == "researching":
            ready = await mark_ready(session, attempt_id)
            await emit_research_frozen_ready(
                session,
                attempt_id=attempt_id,
                evidence_set_id=evidence_set_id,
                stop_reason=ready.research_stop_reason,
            )
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
    ready = await mark_ready(session, attempt_id)
    await emit_research_frozen_ready(
        session,
        attempt_id=attempt_id,
        evidence_set_id=evidence_set_id,
        stop_reason=ready.research_stop_reason,
    )
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
    stored = await persist_runtime_needs(session, attempt_id=attempt.id, needs=accepted)
    accepted_ids = {need.research_need_id for need in accepted}
    seeded = await seed_need_executions(
        session,
        attempt_id=attempt.id,
        need_ids=[need.research_need_id for need in accepted],
    )
    await _emit_seeded_runtime_needs(
        session,
        attempt_id=attempt.id,
        accepted_ids=accepted_ids,
        stored=stored,
        seeded=seeded,
    )
    pending = [
        row.research_need_id
        for row in seeded
        if row.research_need_id in accepted_ids
        and row.status not in TERMINAL_NEED_EXECUTION_STATUSES
    ]
    if not pending:
        return "no_novel_followups"
    return accepted


async def _review_and_persist_completeness(
    session: AsyncSession,
    *,
    attempt: ExecutionAttempt,
    evidence_set_id: str,
    snapshot_plan: ResearchPlan,
    assessment: ResearchAssessment,
    reviewer: ResearchCompletenessReviewer,
    router: ResearchRouter | None,
    case_id: str | None,
) -> ResearchCompletenessPass:
    """Judge the original objective. Incomplete is a valid outcome."""
    items = await list_evidence_items(session, evidence_set_id)
    evidence = [assessable_from_item(item) for item in items]
    runtime_rows = await list_runtime_needs(session, attempt.id)
    runtime_needs = [runtime_need_from_row(row) for row in runtime_rows]
    objective = None
    if attempt.research_objective_snapshot is not None:
        objective = research_objective_from_snapshot(attempt.research_objective_snapshot)
    evidence_fp = evidence_fingerprint(evidence)
    question_fp = question_fingerprint(runtime_needs, objective)
    matched = await get_research_completeness_by_fingerprint(
        session,
        attempt.id,
        evidence_fingerprint=evidence_fp,
        question_fingerprint=question_fp,
    )
    if matched is not None:
        return matched
    existing = await list_research_completeness_passes(session, attempt.id)
    completeness_pass = next_completeness_pass(len(existing))
    already = await get_research_completeness(
        session, attempt.id, completeness_pass=completeness_pass
    )
    if already is not None:
        return already
    history = [
        assessment_draft_from_row(row)
        for row in await list_research_assessments(session, attempt.id)
    ]
    draft = assessment_draft_from_row(assessment)
    allowed_source_types = _executable_source_types(router, case_id=case_id)
    try:
        reviewed = await reviewer.review(
            objective=objective,
            plan=snapshot_plan,
            runtime_needs=runtime_needs,
            assessment=draft,
            assessments=history,
            evidence=evidence,
            available_source_types=allowed_source_types,
        )
    except ResearchCompletenessError:
        raise
    except Exception as exc:
        raise ResearchCompletenessError(
            f"Attempt {attempt.id} completeness review failed"
        ) from exc
    reviewed = sanitize_completeness_draft(
        reviewed,
        runtime_needs=runtime_needs,
        evidence=evidence,
        allowed_source_types=allowed_source_types,
    )
    completeness = await persist_research_completeness(
        session,
        attempt_id=attempt.id,
        evidence_set_id=evidence_set_id,
        draft=reviewed,
        evidence_fingerprint=evidence_fp,
        question_fingerprint=question_fp,
        completeness_pass=completeness_pass,
    )
    await emit_completeness_persisted(session, completeness=completeness)
    return completeness


async def _plan_and_persist_global_needs(
    session: AsyncSession,
    *,
    attempt: ExecutionAttempt,
    completeness: ResearchCompletenessPass,
    wave_number: int,
    max_needs: int,
    router: ResearchRouter | None,
    case_id: str | None,
) -> list[RuntimeResearchNeed] | str:
    previous = [runtime_need_from_row(row) for row in await list_runtime_needs(session, attempt.id)]
    if len(previous) >= max_needs:
        return "max_needs"
    draft = completeness_draft_from_row(completeness)
    allowed_source_types = _executable_source_types(router, case_id=case_id)
    runnable = [row for row in draft.missing_questions if row.source_types]
    accepted = validate_follow_up_drafts(
        missing_questions_to_follow_up_drafts(runnable),
        previous_needs=previous,
        wave_number=wave_number,
        origin=GLOBAL_NEED_ORIGIN,
        source_completeness_pass=completeness.completeness_pass,
        id_prefix="global",
        allowed_source_types=allowed_source_types,
    )
    accepted = take_needs_within_budget(
        accepted, current_count=len(previous), max_needs=max_needs
    )
    if not accepted:
        if has_capability_unavailable_gap(
            draft.missing_questions, allowed_source_types=allowed_source_types
        ):
            return "capability_unavailable"
        return "no_novel_followups" if len(previous) < max_needs else "max_needs"
    stored = await persist_runtime_needs(session, attempt_id=attempt.id, needs=accepted)
    accepted_ids = {need.research_need_id for need in accepted}
    seeded = await seed_need_executions(
        session,
        attempt_id=attempt.id,
        need_ids=[need.research_need_id for need in accepted],
    )
    await _emit_seeded_runtime_needs(
        session,
        attempt_id=attempt.id,
        accepted_ids=accepted_ids,
        stored=stored,
        seeded=seeded,
    )
    pending = [
        row.research_need_id
        for row in seeded
        if row.research_need_id in accepted_ids
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
    question_graph: QuestionEvidenceGraph,
    assessor: ResearchAssessor,
    planner: FollowUpResearchPlanner,
    completeness_reviewer: ResearchCompletenessReviewer,
    relevance_assessor: EvidenceRelevanceAssessor | None,
    provider_descriptors: tuple[KnowledgeProviderDescriptor, ...] | None,
    concurrency: int,
    max_follow_up_waves: int,
    max_needs: int,
    max_completeness_passes: int,
    start_wave: int | None = None,
) -> None:
    wave = INITIAL_RESEARCH_WAVE if start_wave is None else start_wave
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
                question_graph=question_graph,
                attempt_id=attempt_id,
                concurrency=concurrency,
            )
        async with factory() as barrier_session:
            with ProgressTracker() as progress:
                _raise_if_write_fenced()
                await _assert_need_barrier(
                    barrier_session, attempt_id=attempt_id, evidence_set_id=evidence_set_id
                )
                attempt = await get_attempt(barrier_session, attempt_id)
                if attempt.status == "ready":
                    return
                if attempt.research_plan_snapshot is not None:
                    snapshot_plan = research_plan_from_snapshot(attempt.research_plan_snapshot)
                runtime_plan = await _runtime_plan(barrier_session, attempt_id)
                quality_plan = runtime_plan if runtime_plan.needs else snapshot_plan
                quality = await _persist_evidence_quality(
                    barrier_session,
                    evidence_set_id=evidence_set_id,
                    plan=quality_plan,
                    descriptors=_quality_descriptors(router, provider_descriptors),
                    relevance_assessor=relevance_assessor,
                )
                assessment = await _assess_persisted_evidence(
                    barrier_session,
                    attempt=attempt,
                    evidence_set_id=evidence_set_id,
                    plan=snapshot_plan,
                    assessor=assessor,
                    assessment_pass=next_assessment_pass(wave),
                    quality=quality,
                )
                await set_research_loop_state(
                    barrier_session,
                    attempt_id,
                    research_wave=wave,
                    stop_reason=None,
                )
                await barrier_session.commit()
                await progress.publish_committed()

                if assessment.result == "sufficient":
                    existing_passes = await list_research_completeness_passes(
                        barrier_session, attempt_id
                    )
                    if len(existing_passes) >= max_completeness_passes:
                        latest = existing_passes[-1]
                        stop = (
                            "sufficient"
                            if latest.result == "complete"
                            else "max_completeness_passes"
                        )
                        await set_research_loop_state(
                            barrier_session,
                            attempt_id,
                            research_wave=wave,
                            stop_reason=stop,
                        )
                        await _freeze_ready_attempt(
                            barrier_session,
                            attempt_id=attempt_id,
                            evidence_set_id=evidence_set_id,
                        )
                        await progress.publish_committed()
                        return
                    completeness = await _review_and_persist_completeness(
                        barrier_session,
                        attempt=attempt,
                        evidence_set_id=evidence_set_id,
                        snapshot_plan=snapshot_plan,
                        assessment=assessment,
                        reviewer=completeness_reviewer,
                        router=router,
                        case_id=context.scope.case_id,
                    )
                    await barrier_session.commit()
                    await progress.publish_committed()
                    if completeness.result == "complete":
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
                        await progress.publish_committed()
                        return
                    if completeness.completeness_pass >= max_completeness_passes:
                        await set_research_loop_state(
                            barrier_session,
                            attempt_id,
                            research_wave=wave,
                            stop_reason="max_completeness_passes",
                        )
                        await _freeze_ready_attempt(
                            barrier_session,
                            attempt_id=attempt_id,
                            evidence_set_id=evidence_set_id,
                        )
                        await progress.publish_committed()
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
                        await progress.publish_committed()
                        return
                    follow_up_wave = wave + 1
                    planned = await _plan_and_persist_global_needs(
                        barrier_session,
                        attempt=attempt,
                        completeness=completeness,
                        wave_number=follow_up_wave,
                        max_needs=max_needs,
                        router=router,
                        case_id=context.scope.case_id,
                    )
                    if isinstance(planned, str):
                        await set_research_loop_state(
                            barrier_session,
                            attempt_id,
                            research_wave=wave,
                            stop_reason=planned,
                        )
                        if planned == "capability_unavailable":
                            await emit_capability_unavailable(
                                barrier_session, completeness=completeness
                            )
                        await _freeze_ready_attempt(
                            barrier_session,
                            attempt_id=attempt_id,
                            evidence_set_id=evidence_set_id,
                        )
                        await progress.publish_committed()
                        return
                    await set_research_loop_state(
                        barrier_session,
                        attempt_id,
                        research_wave=follow_up_wave,
                        stop_reason=None,
                    )
                    await barrier_session.commit()
                    await progress.publish_committed()
                    wave = follow_up_wave
                    continue

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
                    await progress.publish_committed()
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
                    await progress.publish_committed()
                    return
                await set_research_loop_state(
                    barrier_session,
                    attempt_id,
                    research_wave=follow_up_wave,
                    stop_reason=None,
                )
                await barrier_session.commit()
                await progress.publish_committed()
                wave = follow_up_wave


async def _resolve_research_objective(
    attempt: ExecutionAttempt,
    research_objective: ResearchObjective | None,
) -> ResearchObjective | None:
    persisted = attempt.research_objective_snapshot
    if persisted is not None:
        existing = research_objective_from_snapshot(persisted)
        if research_objective is not None and research_objective != existing:
            raise ExecutionStatusError(
                f"Attempt {attempt.id} research_objective is immutable once persisted"
            )
        return existing
    return research_objective


def _executable_source_types(
    router: ResearchRouter | None,
    *,
    case_id: str | None,
) -> tuple[str, ...]:
    """Types the attempt's production router/registry can actually run."""
    if router is not None:
        types = router.available_source_types()
        registered = getattr(router, "registered_descriptors", None)
        descriptors = tuple(registered()) if callable(registered) else None
    else:
        types = standard_available_source_types()
        descriptors = standard_capability_descriptors()
    return filter_source_types_for_scope(
        types, case_id=case_id, descriptors=descriptors
    )


async def _resolve_initial_plan(
    session: AsyncSession,
    *,
    attempt: ExecutionAttempt,
    research_plan: ResearchPlan | None,
    research_objective: ResearchObjective | None,
    research_planner: ResearchPlanner | None,
    need_limit: int,
    router: ResearchRouter | None,
    case_id: str | None,
) -> ResearchPlan:
    """Persist objective + initial plan before research is claimed.

    A snapshot already on the Attempt is reused. Planner/model failure
    leaves the Attempt created.
    """
    if attempt.research_plan_snapshot is not None:
        plan = research_plan_from_snapshot(attempt.research_plan_snapshot)
        _assert_plan_within_budget(plan, need_limit)
        return plan

    if research_plan is not None:
        plan = validate_research_plan(research_plan)
        _assert_plan_within_budget(plan, need_limit)
        await _persist_start_snapshots(
            session,
            attempt=attempt,
            objective=research_objective,
            plan=plan,
        )
        return plan

    if research_objective is None:
        raise InvalidResearchObjectiveError(
            "research_objective is required when no ResearchPlan is supplied"
        )
    if research_planner is None:
        raise ResearchPlannerError("ResearchPlanner is required")
    allowed_source_types = _executable_source_types(router, case_id=case_id)
    if not allowed_source_types:
        raise ResearchPlannerError("no executable research source types are available")
    try:
        drafts = await research_planner.plan_research(
            objective=research_objective,
            available_source_types=allowed_source_types,
        )
    except ResearchPlannerError:
        raise
    except Exception as exc:
        raise ResearchPlannerError(
            f"Attempt {attempt.id} research planning failed"
        ) from exc
    plan = plan_from_planner_drafts(
        drafts, allowed_source_types=allowed_source_types
    )
    _assert_plan_within_budget(plan, need_limit)
    await _persist_start_snapshots(
        session,
        attempt=attempt,
        objective=research_objective,
        plan=plan,
    )
    return plan


def _assert_plan_within_budget(plan: ResearchPlan, need_limit: int) -> None:
    if len(plan.needs) > need_limit:
        raise InvalidResearchPlanError(
            f"ResearchPlan has {len(plan.needs)} needs; "
            f"research_max_needs_per_attempt={need_limit}"
        )


async def _resolve_resume_plan(
    attempt: ExecutionAttempt,
    *,
    research_plan: ResearchPlan | None,
    need_limit: int,
) -> ResearchPlan:
    """Reuse the immutable initial plan. Never invoke the planner on reclaim."""
    if attempt.research_plan_snapshot is not None:
        plan = research_plan_from_snapshot(attempt.research_plan_snapshot)
        _assert_plan_within_budget(plan, need_limit)
        return plan
    if research_plan is not None:
        plan = validate_research_plan(research_plan)
        _assert_plan_within_budget(plan, need_limit)
        return plan
    raise ResearchExecutionError(
        f"Attempt {attempt.id} cannot resume research without a persisted plan"
    )


async def _ensure_research_inventory(
    session: AsyncSession,
    *,
    attempt: ExecutionAttempt,
    run: ExecutionRun,
    plan: ResearchPlan,
) -> str:
    evidence_set_id = attempt.evidence_set_id
    if evidence_set_id is None:
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
    else:
        evidence_set = await get_evidence_set(session, evidence_set_id)
        if evidence_set.status == "failed":
            raise ResearchExecutionError(
                f"Attempt {attempt.id} EvidenceSet {evidence_set_id} is failed"
            )
    stored_needs = await persist_runtime_needs(
        session,
        attempt_id=attempt.id,
        needs=runtime_needs_from_plan(plan),
    )
    seeded = await seed_need_executions(
        session,
        attempt_id=attempt.id,
        need_ids=[need.id for need in plan.needs],
    )
    await _emit_seeded_runtime_needs(
        session,
        attempt_id=attempt.id,
        accepted_ids={need.id for need in plan.needs},
        stored=stored_needs,
        seeded=seeded,
    )
    return evidence_set_id


async def _persist_start_snapshots(
    session: AsyncSession,
    *,
    attempt: ExecutionAttempt,
    objective: ResearchObjective | None,
    plan: ResearchPlan,
) -> None:
    if objective is not None:
        await set_attempt_snapshots(
            session,
            attempt_id=attempt.id,
            research_objective_snapshot=research_objective_to_snapshot(objective),
        )
        await emit_objective_accepted(
            session, attempt_id=attempt.id, objective=objective
        )
    await set_attempt_snapshots(
        session,
        attempt_id=attempt.id,
        research_plan_snapshot=research_plan_to_snapshot(plan),
    )
    await emit_initial_plan_accepted(session, attempt_id=attempt.id, plan=plan)
    await session.refresh(attempt)


async def execute_attempt_research(
    session: AsyncSession,
    *,
    attempt_id: str,
    research_plan: ResearchPlan | None = None,
    research_objective: ResearchObjective | None = None,
    research_planner: ResearchPlanner | None = None,
    router: ResearchRouter | None = None,
    router_factory: ResearchRouterFactory | None = None,
    assessor: ResearchAssessor | None = None,
    planner: FollowUpResearchPlanner | None = None,
    completeness_reviewer: ResearchCompletenessReviewer | None = None,
    relevance_assessor: EvidenceRelevanceAssessor | None = None,
    provider_descriptors: Sequence[KnowledgeProviderDescriptor] | None = None,
    question_graph: QuestionEvidenceGraph | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    concurrency: int | None = None,
    max_follow_up_waves: int | None = None,
    max_needs: int | None = None,
    max_completeness_passes: int | None = None,
    lease_lost: asyncio.Event | None = None,
) -> AttemptResearchResult:
    """Plan if needed, then run ResearchNeeds in bounded waves and freeze.

    Canonical path: persisted research_objective → ResearchPlanner →
    validated initial ResearchPlan snapshot → retrieve / quality / assess /
    follow-up.
    An explicit ResearchPlan skips the planner (tests and internal callers).
    A researching Attempt resumes the same objective/plan/EvidenceSet
    lineage without regenerating the initial plan. Scope is always taken
    from ExecutionRun. Source-level error/not_found complete that need and
    do not fail the Attempt. Planner failure leaves the Attempt created.
    Assessor/follow-up/model/parsing/worker failure marks both Attempt and
    EvidenceSet failed without freezing.
    """
    if router is None and router_factory is None:
        raise ResearchExecutionError("ResearchRouter is required")

    attempt = await get_attempt(session, attempt_id)
    if attempt.status == "ready":
        return await _result_from_attempt(session, attempt)
    if attempt.status not in {"created", "researching"}:
        raise ExecutionStatusError(
            f"Cannot start research on attempt {attempt.id} with status={attempt.status}"
        )

    bound_assessor = assessor or ProgrammaticResearchAssessor()
    bound_planner = planner or NoOpFollowUpPlanner()
    bound_completeness = (
        completeness_reviewer or ProgrammaticResearchCompletenessReviewer()
    )
    bound_graph = question_graph or DisabledQuestionEvidenceGraph()
    wave_limit, need_limit, completeness_limit = _loop_limits(
        max_follow_up_waves, max_needs, max_completeness_passes
    )
    run = await get_run(session, attempt.run_id)
    case_id = research_context_from_run(run).scope.case_id
    resume = attempt.status == "researching"
    if resume:
        await _resolve_research_objective(attempt, research_objective)
        plan = await _resolve_resume_plan(
            attempt,
            research_plan=research_plan,
            need_limit=need_limit,
        )
    else:
        objective = await _resolve_research_objective(attempt, research_objective)
        plan = await _resolve_initial_plan(
            session,
            attempt=attempt,
            research_plan=research_plan,
            research_objective=objective,
            research_planner=research_planner,
            need_limit=need_limit,
            router=router,
            case_id=case_id,
        )
    need_concurrency = _concurrency_limit(concurrency)
    claimed = resume
    evidence_set_id: str | None = attempt.evidence_set_id
    fence_token = _write_fence.set(lease_lost)
    try:
        with ProgressTracker() as progress:
            if not resume:
                attempt = await claim_attempt_researching(
                    session,
                    attempt_id,
                    research_plan_snapshot=research_plan_to_snapshot(plan),
                )
                if attempt.status == "ready":
                    return await _result_from_attempt(session, attempt)
                claimed = True
                if objective is not None:
                    await emit_objective_accepted(
                        session, attempt_id=attempt.id, objective=objective
                    )
                await emit_initial_plan_accepted(
                    session, attempt_id=attempt.id, plan=plan
                )
            evidence_set_id = await _ensure_research_inventory(
                session,
                attempt=attempt,
                run=run,
                plan=plan,
            )
            start_wave = attempt.research_wave if resume else INITIAL_RESEARCH_WAVE
            context = research_context_from_run(run)
            factory = session_factory or _session_factory(session)
            await session.commit()
            await progress.publish_committed()

        await _run_research_loop(
            factory=factory,
            attempt_id=attempt_id,
            evidence_set_id=evidence_set_id,
            snapshot_plan=plan,
            context=context,
            router=router,
            router_factory=router_factory,
            question_graph=bound_graph,
            assessor=bound_assessor,
            planner=bound_planner,
            completeness_reviewer=bound_completeness,
            relevance_assessor=relevance_assessor,
            provider_descriptors=(
                None if provider_descriptors is None else tuple(provider_descriptors)
            ),
            concurrency=need_concurrency,
            max_follow_up_waves=wave_limit,
            max_needs=need_limit,
            max_completeness_passes=completeness_limit,
            start_wave=start_wave,
        )
        async with factory() as final_session:
            result = await _result_from_attempt(
                final_session, await get_attempt(final_session, attempt_id)
            )
        await _refresh_caller_state(session, attempt_id, evidence_set_id)
        return result
    except BaseException as exc:
        if isinstance(exc, asyncio.CancelledError):
            raise
        if isinstance(exc, ExecutionStatusError) and not claimed:
            raise
        fence = _write_fence.get()
        if fence is not None and fence.is_set():
            raise asyncio.CancelledError from exc
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
    finally:
        if _write_fence.get() is lease_lost:
            _write_fence.reset(fence_token)


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
    cached_completeness = await session.execute(
        select(ResearchCompletenessPass).where(
            ResearchCompletenessPass.attempt_id == attempt_id
        )
    )
    for row in cached_completeness.scalars():
        session.expire(row)
    if evidence_set_id is not None:
        cached_quality = await session.execute(
            select(ResearchEvidenceQuality).where(
                ResearchEvidenceQuality.evidence_set_id == evidence_set_id
            )
        )
        for row in cached_quality.scalars():
            session.expire(row)
