"""Panel session API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.schemas.domain import JobCreate
from app.services import jobs as jobs_service
from app.services.panel.engine import run_generic_panel
from app.services.panel.schemas import PanelSessionCreate, PanelSessionOut
from app.services.panel.sessions import create_panel_session, get_panel_session, serialize_panel_session
from app.services.prompt_store import require_active_prompts

router = APIRouter(prefix="/panel", tags=["panel"])


@router.post("/sessions", response_model=PanelSessionOut, status_code=201)
async def post_panel_session(
    body: PanelSessionCreate,
    session: AsyncSession = Depends(get_session),
) -> PanelSessionOut:
    if body.config.protocol != "generic_panel":
        raise HTTPException(status_code=400, detail="Unsupported protocol")
    out = await create_panel_session(session, body)
    await session.commit()
    return out


@router.get("/sessions/{session_id}", response_model=PanelSessionOut)
async def get_panel_session_by_id(
    session_id: str,
    session: AsyncSession = Depends(get_session),
) -> PanelSessionOut:
    row = await get_panel_session(session, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Panel session not found")
    return serialize_panel_session(row)


@router.post("/sessions/{session_id}/run", status_code=202)
async def post_panel_session_run(
    session_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    row = await get_panel_session(session, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Panel session not found")
    if row.status in {"pending", "running"}:
        raise HTTPException(status_code=409, detail="Panel session already running")

    row.status = "pending"
    row.error = None
    await session.flush()

    job = await jobs_service.create_job(
        session,
        JobCreate(
            kind="panel_session_run",
            label=f"Panel: {row.config.get('topic', session_id)[:80]}",
            request={"session_id": session_id},
        ),
    )
    row.job_id = job.id
    await session.commit()
    jobs_service.enqueue_job(job.id)
    return {"job_id": job.id, "session_id": session_id}
