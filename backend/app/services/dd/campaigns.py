"""DD campaign persistence and sourcing orchestration."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import DdCampaign
from app.serializers import format_date
from app.services.dd.allabolag_mock import search_companies
from app.services.kund_store import bolag_demo_customer_id
from app.services.dd.schemas import (
    DdCampaignCreate,
    DdCampaignOut,
    DdCampaignUpdate,
    DdCandidateCompany,
    DdSourcingCriteria,
)


def _default_criteria() -> dict:
    return DdSourcingCriteria().model_dump(mode="json")


def serialize_campaign(row: DdCampaign) -> DdCampaignOut:
    criteria_raw = row.criteria if isinstance(row.criteria, dict) else {}
    candidates_raw = row.candidates if isinstance(row.candidates, list) else []
    return DdCampaignOut(
        id=row.id,
        module=row.module,
        title=row.title,
        status=row.status,  # type: ignore[arg-type]
        criteria=DdSourcingCriteria.model_validate(criteria_raw or _default_criteria()),
        candidates=[DdCandidateCompany.model_validate(c) for c in candidates_raw],
        selected_candidate_ids=list(row.selected_candidate_ids or []),
        expert_role_keys=list(row.expert_role_keys or []),
        customer_id=row.customer_id,
        created_at=format_date(row.created_at) if row.created_at else "",
        updated_at=format_date(row.updated_at) if row.updated_at else "",
    )


async def list_campaigns(
    session: AsyncSession,
    *,
    module: str | None = None,
    customer_id: int | None = None,
) -> list[DdCampaignOut]:
    stmt = select(DdCampaign).order_by(DdCampaign.updated_at.desc())
    if module:
        stmt = stmt.where(DdCampaign.module == module)
    if customer_id is not None:
        stmt = stmt.where(DdCampaign.customer_id == customer_id)
    rows = (await session.execute(stmt)).scalars().all()
    return [serialize_campaign(row) for row in rows]


async def get_campaign(session: AsyncSession, campaign_id: int) -> DdCampaign | None:
    return await session.get(DdCampaign, campaign_id)


async def create_campaign(session: AsyncSession, body: DdCampaignCreate) -> DdCampaignOut:
    criteria = body.criteria or DdSourcingCriteria()
    customer_id = await bolag_demo_customer_id(session)
    row = DdCampaign(
        customer_id=customer_id,
        module=body.module,
        title=body.title.strip(),
        status="draft",
        criteria=criteria.model_dump(mode="json"),
        candidates=[],
        selected_candidate_ids=[],
        expert_role_keys=[],
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return serialize_campaign(row)


async def update_campaign(
    session: AsyncSession,
    row: DdCampaign,
    body: DdCampaignUpdate,
) -> DdCampaignOut:
    if body.title is not None:
        row.title = body.title.strip()
    if body.status is not None:
        row.status = body.status
    if body.criteria is not None:
        row.criteria = body.criteria.model_dump(mode="json")
    if body.candidates is not None:
        row.candidates = [c.model_dump(mode="json") for c in body.candidates]
    if body.selected_candidate_ids is not None:
        row.selected_candidate_ids = list(body.selected_candidate_ids)
    if body.expert_role_keys is not None:
        row.expert_role_keys = list(body.expert_role_keys)
    await session.flush()
    await session.refresh(row)
    return serialize_campaign(row)


def run_sourcing(criteria: DdSourcingCriteria) -> list[DdCandidateCompany]:
    return search_companies(criteria)
