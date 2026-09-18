"""Execution HTTP API: Run → Research → method execute → read models."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.scope import assert_kund_access
from app.database.models import (
    EvidenceSet,
    EvidenceSetItem,
    ExecutionAttempt,
    ExecutionAttemptResult,
    ExecutionRun,
    KnowledgeQuestionRow,
    Persona,
    ResearchAssessment,
    ResearchCompletenessPass,
    ResearchEvidenceQuality,
    ResearchProgressEvent,
    ResearchQuestion,
    ResearchQuestionDependency,
    ResearchQuestionExpert,
    ResearchRuntimeNeed,
    SpecificQuestion,
    UserAccount,
)
from app.database.session import get_session
from app.services.attempt_executors import (
    UnsupportedAttemptTypeError,
    execute_registered_attempt,
)
from app.services.execution.errors import (
    ExecutionError,
    ExecutionFrozenError,
    ExecutionImmutableError,
    ExecutionNotFoundError,
    ExecutionScopeError,
    ExecutionStatusError,
)
from app.services.execution.schemas import (
    AttemptCloneRequest,
    AttemptExecuteOut,
    AttemptExecuteRequest,
    AttemptResearchOut,
    AttemptResearchRequest,
    AttemptResultOut,
    EvidenceQualityFlagOut,
    EvidenceQualityOut,
    EvidenceSetItemOut,
    EvidenceSetOut,
    EvidenceSummaryOut,
    ExecutionAttemptCreate,
    ExecutionAttemptOut,
    ExecutionRunCreate,
    ExecutionRunOut,
    MissingQuestionOut,
    ResearchAssessmentOut,
    ResearchCompletenessOut,
    ResearchExpertOut,
    ResearchNeedAssessmentOut,
    ResearchOverviewCountsOut,
    ResearchOverviewOut,
    ResearchProgressEventListOut,
    ResearchProgressEventOut,
    ResearchQuestionOverviewOut,
    ResearchSourceOut,
    RuntimeResearchNeedOut,
)
from app.services.execution.service import (
    clone_attempt,
    create_attempt,
    create_run,
    get_attempt,
    get_attempt_result,
    get_evidence_set,
    get_run,
    list_attempt_results,
    list_evidence_items,
    list_evidence_quality,
    list_evidence_summaries,
    list_research_assessments,
    list_research_assessments_for_attempts,
    list_research_completeness_for_attempts,
    list_research_completeness_passes,
    list_run_attempts,
    list_runtime_needs,
    list_runtime_needs_for_attempts,
)
from app.services.panel.attempt_execution import (
    GENERIC_PANEL_ATTEMPT_TYPE,
    PanelAttemptError,
    validate_generic_panel_snapshots,
)
from app.services.prompt_store import require_active_prompts
from app.services.research.assessment import need_assessment_from_json
from app.services.research.completeness import (
    ResearchCompletenessError,
    missing_question_from_json,
)
from app.services.research.composition import ResearchCompositionError
from app.services.research.execution import ResearchExecutionError
from app.services.research.models import InvalidResearchPlanError
from app.services.research.planner import (
    InvalidResearchObjectiveError,
    ResearchObjective,
    ResearchPlannerError,
    require_research_objective,
    research_objective_to_snapshot,
)
from app.services.research.progress import list_research_progress_events
from app.services.research_worker import accept_attempt_research

router = APIRouter(prefix="/execution", tags=["execution"])


def _http_for_execution_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ExecutionNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ExecutionScopeError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(
        exc,
        (ExecutionStatusError, ExecutionImmutableError, ExecutionFrozenError),
    ):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(
        exc,
        (InvalidResearchPlanError, InvalidResearchObjectiveError, ValidationError),
    ):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, UnsupportedAttemptTypeError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(
        exc,
        (
            ResearchExecutionError,
            ResearchPlannerError,
            PanelAttemptError,
            ResearchCompositionError,
        ),
    ):
        return HTTPException(status_code=500, detail=str(exc))
    if isinstance(exc, ExecutionError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def _run_out(run: ExecutionRun) -> ExecutionRunOut:
    return ExecutionRunOut(
        id=run.id,
        customer_id=run.customer_id,
        module=run.module,
        title=run.title,
        context=dict(run.context or {}),
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _assessment_out(row: ResearchAssessment) -> ResearchAssessmentOut:
    return ResearchAssessmentOut(
        id=row.id,
        attempt_id=row.attempt_id,
        evidence_set_id=row.evidence_set_id,
        assessment_pass=row.assessment_pass,
        result=row.result,
        rationale=row.rationale,
        need_assessments=[
            ResearchNeedAssessmentOut(
                research_need_id=item.research_need_id,
                sufficient=item.sufficient,
                supporting_evidence_ids=list(item.supporting_evidence_ids),
                missing_or_weak=item.missing_or_weak,
                contradictions=list(item.contradictions),
                further_information=item.further_information,
            )
            for item in (need_assessment_from_json(raw) for raw in (row.need_assessments or []))
        ],
        gaps=list(row.gaps or []),
        contradictions=list(row.contradictions or []),
        considered_evidence_ids=list(row.considered_evidence_ids or []),
        evidence_fingerprint=row.evidence_fingerprint,
        model_provider=row.model_provider,
        model_name=row.model_name,
        model_version=row.model_version,
        created_at=row.created_at,
    )


def _runtime_need_out(row: ResearchRuntimeNeed) -> RuntimeResearchNeedOut:
    return RuntimeResearchNeedOut(
        research_need_id=row.research_need_id,
        question=row.question,
        why_needed=row.why_needed,
        requested_by=list(row.requested_by or []),
        source_types=list(row.source_types or []),
        domains=list(row.domains or []),
        modalities=list(row.modalities or []),
        capabilities=list(row.capabilities or []),
        origin=row.origin,
        wave_number=row.wave_number,
        parent_research_need_id=row.parent_research_need_id,
        source_assessment_pass=row.source_assessment_pass,
        source_completeness_pass=row.source_completeness_pass,
        source_gap=row.source_gap or "",
        question_key=row.question_key,
    )


def _completeness_out(row: ResearchCompletenessPass) -> ResearchCompletenessOut:
    return ResearchCompletenessOut(
        id=row.id,
        attempt_id=row.attempt_id,
        evidence_set_id=row.evidence_set_id,
        completeness_pass=row.completeness_pass,
        result=row.result,
        rationale=row.rationale,
        missing_questions=[
            MissingQuestionOut(
                question=item.question,
                why_needed=item.why_needed,
                rationale=item.rationale,
                source_types=list(item.source_types),
                unavailable_source_types=list(item.unavailable_source_types),
                capability_gap=item.capability_gap,
            )
            for item in (missing_question_from_json(raw) for raw in (row.missing_questions or []))
        ],
        considered_evidence_ids=list(row.considered_evidence_ids or []),
        considered_question_keys=list(row.considered_question_keys or []),
        evidence_fingerprint=row.evidence_fingerprint,
        question_fingerprint=row.question_fingerprint,
        model_provider=row.model_provider,
        model_name=row.model_name,
        model_version=row.model_version,
        created_at=row.created_at,
    )


def _result_out(row: ExecutionAttemptResult) -> AttemptResultOut:
    return AttemptResultOut(
        id=row.id,
        result_type=row.result_type,
        schema_version=row.schema_version,
        payload=dict(row.payload or {}),
        evidence_refs=dict(row.evidence_refs or {}),
        panel_session_id=row.panel_session_id,
        created_at=row.created_at,
    )


def _quality_out(row: ResearchEvidenceQuality) -> EvidenceQualityOut:
    raw_flags = row.flags if isinstance(row.flags, list) else []
    flags = [
        EvidenceQualityFlagOut(
            code=str(item.get("code") or ""),
            detail=str(item.get("detail") or ""),
        )
        for item in raw_flags
        if isinstance(item, dict)
    ]
    return EvidenceQualityOut(
        id=row.id,
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
        created_at=row.created_at,
    )


def _item_out(
    item: EvidenceSetItem,
    quality: ResearchEvidenceQuality | None = None,
) -> EvidenceSetItemOut:
    return EvidenceSetItemOut(
        id=item.id,
        evidence_set_id=item.evidence_set_id,
        research_need_id=item.research_need_id,
        original_evidence_id=item.original_evidence_id,
        ordinal=item.ordinal,
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
        quality=None if quality is None else _quality_out(quality),
    )


def _evidence_set_out(
    row: EvidenceSet,
    items: list[EvidenceSetItem],
    quality_rows: list[ResearchEvidenceQuality] | None = None,
) -> EvidenceSetOut:
    latest: dict[str, ResearchEvidenceQuality] = {}
    for quality in quality_rows or []:
        latest[quality.evidence_set_item_id] = quality
    return EvidenceSetOut(
        id=row.id,
        run_id=row.run_id,
        created_from_attempt_id=row.created_from_attempt_id,
        status=row.status,
        created_at=row.created_at,
        frozen_at=row.frozen_at,
        items=[_item_out(item, latest.get(item.id)) for item in items],
    )


async def _require_run(
    session: AsyncSession,
    user: UserAccount,
    run_id: str,
) -> ExecutionRun:
    try:
        run = await get_run(session, run_id)
    except ExecutionNotFoundError as exc:
        raise _http_for_execution_error(exc) from exc
    assert_kund_access(user, run.customer_id)
    return run


async def _require_attempt(
    session: AsyncSession,
    user: UserAccount,
    attempt_id: str,
) -> tuple[ExecutionAttempt, ExecutionRun]:
    try:
        attempt = await get_attempt(session, attempt_id)
        run = await get_run(session, attempt.run_id)
    except ExecutionNotFoundError as exc:
        raise _http_for_execution_error(exc) from exc
    assert_kund_access(user, run.customer_id)
    return attempt, run


async def _attached_evidence(
    session: AsyncSession,
    attempt: ExecutionAttempt,
    run: ExecutionRun,
) -> tuple[EvidenceSet, list[EvidenceSetItem]] | None:
    if attempt.evidence_set_id is None:
        return None
    try:
        evidence_set = await get_evidence_set(session, attempt.evidence_set_id)
        if evidence_set.run_id != run.id:
            raise ExecutionScopeError("Attempt evidence must belong to the same run")
        evidence_run = await get_run(session, evidence_set.run_id)
        if evidence_run.customer_id != run.customer_id:
            raise ExecutionScopeError("Attempt evidence must belong to the same customer")
        items = await list_evidence_items(session, evidence_set.id)
    except ExecutionError as exc:
        raise _http_for_execution_error(exc) from exc
    return evidence_set, items


def _attempt_out_from_loaded(
    attempt: ExecutionAttempt,
    *,
    evidence: EvidenceSummaryOut | None,
    result_row: ExecutionAttemptResult | None,
    assessment_row: ResearchAssessment | None = None,
    assessment_rows: list[ResearchAssessment] | None = None,
    completeness_rows: list[ResearchCompletenessPass] | None = None,
    runtime_need_rows: list[ResearchRuntimeNeed] | None = None,
) -> ExecutionAttemptOut:
    history = assessment_rows or []
    latest = assessment_row or (history[-1] if history else None)
    completeness_history = completeness_rows or []
    latest_completeness = completeness_history[-1] if completeness_history else None
    return ExecutionAttemptOut(
        id=attempt.id,
        run_id=attempt.run_id,
        parent_attempt_id=attempt.parent_attempt_id,
        attempt_type=attempt.attempt_type,
        status=attempt.status,
        configuration_snapshot=dict(attempt.configuration_snapshot or {}),
        input_snapshot=dict(attempt.input_snapshot or {}),
        research_objective_snapshot=attempt.research_objective_snapshot,
        research_plan_snapshot=attempt.research_plan_snapshot,
        evidence=evidence,
        assessment=None if latest is None else _assessment_out(latest),
        assessments=[_assessment_out(row) for row in history],
        completeness=(
            None if latest_completeness is None else _completeness_out(latest_completeness)
        ),
        completeness_passes=[_completeness_out(row) for row in completeness_history],
        research_wave=attempt.research_wave,
        stop_reason=attempt.research_stop_reason,
        runtime_needs=[_runtime_need_out(row) for row in (runtime_need_rows or [])],
        result=None if result_row is None else _result_out(result_row),
        created_at=attempt.created_at,
        started_at=attempt.started_at,
        completed_at=attempt.completed_at,
    )


def _summary_from_counts(
    evidence_set_id: str,
    status: str,
    found: int,
    not_found: int,
    error: int,
) -> EvidenceSummaryOut:
    return EvidenceSummaryOut(
        evidence_set_id=evidence_set_id,
        status=status,
        found_count=found,
        not_found_count=not_found,
        error_count=error,
    )


async def _attempt_out(
    session: AsyncSession,
    attempt: ExecutionAttempt,
    run: ExecutionRun,
) -> ExecutionAttemptOut:
    evidence = None
    if attempt.evidence_set_id is not None:
        summaries = await list_evidence_summaries(session, [attempt.evidence_set_id], run_id=run.id)
        raw = summaries.get(attempt.evidence_set_id)
        if raw is None:
            raise HTTPException(
                status_code=403, detail="Attempt evidence must belong to the same run"
            )
        evidence = _summary_from_counts(attempt.evidence_set_id, *raw)
    result_row = await get_attempt_result(session, attempt.id)
    history = await list_research_assessments(session, attempt.id)
    completeness = await list_research_completeness_passes(session, attempt.id)
    runtime_needs = await list_runtime_needs(session, attempt.id)
    return _attempt_out_from_loaded(
        attempt,
        evidence=evidence,
        result_row=result_row,
        assessment_rows=history,
        completeness_rows=completeness,
        runtime_need_rows=runtime_needs,
    )


@router.post("/runs", response_model=ExecutionRunOut, status_code=201)
async def post_execution_run(
    body: ExecutionRunCreate,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> ExecutionRunOut:
    assert_kund_access(user, body.customer_id)
    try:
        run = await create_run(
            session,
            customer_id=body.customer_id,
            module=body.module,
            title=body.title,
            context=body.context,
        )
    except ExecutionError as exc:
        raise _http_for_execution_error(exc) from exc
    await session.commit()
    return _run_out(run)


@router.get("/runs/{run_id}", response_model=ExecutionRunOut)
async def get_execution_run(
    run_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> ExecutionRunOut:
    run = await _require_run(session, user, run_id)
    return _run_out(run)


@router.get("/runs/{run_id}/attempts", response_model=list[ExecutionAttemptOut])
async def get_execution_run_attempts(
    run_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> list[ExecutionAttemptOut]:
    run = await _require_run(session, user, run_id)
    attempts = await list_run_attempts(session, run.id)
    set_ids = [
        attempt.evidence_set_id for attempt in attempts if attempt.evidence_set_id is not None
    ]
    summaries = await list_evidence_summaries(session, set_ids, run_id=run.id)
    results = await list_attempt_results(session, [attempt.id for attempt in attempts])
    attempt_ids = [attempt.id for attempt in attempts]
    assessments = await list_research_assessments_for_attempts(session, attempt_ids)
    completeness = await list_research_completeness_for_attempts(session, attempt_ids)
    runtime_needs = await list_runtime_needs_for_attempts(session, attempt_ids)
    out: list[ExecutionAttemptOut] = []
    for attempt in attempts:
        evidence = None
        if attempt.evidence_set_id is not None:
            raw = summaries.get(attempt.evidence_set_id)
            if raw is None:
                raise HTTPException(
                    status_code=403,
                    detail="Attempt evidence must belong to the same run",
                )
            evidence = _summary_from_counts(attempt.evidence_set_id, *raw)
        out.append(
            _attempt_out_from_loaded(
                attempt,
                evidence=evidence,
                result_row=results.get(attempt.id),
                assessment_rows=assessments.get(attempt.id, []),
                completeness_rows=completeness.get(attempt.id, []),
                runtime_need_rows=runtime_needs.get(attempt.id, []),
            )
        )
    return out


@router.post(
    "/runs/{run_id}/attempts",
    response_model=ExecutionAttemptOut,
    status_code=201,
)
async def post_execution_attempt(
    run_id: str,
    body: ExecutionAttemptCreate,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> ExecutionAttemptOut:
    run = await _require_run(session, user, run_id)
    if body.attempt_type.strip() == GENERIC_PANEL_ATTEMPT_TYPE:
        try:
            validate_generic_panel_snapshots(
                configuration_snapshot=body.configuration_snapshot,
                input_snapshot=body.input_snapshot,
                module=run.module,
                title=run.title,
            )
        except (ValidationError, ExecutionError) as exc:
            raise _http_for_execution_error(exc) from exc
    try:
        objective_snapshot = None
        if body.research_objective is not None:
            objective_snapshot = research_objective_to_snapshot(
                ResearchObjective(
                    objective=require_research_objective(body.research_objective),
                    context=dict(body.research_context),
                )
            )
        attempt = await create_attempt(
            session,
            run_id=run.id,
            attempt_type=body.attempt_type,
            configuration_snapshot=body.configuration_snapshot,
            input_snapshot=body.input_snapshot,
            research_objective_snapshot=objective_snapshot,
        )
    except (ExecutionError, InvalidResearchObjectiveError) as exc:
        raise _http_for_execution_error(exc) from exc
    await session.commit()
    return await _attempt_out(session, attempt, run)


@router.get("/attempts/{attempt_id}", response_model=ExecutionAttemptOut)
async def get_execution_attempt(
    attempt_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> ExecutionAttemptOut:
    attempt, run = await _require_attempt(session, user, attempt_id)
    return await _attempt_out(session, attempt, run)


@router.post(
    "/attempts/{attempt_id}/clone",
    response_model=ExecutionAttemptOut,
    status_code=201,
)
async def post_attempt_clone(
    attempt_id: str,
    body: AttemptCloneRequest | None = None,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> ExecutionAttemptOut:
    source, run = await _require_attempt(session, user, attempt_id)
    payload = body or AttemptCloneRequest()
    if (
        source.attempt_type.strip() == GENERIC_PANEL_ATTEMPT_TYPE
        and payload.configuration_snapshot is not None
    ):
        try:
            incoming = source.input_snapshot if isinstance(source.input_snapshot, dict) else {}
            validate_generic_panel_snapshots(
                configuration_snapshot=payload.configuration_snapshot,
                input_snapshot=incoming,
                module=run.module,
                title=run.title,
            )
        except (ValidationError, ExecutionError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        clone = await clone_attempt(
            session,
            source.id,
            configuration_snapshot=payload.configuration_snapshot,
        )
    except ExecutionError as exc:
        raise _http_for_execution_error(exc) from exc
    await session.commit()
    clone = await get_attempt(session, clone.id)
    return await _attempt_out(session, clone, run)


async def _research_out_from_attempt(
    session: AsyncSession, attempt: ExecutionAttempt
) -> AttemptResearchOut:
    found = not_found = error = 0
    if attempt.evidence_set_id is not None:
        summaries = await list_evidence_summaries(session, [attempt.evidence_set_id])
        raw = summaries.get(attempt.evidence_set_id)
        if raw is not None:
            _status, found, not_found, error = raw
    history = await list_research_assessments(session, attempt.id)
    latest = history[-1] if history else None
    completeness_history = await list_research_completeness_passes(session, attempt.id)
    latest_completeness = completeness_history[-1] if completeness_history else None
    runtime_needs = await list_runtime_needs(session, attempt.id)
    return AttemptResearchOut(
        attempt_id=attempt.id,
        evidence_set_id=attempt.evidence_set_id,
        status=attempt.status,
        found_count=found,
        not_found_count=not_found,
        error_count=error,
        assessment=None if latest is None else _assessment_out(latest),
        assessments=[_assessment_out(row) for row in history],
        completeness=(
            None if latest_completeness is None else _completeness_out(latest_completeness)
        ),
        completeness_passes=[_completeness_out(row) for row in completeness_history],
        research_wave=attempt.research_wave,
        stop_reason=attempt.research_stop_reason,
        runtime_needs=[_runtime_need_out(row) for row in runtime_needs],
    )


@router.post(
    "/attempts/{attempt_id}/research",
    response_model=AttemptResearchOut,
)
async def post_attempt_research(
    attempt_id: str,
    body: AttemptResearchRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> AttemptResearchOut:
    attempt, _run = await _require_attempt(session, user, attempt_id)
    try:
        status = await accept_attempt_research(
            session,
            attempt_id=attempt.id,
            research_objective=body.research_objective,
            research_context=dict(body.research_context),
            research_plan=(None if body.research_plan is None else body.research_plan.model_dump()),
        )
        attempt = await get_attempt(session, attempt_id)
    except (
        ExecutionError,
        InvalidResearchObjectiveError,
        InvalidResearchPlanError,
        ResearchCompletenessError,
        ResearchExecutionError,
        ResearchPlannerError,
        ResearchCompositionError,
    ) as exc:
        raise _http_for_execution_error(exc) from exc
    response.status_code = int(status)
    return await _research_out_from_attempt(session, attempt)


@router.post(
    "/attempts/{attempt_id}/execute",
    response_model=AttemptExecuteOut,
)
async def post_attempt_execute(
    attempt_id: str,
    body: AttemptExecuteRequest | None = None,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> AttemptExecuteOut:
    attempt, run = await _require_attempt(session, user, attempt_id)
    _ = body
    if attempt.status == "completed":
        detail = await _attempt_out(session, attempt, run)
        return AttemptExecuteOut(attempt=detail, result=detail.result)
    try:
        prompts = await require_active_prompts(
            session,
            customer_id=run.customer_id,
            module=run.module,
            language="sv",
        )
        await execute_registered_attempt(
            session,
            attempt_id=attempt.id,
            prompts=prompts,
        )
        attempt = await get_attempt(session, attempt.id)
        detail = await _attempt_out(session, attempt, run)
    except (ExecutionError, PanelAttemptError, ValidationError) as exc:
        raise _http_for_execution_error(exc) from exc
    return AttemptExecuteOut(attempt=detail, result=detail.result)


@router.get(
    "/attempts/{attempt_id}/progress-events",
    response_model=ResearchProgressEventListOut,
)
async def get_attempt_progress_events(
    attempt_id: str,
    after_sequence: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> ResearchProgressEventListOut:
    await _require_attempt(session, user, attempt_id)
    rows = await list_research_progress_events(session, attempt_id, after_sequence=after_sequence)
    return ResearchProgressEventListOut(
        attempt_id=attempt_id,
        after_sequence=after_sequence,
        events=[
            ResearchProgressEventOut(
                id=row.id,
                attempt_id=row.attempt_id,
                sequence=row.sequence,
                event_type=row.event_type,
                payload=dict(row.payload or {}),
                occurred_at=row.occurred_at,
            )
            for row in rows
        ],
    )


@router.get(
    "/attempts/{attempt_id}/research-overview",
    response_model=ResearchOverviewOut,
)
async def get_attempt_research_overview(
    attempt_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> ResearchOverviewOut:
    attempt, _run = await _require_attempt(session, user, attempt_id)
    question_rows = (
        await session.execute(
            select(
                ResearchQuestion,
                KnowledgeQuestionRow.display_text,
                SpecificQuestion.text,
            )
            .join(
                KnowledgeQuestionRow,
                KnowledgeQuestionRow.id == ResearchQuestion.knowledge_question_id,
            )
            .join(
                SpecificQuestion,
                SpecificQuestion.id == ResearchQuestion.specific_question_id,
            )
            .where(ResearchQuestion.attempt_id == attempt_id)
            .order_by(ResearchQuestion.created_at, ResearchQuestion.id)
        )
    ).all()
    question_ids = [row.id for row, _question, _specific in question_rows]
    child_ids = [
        row.execution_attempt_id
        for row, _question, _specific in question_rows
        if row.execution_attempt_id is not None
    ]
    expert_links = (
        list(
            (
                await session.execute(
                    select(ResearchQuestionExpert).where(
                        ResearchQuestionExpert.question_id.in_(question_ids)
                    )
                )
            ).scalars()
        )
        if question_ids
        else []
    )
    expert_ids = {link.expert_id for link in expert_links}
    personas = (
        list((await session.execute(select(Persona).where(Persona.id.in_(expert_ids)))).scalars())
        if expert_ids
        else []
    )
    expert_names = {persona.id: persona.name for persona in personas}
    dependencies = (
        list(
            (
                await session.execute(
                    select(ResearchQuestionDependency).where(
                        ResearchQuestionDependency.question_id.in_(question_ids)
                    )
                )
            ).scalars()
        )
        if question_ids
        else []
    )
    children = (
        list(
            (
                await session.execute(
                    select(ExecutionAttempt).where(ExecutionAttempt.id.in_(child_ids))
                )
            ).scalars()
        )
        if child_ids
        else []
    )
    child_by_id = {child.id: child for child in children}
    evidence_set_ids = [child.evidence_set_id for child in children if child.evidence_set_id]
    evidence_items = (
        list(
            (
                await session.execute(
                    select(EvidenceSetItem)
                    .where(EvidenceSetItem.evidence_set_id.in_(evidence_set_ids))
                    .order_by(EvidenceSetItem.ordinal, EvidenceSetItem.id)
                )
            ).scalars()
        )
        if evidence_set_ids
        else []
    )
    assessments = (
        list(
            (
                await session.execute(
                    select(ResearchAssessment)
                    .where(ResearchAssessment.attempt_id.in_(child_ids))
                    .order_by(ResearchAssessment.assessment_pass)
                )
            ).scalars()
        )
        if child_ids
        else []
    )
    completeness = (
        list(
            (
                await session.execute(
                    select(ResearchCompletenessPass)
                    .where(ResearchCompletenessPass.attempt_id.in_(child_ids))
                    .order_by(ResearchCompletenessPass.completeness_pass)
                )
            ).scalars()
        )
        if child_ids
        else []
    )

    links_by_question: dict[str, list[ResearchQuestionExpert]] = {}
    for link in expert_links:
        links_by_question.setdefault(link.question_id, []).append(link)
    dependency_ids: dict[str, list[str]] = {}
    for dependency in dependencies:
        dependency_ids.setdefault(dependency.question_id, []).append(
            dependency.depends_on_question_id
        )
    items_by_set: dict[str, list[EvidenceSetItem]] = {}
    for item in evidence_items:
        items_by_set.setdefault(item.evidence_set_id, []).append(item)
    assessment_by_attempt = {row.attempt_id: row for row in assessments}
    completeness_by_attempt = {row.attempt_id: row for row in completeness}

    questions: list[ResearchQuestionOverviewOut] = []
    for row, question_text, specific_text in question_rows:
        child = child_by_id.get(row.execution_attempt_id or "")
        items = (
            items_by_set.get(child.evidence_set_id, []) if child and child.evidence_set_id else []
        )
        assessment = assessment_by_attempt.get(child.id) if child else None
        complete = completeness_by_attempt.get(child.id) if child else None
        status = _research_question_display_status(
            raw_status=row.status,
            items=items,
            assessment=assessment,
            completeness=complete,
        )
        links = links_by_question.get(row.id, [])
        raised = [link for link in links if link.role == "raised_by"]
        assigned = next((link for link in links if link.role == "assigned_to"), None)
        questions.append(
            ResearchQuestionOverviewOut(
                id=row.id,
                question=question_text,
                specific_question=specific_text,
                why_needed=row.why_needed,
                status=status,
                raw_status=row.status,
                outcome_reason=row.outcome_reason,
                origin=row.origin,
                depth=row.depth,
                child_attempt_id=row.execution_attempt_id,
                child_attempt_status=child.status if child else None,
                dependency_ids=dependency_ids.get(row.id, []),
                raised_by=[
                    ResearchExpertOut(
                        id=link.expert_id,
                        name=expert_names.get(link.expert_id, link.expert_id),
                    )
                    for link in raised
                ],
                assigned_to=None
                if assigned is None
                else ResearchExpertOut(
                    id=assigned.expert_id,
                    name=expert_names.get(assigned.expert_id, assigned.expert_id),
                ),
                sources=[
                    ResearchSourceOut(
                        id=item.id,
                        status=item.status,
                        title=item.title,
                        excerpt=(item.excerpt[:1000] if item.excerpt else None),
                        locator=item.locator,
                        source_url=item.source_url,
                        source_type=item.source_type,
                        provider=item.provider,
                    )
                    for item in items
                ],
                assessment_result=assessment.result if assessment else None,
                assessment_rationale=assessment.rationale if assessment else None,
                completeness_result=complete.result if complete else None,
                completeness_rationale=complete.rationale if complete else None,
            )
        )
    status_counts = {
        status: sum(question.status == status for question in questions)
        for status in (
            "answered",
            "running",
            "waiting",
            "insufficient",
            "unanswered",
            "failed",
            "blocked",
        )
    }
    latest_sequence = int(
        (
            await session.execute(
                select(func.max(ResearchProgressEvent.sequence)).where(
                    ResearchProgressEvent.attempt_id == attempt_id
                )
            )
        ).scalar_one()
        or 0
    )
    active = status_counts["running"] + status_counts["waiting"]
    gaps = (
        status_counts["insufficient"]
        + status_counts["unanswered"]
        + status_counts["failed"]
        + status_counts["blocked"]
    )
    phase = "researching" if active else "completed_with_gaps" if gaps else "completed"
    return ResearchOverviewOut(
        run_id=attempt.run_id,
        attempt_id=attempt.id,
        attempt_status=attempt.status,
        phase=phase,
        latest_sequence=latest_sequence,
        counts=ResearchOverviewCountsOut(total=len(questions), **status_counts),
        questions=questions,
    )


def _research_question_display_status(
    *,
    raw_status: str,
    items: list[EvidenceSetItem],
    assessment: ResearchAssessment | None,
    completeness: ResearchCompletenessPass | None,
) -> str:
    if raw_status == "running":
        return "running"
    if raw_status in {"pending", "unassigned"}:
        return "waiting"
    if raw_status == "blocked":
        return "blocked"
    if raw_status == "failed":
        return "failed"
    if raw_status != "completed":
        return raw_status
    found = any(item.status == "found" for item in items)
    if not found:
        return "unanswered"
    if completeness is not None and completeness.result != "complete":
        return "insufficient"
    if completeness is None and assessment is not None and assessment.result != "sufficient":
        return "insufficient"
    return "answered"


@router.get(
    "/attempts/{attempt_id}/evidence",
    response_model=EvidenceSetOut,
)
async def get_attempt_evidence(
    attempt_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> EvidenceSetOut:
    attempt, run = await _require_attempt(session, user, attempt_id)
    attached = await _attached_evidence(session, attempt, run)
    if attached is None:
        raise HTTPException(status_code=404, detail="Attempt has no attached EvidenceSet")
    evidence_set, items = attached
    quality_rows = await list_evidence_quality(session, evidence_set.id)
    return _evidence_set_out(evidence_set, items, quality_rows)


@router.get(
    "/attempts/{attempt_id}/result",
    response_model=AttemptResultOut,
)
async def get_attempt_result_by_id(
    attempt_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> AttemptResultOut:
    attempt, _run = await _require_attempt(session, user, attempt_id)
    row = await get_attempt_result(session, attempt.id)
    if row is None:
        raise HTTPException(status_code=404, detail="Attempt result not found")
    return _result_out(row)
