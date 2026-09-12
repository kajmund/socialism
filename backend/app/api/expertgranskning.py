"""Expertgranskning module API — free-text document + saved expert panel."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.scope import (
    assert_job_owner_access,
    assert_kund_access,
    effective_customer_id,
)
from app.database.models import Job, Population, UserAccount
from app.database.session import get_session
from app.schemas.domain import JobCreate
from app.services import jobs as jobs_service
from app.services.customer_scope import customer_id_for_panel_session
from app.services.expertgranskning import WORD_JOB_KIND
from app.services.expertgranskning.schemas import (
    ExpertgranskningLatestWordJobOut,
    ExpertgranskningResultOut,
    ExpertgranskningSessionCreate,
    ExpertgranskningSessionOut,
    ExpertgranskningSessionSummary,
    ExpertgranskningSessionUpdate,
    ExpertgranskningWordJobCreate,
    ExpertgranskningWordJobRequest,
)
from app.services.expertgranskning.sessions import (
    create_expertgranskning_session,
    delete_expertgranskning_session,
    get_expertgranskning_session_out,
    is_expertgranskning_session,
    list_expertgranskning_sessions,
    prepare_session_for_run,
    resolve_customer_id,
    update_expertgranskning_session,
)
from app.services.expertgranskning.watch import (
    find_latest_word_job_for_doc,
    load_expertgranskning_results,
    publish_action_updated,
    serialize_result,
)
from app.services.word.actions import load_word_actions, serialize_word_action
from app.services.word.application import (
    claim_application,
    complete_application,
    dismiss_application,
    mark_application_unresolved,
)
from app.services.word.schemas import (
    WordActionOut,
    WordApplicationClaimIn,
    WordApplicationCompleteIn,
    WordApplicationUnresolvedIn,
)
from app.services.panel.expert_slots import require_expert_panel
from app.services.panel.sessions import get_panel_session

router = APIRouter(prefix="/expertgranskning", tags=["expertgranskning"])


async def _require_session(
    session: AsyncSession,
    user: UserAccount,
    session_id: str,
):
    row = await get_panel_session(session, session_id)
    if row is None or not is_expertgranskning_session(row):
        raise HTTPException(status_code=404, detail="Expertgranskning session not found")
    customer_id = await customer_id_for_panel_session(session, session_id)
    assert_kund_access(user, customer_id)
    return row, customer_id


@router.get("/sessions", response_model=list[ExpertgranskningSessionSummary])
async def get_expertgranskning_sessions(
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> list[ExpertgranskningSessionSummary]:
    customer_id = effective_customer_id(user)
    return await list_expertgranskning_sessions(session, customer_id=customer_id)


@router.post("/sessions", response_model=ExpertgranskningSessionOut, status_code=201)
async def post_expertgranskning_session(
    body: ExpertgranskningSessionCreate,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> ExpertgranskningSessionOut:
    try:
        customer_id = await resolve_customer_id(
            session,
            panel_id=body.panel_id,
            project_id=body.project_id,
            user_customer_id=user.kund_id,
            is_admin=user.role == "admin",
        )
        assert_kund_access(user, customer_id)
        out = await create_expertgranskning_session(
            session, body, customer_id=customer_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    return out


@router.get("/sessions/{session_id}", response_model=ExpertgranskningSessionOut)
async def get_expertgranskning_session(
    session_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> ExpertgranskningSessionOut:
    row, _customer_id = await _require_session(session, user, session_id)
    return await get_expertgranskning_session_out(session, row)


@router.patch("/sessions/{session_id}", response_model=ExpertgranskningSessionOut)
async def patch_expertgranskning_session(
    session_id: str,
    body: ExpertgranskningSessionUpdate,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> ExpertgranskningSessionOut:
    row, customer_id = await _require_session(session, user, session_id)
    try:
        out = await update_expertgranskning_session(
            session, row, body, customer_id=customer_id
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return out


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_expertgranskning_session_route(
    session_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> Response:
    row, _customer_id = await _require_session(session, user, session_id)
    try:
        await delete_expertgranskning_session(session, row)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return Response(status_code=204)


@router.post("/sessions/{session_id}/run", status_code=202)
async def post_expertgranskning_session_run(
    session_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> dict[str, str]:
    row, _customer_id = await _require_session(session, user, session_id)
    if row.status in {"pending", "running"}:
        raise HTTPException(status_code=409, detail="Panel session already running")

    try:
        await prepare_session_for_run(session, row)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    row.status = "pending"
    row.error = None
    await session.flush()

    job = await jobs_service.create_job(
        session,
        JobCreate(
            kind="panel_session_run",
            label=f"Expertgranskning: {(row.config or {}).get('topic', session_id)[:80]}",
            request={"session_id": session_id},
        ),
    )
    row.job_id = job.id
    await session.commit()
    jobs_service.enqueue_job(job.id)
    return {"job_id": job.id, "session_id": session_id}


async def _require_word_job(
    session: AsyncSession,
    user: UserAccount,
    job_id: str,
) -> Job:
    job = await session.get(Job, job_id)
    if job is None or job.kind != WORD_JOB_KIND:
        raise HTTPException(status_code=404, detail="Word review job not found")
    assert_kund_access(user, job.customer_id)
    assert_job_owner_access(user, job)
    return job


def _panel_visible_to_user(population: Population, user: UserAccount) -> bool:
    if user.role == "admin":
        return True
    return user.kund_id is not None and population.customer_id == user.kund_id


@router.post("/word-jobs", status_code=202)
async def post_expertgranskning_word_job(
    body: ExpertgranskningWordJobCreate,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> dict[str, str]:
    try:
        panel = await require_expert_panel(session, body.panel_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not _panel_visible_to_user(panel, user):
        raise HTTPException(status_code=403, detail="kund_access_denied")

    if body.doc_id:
        existing = await find_latest_word_job_for_doc(
            session,
            doc_id=body.doc_id,
            customer_id=panel.customer_id,
        )
        if existing is not None and existing.status in {"pending", "running"}:
            raise HTTPException(status_code=409, detail="word_review_already_running")

    request = ExpertgranskningWordJobRequest(
        panel_id=body.panel_id,
        customer_id=panel.customer_id,
        owner_user_id=user.id,
        doc_id=body.doc_id,
        word_session_id=body.word_session_id,
        sections=body.sections,
        locale=body.locale,
    )
    job = await jobs_service.create_job(
        session,
        JobCreate(
            kind=WORD_JOB_KIND,
            label="Word-granskning",
            request=request.model_dump(mode="json"),
        ),
    )
    jobs_service.enqueue_job(job.id)
    return {"job_id": job.id}


@router.get("/word-jobs/latest", response_model=ExpertgranskningLatestWordJobOut)
async def get_latest_expertgranskning_word_job(
    doc_id: str = Query(min_length=1, max_length=128),
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> ExpertgranskningLatestWordJobOut:
    job = await find_latest_word_job_for_doc(
        session,
        doc_id=doc_id.strip(),
        customer_id=None if user.role == "admin" else user.kund_id,
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Word review job not found")
    assert_kund_access(user, job.customer_id)
    assert_job_owner_access(user, job)
    actions = await load_word_actions(session, job.id, customer_id=job.customer_id)
    return ExpertgranskningLatestWordJobOut(
        job_id=job.id,
        status=job.status,
        actions=[serialize_word_action(row) for row in actions],
    )


@router.get("/word-jobs/{job_id}/results", response_model=list[ExpertgranskningResultOut])
async def get_expertgranskning_word_job_results(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> list[ExpertgranskningResultOut]:
    await _require_word_job(session, user, job_id)
    rows = await load_expertgranskning_results(session, job_id)
    return [serialize_result(row) for row in rows]


@router.get("/word-jobs/{job_id}/actions", response_model=list[WordActionOut])
async def get_expertgranskning_word_job_actions(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> list[WordActionOut]:
    job = await _require_word_job(session, user, job_id)
    rows = await load_word_actions(session, job_id, customer_id=job.customer_id)
    return [serialize_word_action(row) for row in rows]


def _application_http_result(mutation, *, reject_detail: str) -> WordActionOut:
    if mutation.row is None:
        raise HTTPException(status_code=404, detail="Word action not found")
    if not mutation.accepted:
        raise HTTPException(status_code=409, detail=reject_detail)
    return serialize_word_action(mutation.row)


@router.post(
    "/word-jobs/{job_id}/actions/{action_id}/claim",
    response_model=WordActionOut,
)
async def claim_expertgranskning_word_action(
    job_id: str,
    action_id: str,
    body: WordApplicationClaimIn,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> WordActionOut:
    job = await _require_word_job(session, user, job_id)
    mutation = await claim_application(
        session,
        job_id=job_id,
        action_id=action_id,
        application_id=body.application_id,
        customer_id=job.customer_id,
    )
    out = _application_http_result(
        mutation, reject_detail="application_not_claimable"
    )
    if mutation.reason == "claimed":
        await publish_action_updated(mutation.row)
    return out


@router.post(
    "/word-jobs/{job_id}/actions/{action_id}/complete",
    response_model=WordActionOut,
)
async def complete_expertgranskning_word_action(
    job_id: str,
    action_id: str,
    body: WordApplicationCompleteIn,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> WordActionOut:
    job = await _require_word_job(session, user, job_id)
    mutation = await complete_application(
        session,
        job_id=job_id,
        action_id=action_id,
        application_id=body.application_id,
        word_artifact_id=body.word_artifact_id,
        customer_id=job.customer_id,
    )
    out = _application_http_result(
        mutation, reject_detail="application_not_completable"
    )
    if mutation.reason == "completed":
        await publish_action_updated(mutation.row)
    return out


@router.post(
    "/word-jobs/{job_id}/actions/{action_id}/unresolved",
    response_model=WordActionOut,
)
async def mark_expertgranskning_word_action_unresolved(
    job_id: str,
    action_id: str,
    body: WordApplicationUnresolvedIn,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> WordActionOut:
    job = await _require_word_job(session, user, job_id)
    mutation = await mark_application_unresolved(
        session,
        job_id=job_id,
        action_id=action_id,
        reason=body.reason,
        application_id=body.application_id,
        customer_id=job.customer_id,
    )
    out = _application_http_result(
        mutation, reject_detail="application_not_unresolvable"
    )
    if mutation.reason == "unresolved":
        await publish_action_updated(mutation.row)
    return out


@router.post(
    "/word-jobs/{job_id}/actions/{action_id}/dismiss",
    response_model=WordActionOut,
)
async def dismiss_expertgranskning_word_action(
    job_id: str,
    action_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> WordActionOut:
    job = await _require_word_job(session, user, job_id)
    mutation = await dismiss_application(
        session,
        job_id=job_id,
        action_id=action_id,
        customer_id=job.customer_id,
    )
    out = _application_http_result(
        mutation, reject_detail="application_not_dismissible"
    )
    if mutation.reason == "dismissed":
        await publish_action_updated(mutation.row)
    return out
