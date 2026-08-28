"""DD module API — campaigns, company-search chat, and mock search.

List endpoints accept optional scope query params (customer_id) declared by the
client — not enforced server-side identity until the Auth card lands.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.services.dd.campaigns import (
    apply_sourcing_run,
    clear_panel_assignment,
    create_campaign,
    delete_campaign,
    get_campaign,
    list_campaigns,
    run_sourcing,
    serialize_campaign_detail,
    update_campaign,
)
from app.services.dd.sourcing_chat import SourcingChatError, run_sourcing_chat_turn
from app.services.dd.candidate_runs import delete_candidate_run, upsert_panel_session
from app.services.dd.panel_sessions import create_dd_panel_session_from_campaign
from app.services.dd.schemas import (
    DdCampaignCreate,
    DdCampaignOut,
    DdCampaignUpdate,
    DdSourcingCriteria,
    DdSourcingChatRequest,
    DdSourcingChatResponse,
    DdSourcingSearchRequest,
    DdSourcingSearchResponse,
)
from app.services.panel.schemas import DdPanelSessionCreateRequest, PanelSessionOut
from app.services.panel.sessions import create_panel_session

router = APIRouter(prefix="/dd", tags=["dd"])


@router.get("/campaigns", response_model=list[DdCampaignOut])
async def get_campaigns(
    module: str | None = Query(default=None),
    customer_id: int | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[DdCampaignOut]:
    return await list_campaigns(session, module=module, customer_id=customer_id)


@router.post("/campaigns", response_model=DdCampaignOut, status_code=201)
async def post_campaign(
    body: DdCampaignCreate,
    session: AsyncSession = Depends(get_session),
) -> DdCampaignOut:
    out = await create_campaign(session, body)
    await session.commit()
    return out


@router.get("/campaigns/{campaign_id}", response_model=DdCampaignOut)
async def get_campaign_by_id(
    campaign_id: int,
    session: AsyncSession = Depends(get_session),
) -> DdCampaignOut:
    row = await get_campaign(session, campaign_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return await serialize_campaign_detail(session, row)


@router.patch("/campaigns/{campaign_id}", response_model=DdCampaignOut)
async def patch_campaign(
    campaign_id: int,
    body: DdCampaignUpdate,
    session: AsyncSession = Depends(get_session),
) -> DdCampaignOut:
    row = await get_campaign(session, campaign_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    try:
        out = await update_campaign(session, row, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    return out


@router.delete("/campaigns/{campaign_id}", status_code=204)
async def delete_campaign_by_id(
    campaign_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await get_campaign(session, campaign_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    await delete_campaign(session, row)
    await session.commit()


@router.delete("/campaigns/{campaign_id}/runs/{candidate_id}", status_code=204)
async def delete_campaign_run(
    campaign_id: int,
    candidate_id: str,
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await get_campaign(session, campaign_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    removed_run = await delete_candidate_run(
        session,
        campaign_id=campaign_id,
        candidate_id=candidate_id,
    )
    removed_assignment = clear_panel_assignment(row, candidate_id)
    if not removed_run and not removed_assignment:
        raise HTTPException(status_code=404, detail="Run not found")
    await session.commit()


@router.post("/sourcing/search", response_model=DdSourcingSearchResponse)
async def post_sourcing_search(body: DdSourcingSearchRequest) -> DdSourcingSearchResponse:
    candidates = run_sourcing(body.criteria)
    return DdSourcingSearchResponse(candidates=candidates)


@router.post("/campaigns/{campaign_id}/sourcing/chat", response_model=DdSourcingChatResponse)
async def post_campaign_sourcing_chat(
    campaign_id: int,
    body: DdSourcingChatRequest,
    session: AsyncSession = Depends(get_session),
) -> DdSourcingChatResponse:
    row = await get_campaign(session, campaign_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    try:
        reply, candidates = await run_sourcing_chat_turn(
            session,
            message=body.message,
            history=body.history,
        )
    except SourcingChatError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return DdSourcingChatResponse(reply=reply, candidates=candidates)


@router.post("/campaigns/{campaign_id}/sourcing/run", response_model=DdCampaignOut)
async def post_campaign_sourcing_run(
    campaign_id: int,
    session: AsyncSession = Depends(get_session),
) -> DdCampaignOut:
    row = await get_campaign(session, campaign_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    criteria = DdSourcingCriteria.model_validate(row.criteria or {})
    candidates = await apply_sourcing_run(session, row, criteria)
    out = await update_campaign(
        session,
        row,
        DdCampaignUpdate(
            status="sourcing",
            candidates=candidates,
        ),
    )
    await session.commit()
    return out


@router.post(
    "/campaigns/{campaign_id}/panel-sessions",
    response_model=PanelSessionOut,
    status_code=201,
)
async def post_dd_panel_session(
    campaign_id: int,
    body: DdPanelSessionCreateRequest,
    session: AsyncSession = Depends(get_session),
) -> PanelSessionOut:
    if body.campaign_id != campaign_id:
        raise HTTPException(status_code=400, detail="campaign_id mismatch")
    try:
        create_body, _candidate = await create_dd_panel_session_from_campaign(session, body)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    out = await create_panel_session(session, create_body)
    await upsert_panel_session(
        session,
        campaign_id=campaign_id,
        candidate_id=body.candidate_id,
        panel_session_id=out.id,
    )
    await session.commit()
    return out
