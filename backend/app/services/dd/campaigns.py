"""DD campaign persistence and sourcing orchestration."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import DdCampaign
from app.serializers import format_date
from app.services.dd.allabolag_mock import search_companies
from app.services.dd.candidate_runs import list_candidate_runs, list_run_candidate_ids
from app.services.kund_store import bolag_demo_customer_id
from app.services.dd.schemas import (
    DdCampaignCreate,
    DdCampaignOut,
    DdCampaignUpdate,
    DdCandidateCompany,
    DdCandidateRunOut,
    DdSourcingCriteria,
)


def _default_criteria() -> dict:
    return DdSourcingCriteria().model_dump(mode="json")


def serialize_campaign(
    row: DdCampaign,
    *,
    candidate_runs: list[DdCandidateRunOut] | None = None,
) -> DdCampaignOut:
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
        candidate_runs=list(candidate_runs or []),
        created_at=format_date(row.created_at) if row.created_at else "",
        updated_at=format_date(row.updated_at) if row.updated_at else "",
    )


async def serialize_campaign_detail(session: AsyncSession, row: DdCampaign) -> DdCampaignOut:
    runs = await list_candidate_runs(session, row.id)
    return serialize_campaign(row, candidate_runs=runs)


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
    return [serialize_campaign(row, candidate_runs=[]) for row in rows]


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
    return await serialize_campaign_detail(session, row)


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
    return await serialize_campaign_detail(session, row)


def run_sourcing(criteria: DdSourcingCriteria) -> list[DdCandidateCompany]:
    return search_companies(criteria)


def merge_sourcing_candidates(
    existing_raw: list,
    incoming: list[DdCandidateCompany],
    *,
    protected_candidate_ids: set[str] | None = None,
) -> list[DdCandidateCompany]:
    """Merge sourcing hits into campaign candidates — upsert on organisationsnummer, never drop rows."""
    existing = [DdCandidateCompany.model_validate(c) for c in (existing_raw or [])]
    protected = protected_candidate_ids or set()
    by_orgnr: dict[str, DdCandidateCompany] = {c.organisationsnummer: c for c in existing}
    by_id: dict[str, DdCandidateCompany] = {c.id: c for c in existing}
    order_orgnrs = [c.organisationsnummer for c in existing]

    for candidate in incoming:
        orgnr = candidate.organisationsnummer
        if orgnr not in by_orgnr:
            order_orgnrs.append(orgnr)
        by_orgnr[orgnr] = candidate
        by_id[candidate.id] = candidate

    merged = [by_orgnr[orgnr] for orgnr in order_orgnrs]
    merged_ids = {c.id for c in merged}
    for candidate_id in protected:
        if candidate_id not in merged_ids and candidate_id in by_id:
            merged.append(by_id[candidate_id])
    return merged


async def apply_sourcing_run(
    session: AsyncSession,
    row: DdCampaign,
    criteria: DdSourcingCriteria,
) -> list[DdCandidateCompany]:
    incoming = run_sourcing(criteria)
    protected = await list_run_candidate_ids(session, row.id)
    return merge_sourcing_candidates(
        row.candidates if isinstance(row.candidates, list) else [],
        incoming,
        protected_candidate_ids=protected,
    )
