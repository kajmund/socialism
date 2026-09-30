"""Research-loop control flow. Decision policy lives in loop_decision."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, fields, replace

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import ExecutionAttempt, ResearchAssessment
from app.observability.context import bind_log_context
from app.services.execution.models import INITIAL_RESEARCH_WAVE, ResearchStopReason
from app.services.execution.service import (
    get_attempt,
    list_research_completeness_passes,
    set_research_loop_state,
)
from app.services.research.assessment import ResearchAssessor
from app.services.research.completeness import ResearchCompletenessReviewer
from app.services.research.evidence_screen import bind_attempt_relevance
from app.services.research.execution import (
    _assert_need_barrier,
    _assess_persisted_evidence,
    _freeze_ready_attempt,
    _pending_need_pairs,
    _persist_evidence_quality,
    _plan_and_persist_follow_ups,
    _plan_and_persist_global_needs,
    _quality_descriptors,
    _raise_if_write_fenced,
    _review_and_persist_completeness,
    _run_need_executions,
    _runtime_plan,
)
from app.services.research.followup import (
    FollowUpResearchPlanner,
    next_assessment_pass,
    require_stop_reason,
)
from app.services.research.loop_decision import (
    decide_after_assessment,
    decide_after_completeness,
)
from app.services.research.models import ResearchContext, ResearchPlan
from app.services.research.need_normalization import ResearchNeedNormalizer
from app.services.research.plan import research_plan_from_snapshot
from app.services.research.progress import ProgressTracker, emit_capability_unavailable
from app.services.research.provider import KnowledgeProviderDescriptor
from app.services.research.quality import EvidenceRelevanceAssessor
from app.services.research.quality_persist import EagerQualityBind
from app.services.research.question_graph import QuestionEvidenceGraph
from app.services.research.router import ResearchRouter

ResearchRouterFactory = Callable[[AsyncSession], ResearchRouter]


@dataclass(frozen=True)
class ResearchLoopConfig:
    factory: async_sessionmaker[AsyncSession]
    attempt_id: str
    evidence_set_id: str
    context: ResearchContext
    router: ResearchRouter | None
    router_factory: ResearchRouterFactory | None
    question_graph: QuestionEvidenceGraph
    assessor: ResearchAssessor
    planner: FollowUpResearchPlanner
    completeness_reviewer: ResearchCompletenessReviewer
    relevance_assessor: EvidenceRelevanceAssessor | None
    provider_descriptors: tuple[KnowledgeProviderDescriptor, ...] | None
    concurrency: int
    max_follow_up_waves: int
    max_needs: int
    max_completeness_passes: int
    need_normalizer: ResearchNeedNormalizer | None


def _loop_config(raw: dict[str, object]) -> ResearchLoopConfig:
    values = {item.name: raw[item.name] for item in fields(ResearchLoopConfig)}
    return ResearchLoopConfig(**values)


async def stop_and_freeze(
    session: AsyncSession,
    progress: ProgressTracker,
    config: ResearchLoopConfig,
    *,
    wave: int,
    reason: ResearchStopReason,
    after_state: Callable[[], Awaitable[None]] | None = None,
) -> None:
    await set_research_loop_state(
        session,
        config.attempt_id,
        research_wave=wave,
        stop_reason=reason,
    )
    if after_state is not None:
        await after_state()
    await _freeze_ready_attempt(
        session,
        attempt_id=config.attempt_id,
        evidence_set_id=config.evidence_set_id,
    )
    await progress.publish_committed()


async def advance_research_wave(
    session: AsyncSession,
    progress: ProgressTracker,
    config: ResearchLoopConfig,
    *,
    follow_up_wave: int,
) -> int:
    await set_research_loop_state(
        session,
        config.attempt_id,
        research_wave=follow_up_wave,
        stop_reason=None,
    )
    await session.commit()
    await progress.publish_committed()
    return follow_up_wave


async def run_research_loop(**kwargs: object) -> None:
    config = _loop_config(kwargs)
    _, relevance_assessor = bind_attempt_relevance(config.assessor, config.relevance_assessor)
    config = replace(config, relevance_assessor=relevance_assessor)
    snapshot_plan = kwargs["snapshot_plan"]
    start_wave = kwargs.get("start_wave")
    wave = INITIAL_RESEARCH_WAVE if start_wave is None else int(start_wave)
    while True:
        bind_log_context(wave_number=wave)
        async with config.factory() as wave_session:
            pending = await _pending_need_pairs(wave_session, config.attempt_id)
            runtime_plan = await _runtime_plan(wave_session, config.attempt_id)
            if not runtime_plan.needs:
                runtime_plan = snapshot_plan
        if pending:
            await _run_need_executions(
                factory=config.factory,
                pending=pending,
                evidence_set_id=config.evidence_set_id,
                plan=runtime_plan,
                context=config.context,
                router=config.router,
                router_factory=config.router_factory,
                question_graph=config.question_graph,
                attempt_id=config.attempt_id,
                concurrency=config.concurrency,
                eager=EagerQualityBind(
                    descriptors=_quality_descriptors(
                        config.router, config.provider_descriptors
                    ),
                    relevance_assessor=config.relevance_assessor,
                    reuse_assessor=config.assessor,
                ),
            )
        next_wave = await _finish_research_wave(config, snapshot_plan=snapshot_plan, wave=wave)
        if next_wave is None:
            return
        snapshot_plan = next_wave[1]
        wave = next_wave[0]


async def _finish_research_wave(
    config: ResearchLoopConfig,
    *,
    snapshot_plan: ResearchPlan,
    wave: int,
) -> tuple[int, ResearchPlan] | None:
    async with config.factory() as barrier_session:
        with ProgressTracker() as progress:
            _raise_if_write_fenced()
            await _assert_need_barrier(
                barrier_session,
                attempt_id=config.attempt_id,
                evidence_set_id=config.evidence_set_id,
            )
            attempt = await get_attempt(barrier_session, config.attempt_id)
            if attempt.status == "ready":
                return None
            if attempt.research_plan_snapshot is not None:
                snapshot_plan = research_plan_from_snapshot(attempt.research_plan_snapshot)
            runtime_plan = await _runtime_plan(barrier_session, config.attempt_id)
            quality_plan = runtime_plan if runtime_plan.needs else snapshot_plan
            descriptors = _quality_descriptors(config.router, config.provider_descriptors)
            quality = await _persist_evidence_quality(
                barrier_session,
                evidence_set_id=config.evidence_set_id,
                plan=quality_plan,
                descriptors=descriptors,
                relevance_assessor=config.relevance_assessor,
            )
            assessment = await _assess_persisted_evidence(
                barrier_session,
                attempt=attempt,
                evidence_set_id=config.evidence_set_id,
                plan=quality_plan,
                assessor=config.assessor,
                assessment_pass=next_assessment_pass(wave),
                quality=quality,
                descriptors=descriptors,
                relevance_assessor=config.relevance_assessor,
            )
            await set_research_loop_state(
                barrier_session,
                config.attempt_id,
                research_wave=wave,
                stop_reason=None,
            )
            await barrier_session.commit()
            await progress.publish_committed()
            return await _decide_research_wave(
                config,
                barrier_session,
                progress,
                attempt=attempt,
                snapshot_plan=snapshot_plan,
                assessment=assessment,
                wave=wave,
            )


async def _decide_research_wave(
    config: ResearchLoopConfig,
    session: AsyncSession,
    progress: ProgressTracker,
    *,
    attempt: ExecutionAttempt,
    snapshot_plan: ResearchPlan,
    assessment: ResearchAssessment,
    wave: int,
) -> tuple[int, ResearchPlan] | None:
    if assessment.result == "sufficient":
        existing_passes = await list_research_completeness_passes(session, config.attempt_id)
        latest = existing_passes[-1] if existing_passes else None
        existing_count = len(existing_passes)
        latest_result = latest.result if latest else None
    else:
        existing_count = 0
        latest_result = None
    decision = decide_after_assessment(
        assessment_result=assessment.result,
        existing_completeness_passes=existing_count,
        latest_completeness_result=latest_result,
        max_completeness_passes=config.max_completeness_passes,
        wave=wave,
        max_follow_up_waves=config.max_follow_up_waves,
    )
    if decision.action == "stop":
        await stop_and_freeze(
            session,
            progress,
            config,
            wave=wave,
            reason=decision.require_stop_reason(),
        )
        return None
    if decision.action == "review_completeness":
        return await _continue_after_completeness(
            config,
            session,
            progress,
            attempt=attempt,
            snapshot_plan=snapshot_plan,
            assessment=assessment,
            wave=wave,
        )
    if decision.action != "plan_follow_up":
        raise RuntimeError(f"Unexpected loop decision: {decision.action}")
    return await _plan_follow_up_or_stop(
        config,
        session,
        progress,
        attempt=attempt,
        snapshot_plan=snapshot_plan,
        assessment=assessment,
        wave=wave,
    )


async def _plan_follow_up_or_stop(
    config: ResearchLoopConfig,
    session: AsyncSession,
    progress: ProgressTracker,
    *,
    attempt: ExecutionAttempt,
    snapshot_plan: ResearchPlan,
    assessment: ResearchAssessment,
    wave: int,
) -> tuple[int, ResearchPlan] | None:
    follow_up_wave = wave + 1
    planned = await _plan_and_persist_follow_ups(
        session,
        attempt=attempt,
        snapshot_plan=snapshot_plan,
        assessment=assessment,
        evidence_set_id=config.evidence_set_id,
        planner=config.planner,
        wave_number=follow_up_wave,
        max_needs=config.max_needs,
        router=config.router,
        case_id=config.context.scope.case_id,
        need_normalizer=config.need_normalizer,
        question_graph=config.question_graph,
        context=config.context,
    )
    if isinstance(planned, str):
        await stop_and_freeze(
            session,
            progress,
            config,
            wave=wave,
            reason=require_stop_reason(planned),
        )
        return None
    next_wave = await advance_research_wave(
        session,
        progress,
        config,
        follow_up_wave=follow_up_wave,
    )
    return next_wave, snapshot_plan


async def _continue_after_completeness(
    config: ResearchLoopConfig,
    session: AsyncSession,
    progress: ProgressTracker,
    *,
    attempt: ExecutionAttempt,
    snapshot_plan: ResearchPlan,
    assessment: ResearchAssessment,
    wave: int,
) -> tuple[int, ResearchPlan] | None:
    completeness = await _review_and_persist_completeness(
        session,
        attempt=attempt,
        evidence_set_id=config.evidence_set_id,
        snapshot_plan=snapshot_plan,
        assessment=assessment,
        reviewer=config.completeness_reviewer,
        router=config.router,
        case_id=config.context.scope.case_id,
    )
    await session.commit()
    await progress.publish_committed()
    decision = decide_after_completeness(
        completeness_result=completeness.result,
        completeness_pass=completeness.completeness_pass,
        max_completeness_passes=config.max_completeness_passes,
        wave=wave,
        max_follow_up_waves=config.max_follow_up_waves,
    )
    if decision.action == "stop":
        await stop_and_freeze(
            session,
            progress,
            config,
            wave=wave,
            reason=decision.require_stop_reason(),
        )
        return None
    if decision.action != "plan_global":
        raise RuntimeError(f"Unexpected completeness decision: {decision.action}")
    follow_up_wave = wave + 1
    planned = await _plan_and_persist_global_needs(
        session,
        attempt=attempt,
        completeness=completeness,
        wave_number=follow_up_wave,
        max_needs=config.max_needs,
        router=config.router,
        case_id=config.context.scope.case_id,
        need_normalizer=config.need_normalizer,
        question_graph=config.question_graph,
        context=config.context,
    )
    if isinstance(planned, str):
        after_state = None
        if planned == "capability_unavailable":

            async def after_state() -> None:
                await emit_capability_unavailable(session, completeness=completeness)

        await stop_and_freeze(
            session,
            progress,
            config,
            wave=wave,
            reason=require_stop_reason(planned),
            after_state=after_state,
        )
        return None
    next_wave = await advance_research_wave(
        session,
        progress,
        config,
        follow_up_wave=follow_up_wave,
    )
    return next_wave, snapshot_plan
