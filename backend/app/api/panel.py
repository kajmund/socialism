"""Panel session API."""

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
from app.services.dd.campaigns import get_campaign
from app.services.panel.schemas import PanelSessionCreate, PanelSessionOut
from app.services.panel.sessions import create_panel_session, get_panel_session, serialize_panel_session

router = APIRouter(prefix="/panel", tags=["panel"])

_SUPPORTED_PROTOCOLS = {"generic_panel", "dd_panel"}


async def _assert_panel_session_access(
    session: AsyncSession,
    user: UserAccount,
    *,
    session_id: str,
    campaign_id: int | None,
) -> None:
    if campaign_id is not None:
        customer_id = await customer_id_for_panel_session(session, session_id)
        assert_kund_access(user, customer_id)
        return
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="admin_required")


@router.post("/sessions", response_model=PanelSessionOut, status_code=201)
async def post_panel_session(
    body: PanelSessionCreate,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> PanelSessionOut:
    if body.config.protocol not in _SUPPORTED_PROTOCOLS:
        raise HTTPException(status_code=400, detail="Unsupported protocol")
    if body.config.campaign_id is not None:
        campaign = await get_campaign(session, body.config.campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="Campaign not found")
        assert_kund_access(user, campaign.customer_id)
    elif user.role != "admin":
        raise HTTPException(status_code=403, detail="admin_required")
    try:
        out = await create_panel_session(session, body)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    return out


@router.get("/sessions/{session_id}", response_model=PanelSessionOut)
async def get_panel_session_by_id(
    session_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> PanelSessionOut:
    row = await get_panel_session(session, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Panel session not found")
    await _assert_panel_session_access(
        session, user, session_id=session_id, campaign_id=row.campaign_id
    )
    return serialize_panel_session(row)


@router.post("/sessions/{session_id}/run", status_code=202)
async def post_panel_session_run(
    session_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> dict[str, str]:
    row = await get_panel_session(session, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Panel session not found")
    await _assert_panel_session_access(
        session, user, session_id=session_id, campaign_id=row.campaign_id
    )
    if row.status in {"pending", "running"}:
        raise HTTPException(status_code=409, detail="Panel session already running")
    if row.protocol not in _SUPPORTED_PROTOCOLS:
        raise HTTPException(status_code=400, detail="Unsupported protocol")

    row.status = "pending"
    row.error = None
    await session.flush()

    request: dict[str, object] = {"session_id": session_id}
    if row.campaign_id is not None:
        request["campaign_id"] = row.campaign_id
    candidate_id = (row.config or {}).get("candidate_id")
    if isinstance(candidate_id, str) and candidate_id:
        request["candidate_id"] = candidate_id
    job = await jobs_service.create_job(
        session,
        JobCreate(
            kind="panel_session_run",
            label=f"Panel: {row.config.get('topic', session_id)[:80]}",
            request=request,
        ),
    )
    row.job_id = job.id
    await session.commit()
    jobs_service.enqueue_job(job.id)
    return {"job_id": job.id, "session_id": session_id}
