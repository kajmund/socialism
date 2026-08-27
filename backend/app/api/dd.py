"""DD module API — campaigns and mock sourcing."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.services.dd.campaigns import (
    create_campaign,
    get_campaign,
    list_campaigns,
    run_sourcing,
    serialize_campaign,
    update_campaign,
)
from app.services.dd.schemas import (
    DdCampaignCreate,
    DdCampaignOut,
    DdCampaignUpdate,
    DdSourcingCriteria,
    DdSourcingSearchRequest,
    DdSourcingSearchResponse,
)

router = APIRouter(prefix="/dd", tags=["dd"])


@router.get("/campaigns", response_model=list[DdCampaignOut])
async def get_campaigns(
    module: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[DdCampaignOut]:
    return await list_campaigns(session, module=module)


@router.post("/campaigns", response_model=DdCampaignOut, status_code=201)
async def post_campaign(
    body: DdCampaignCreate,
    session: AsyncSession = Depends(get_session),
) -> DdCampaignOut:
    row = await create_campaign(session, body)
    await session.commit()
    return row


@router.get("/campaigns/{campaign_id}", response_model=DdCampaignOut)
async def get_campaign_by_id(
    campaign_id: int,
    session: AsyncSession = Depends(get_session),
) -> DdCampaignOut:
    row = await get_campaign(session, campaign_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return serialize_campaign(row)


@router.patch("/campaigns/{campaign_id}", response_model=DdCampaignOut)
async def patch_campaign(
    campaign_id: int,
    body: DdCampaignUpdate,
    session: AsyncSession = Depends(get_session),
) -> DdCampaignOut:
    row = await get_campaign(session, campaign_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    out = await update_campaign(session, row, body)
    await session.commit()
    return out


@router.post("/sourcing/search", response_model=DdSourcingSearchResponse)
async def post_sourcing_search(body: DdSourcingSearchRequest) -> DdSourcingSearchResponse:
    candidates = run_sourcing(body.criteria)
    return DdSourcingSearchResponse(candidates=candidates)


@router.post("/campaigns/{campaign_id}/sourcing/run", response_model=DdCampaignOut)
async def post_campaign_sourcing_run(
    campaign_id: int,
    session: AsyncSession = Depends(get_session),
) -> DdCampaignOut:
    row = await get_campaign(session, campaign_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    criteria = DdSourcingCriteria.model_validate(row.criteria or {})
    candidates = run_sourcing(criteria)
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
