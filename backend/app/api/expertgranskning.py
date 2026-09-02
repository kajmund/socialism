"""Expertgranskning module API — free-text document + saved expert panel."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.scope import assert_kund_access
from app.database.models import UserAccount
from app.database.session import get_session
from app.schemas.domain import JobCreate
from app.services import jobs as jobs_service
from app.services.customer_scope import customer_id_for_panel_session
from app.services.expertgranskning.schemas import (
    ExpertgranskningSessionCreate,
    ExpertgranskningSessionOut,
)
from app.services.expertgranskning.sessions import (
    create_expertgranskning_session,
    is_expertgranskning_session,
    resolve_customer_id,
    serialize_expertgranskning_session,
)
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
    return row


@router.post("/sessions", response_model=ExpertgranskningSessionOut, status_code=201)
async def post_expertgranskning_session(
    body: ExpertgranskningSessionCreate,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> ExpertgranskningSessionOut:
    if not body.document_text:
        raise HTTPException(status_code=400, detail="document_text is required")
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
    row = await _require_session(session, user, session_id)
    return serialize_expertgranskning_session(row)


@router.post("/sessions/{session_id}/run", status_code=202)
async def post_expertgranskning_session_run(
    session_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> dict[str, str]:
    row = await _require_session(session, user, session_id)
    if row.status in {"pending", "running"}:
        raise HTTPException(status_code=409, detail="Panel session already running")

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
