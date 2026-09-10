"""Execution HTTP API: Run → Research → method execute → read models."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.scope import assert_kund_access
from app.database.models import (
    EvidenceSet,
    EvidenceSetItem,
    ExecutionAttempt,
    ExecutionAttemptResult,
    ExecutionRun,
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
    EvidenceSetItemOut,
    EvidenceSetOut,
    EvidenceSummaryOut,
    ExecutionAttemptCreate,
    ExecutionAttemptOut,
    ExecutionRunCreate,
    ExecutionRunOut,
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
    list_evidence_summaries,
    list_run_attempts,
)
from app.services.panel.attempt_execution import (
    GENERIC_PANEL_ATTEMPT_TYPE,
    PanelAttemptError,
    validate_generic_panel_snapshots,
)
from app.services.prompt_store import require_active_prompts
from app.services.research.composition import (
    ResearchCompositionError,
    build_standard_research_router,
)
from app.services.research.execution import (
    AttemptResearchResult,
    ResearchExecutionError,
    execute_attempt_research,
)
from app.services.research.models import InvalidResearchPlanError
from app.services.research.plan import research_plan_from_snapshot

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
    if isinstance(exc, (InvalidResearchPlanError, ValidationError)):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, UnsupportedAttemptTypeError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, (ResearchExecutionError, PanelAttemptError, ResearchCompositionError)):
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


def _item_out(item: EvidenceSetItem) -> EvidenceSetItemOut:
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
    )


def _evidence_set_out(row: EvidenceSet, items: list[EvidenceSetItem]) -> EvidenceSetOut:
    return EvidenceSetOut(
        id=row.id,
        run_id=row.run_id,
        created_from_attempt_id=row.created_from_attempt_id,
        status=row.status,
        created_at=row.created_at,
        frozen_at=row.frozen_at,
        items=[_item_out(item) for item in items],
    )


def _research_out(result: AttemptResearchResult) -> AttemptResearchOut:
    return AttemptResearchOut(
        attempt_id=result.attempt_id,
        evidence_set_id=result.evidence_set_id,
        status=result.status,
        found_count=result.found_count,
        not_found_count=result.not_found_count,
        error_count=result.error_count,
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
            raise ExecutionScopeError(
                "Attempt evidence must belong to the same run"
            )
        evidence_run = await get_run(session, evidence_set.run_id)
        if evidence_run.customer_id != run.customer_id:
            raise ExecutionScopeError(
                "Attempt evidence must belong to the same customer"
            )
        items = await list_evidence_items(session, evidence_set.id)
    except ExecutionError as exc:
        raise _http_for_execution_error(exc) from exc
    return evidence_set, items


def _attempt_out_from_loaded(
    attempt: ExecutionAttempt,
    *,
    evidence: EvidenceSummaryOut | None,
    result_row: ExecutionAttemptResult | None,
) -> ExecutionAttemptOut:
    return ExecutionAttemptOut(
        id=attempt.id,
        run_id=attempt.run_id,
        parent_attempt_id=attempt.parent_attempt_id,
        attempt_type=attempt.attempt_type,
        status=attempt.status,
        configuration_snapshot=dict(attempt.configuration_snapshot or {}),
        input_snapshot=dict(attempt.input_snapshot or {}),
        research_plan_snapshot=attempt.research_plan_snapshot,
        evidence=evidence,
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
        summaries = await list_evidence_summaries(
            session, [attempt.evidence_set_id], run_id=run.id
        )
        raw = summaries.get(attempt.evidence_set_id)
        if raw is None:
            raise HTTPException(
                status_code=403, detail="Attempt evidence must belong to the same run"
            )
        evidence = _summary_from_counts(attempt.evidence_set_id, *raw)
    result_row = await get_attempt_result(session, attempt.id)
    return _attempt_out_from_loaded(attempt, evidence=evidence, result_row=result_row)


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
        attempt.evidence_set_id
        for attempt in attempts
        if attempt.evidence_set_id is not None
    ]
    summaries = await list_evidence_summaries(session, set_ids, run_id=run.id)
    results = await list_attempt_results(session, [attempt.id for attempt in attempts])
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
        attempt = await create_attempt(
            session,
            run_id=run.id,
            attempt_type=body.attempt_type,
            configuration_snapshot=body.configuration_snapshot,
            input_snapshot=body.input_snapshot,
        )
    except ExecutionError as exc:
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
    return AttemptResearchOut(
        attempt_id=attempt.id,
        evidence_set_id=attempt.evidence_set_id,
        status=attempt.status,
        found_count=found,
        not_found_count=not_found,
        error_count=error,
    )


@router.post(
    "/attempts/{attempt_id}/research",
    response_model=AttemptResearchOut,
)
async def post_attempt_research(
    attempt_id: str,
    body: AttemptResearchRequest,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> AttemptResearchOut:
    attempt, _run = await _require_attempt(session, user, attempt_id)
    if attempt.status == "ready":
        return await _research_out_from_attempt(session, attempt)
    try:
        plan = research_plan_from_snapshot(body.research_plan.model_dump())
        router_impl = build_standard_research_router(session)
        result = await execute_attempt_research(
            session,
            attempt_id=attempt_id,
            research_plan=plan,
            router=router_impl,
        )
    except (
        ExecutionError,
        InvalidResearchPlanError,
        ResearchExecutionError,
        ResearchCompositionError,
    ) as exc:
        raise _http_for_execution_error(exc) from exc
    return _research_out(result)


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
    return _evidence_set_out(evidence_set, items)


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
