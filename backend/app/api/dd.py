"""DD module API — campaigns, company-search chat, and mock search."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.scope import assert_kund_access, effective_customer_id, require_user_kund_id
from app.database.models import DdCampaign, UserAccount
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
from app.schemas.domain import JobCreate, JobOut
from app.services import jobs as jobs_service
from app.services.dd.candidate_runs import (
    clear_research,
    delete_candidate_run,
    get_candidate_run,
    upsert_panel_session,
    upsert_research_job,
)
from app.services.dd.panel_sessions import create_dd_panel_session_from_campaign
from app.services.dd.schemas import (
    DdCampaignCreate,
    DdCampaignOut,
    DdCampaignUpdate,
    DdResearchDossier,
    DdResearchPerson,
    DdResearchStartRequest,
    DdSourcingCriteria,
    DdSourcingChatRequest,
    DdSourcingChatResponse,
    DdSourcingSearchRequest,
    DdSourcingSearchResponse,
)
from app.services.panel.schemas import DdPanelSessionCreateRequest, PanelSessionOut
from app.services.panel.sessions import create_panel_session

router = APIRouter(prefix="/dd", tags=["dd"])


def _norm_person_name(name: str) -> str:
    return " ".join(name.split()).casefold()


def _person_investigated(person: DdResearchPerson) -> bool:
    return bool(person.bolag) or any(bool(hit.url) for hit in person.web_hits)


def _people_research_blocked(dossier: DdResearchDossier, person_names: list[str]) -> bool:
    """True when every targeted person is already investigated — require clear to re-run."""
    by_name = {_norm_person_name(person.namn): person for person in dossier.people}
    if person_names:
        targets = [
            by_name[key]
            for raw in person_names
            if (key := _norm_person_name(raw)) in by_name
        ]
    else:
        targets = list(dossier.people)
    if not targets:
        return False
    return all(_person_investigated(person) for person in targets)


async def _require_campaign(
    session: AsyncSession,
    campaign_id: int,
    user: UserAccount,
) -> DdCampaign:
    row = await get_campaign(session, campaign_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    assert_kund_access(user, row.customer_id)
    return row


@router.get("/campaigns", response_model=list[DdCampaignOut])
async def get_campaigns(
    module: str | None = Query(default=None),
    customer_id: int | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> list[DdCampaignOut]:
    customer_id = effective_customer_id(user, customer_id)
    return await list_campaigns(session, module=module, customer_id=customer_id)


@router.post("/campaigns", response_model=DdCampaignOut, status_code=201)
async def post_campaign(
    body: DdCampaignCreate,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> DdCampaignOut:
    # registry.py imports this router; import here to avoid a cycle.
    from app.modules.registry import module_has_component

    if not module_has_component(body.module, "campaigns"):
        raise HTTPException(
            status_code=400,
            detail=f"Module {body.module!r} does not support campaigns",
        )
    # DdCampaignCreate has no customer_id; non-admin must own the created row.
    customer_id = require_user_kund_id(user) if user.role != "admin" else None
    out = await create_campaign(session, body, customer_id=customer_id)
    await session.commit()
    return out


@router.get("/campaigns/{campaign_id}", response_model=DdCampaignOut)
async def get_campaign_by_id(
    campaign_id: int,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> DdCampaignOut:
    row = await _require_campaign(session, campaign_id, user)
    return await serialize_campaign_detail(session, row)


@router.patch("/campaigns/{campaign_id}", response_model=DdCampaignOut)
async def patch_campaign(
    campaign_id: int,
    body: DdCampaignUpdate,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> DdCampaignOut:
    row = await _require_campaign(session, campaign_id, user)
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
    user: UserAccount = Depends(get_current_user),
) -> None:
    row = await _require_campaign(session, campaign_id, user)
    await delete_campaign(session, row)
    await session.commit()


@router.delete("/campaigns/{campaign_id}/runs/{candidate_id}", status_code=204)
async def delete_campaign_run(
    campaign_id: int,
    candidate_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> None:
    row = await _require_campaign(session, campaign_id, user)
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
async def post_sourcing_search(
    body: DdSourcingSearchRequest,
    _user: UserAccount = Depends(get_current_user),
) -> DdSourcingSearchResponse:
    candidates = run_sourcing(body.criteria)
    return DdSourcingSearchResponse(candidates=candidates)


@router.post("/campaigns/{campaign_id}/sourcing/chat", response_model=DdSourcingChatResponse)
async def post_campaign_sourcing_chat(
    campaign_id: int,
    body: DdSourcingChatRequest,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> DdSourcingChatResponse:
    await _require_campaign(session, campaign_id, user)
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
    user: UserAccount = Depends(get_current_user),
) -> DdCampaignOut:
    row = await _require_campaign(session, campaign_id, user)
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
    "/campaigns/{campaign_id}/candidates/{candidate_id}/research",
    response_model=JobOut,
    status_code=202,
)
async def post_candidate_research(
    campaign_id: int,
    candidate_id: str,
    body: DdResearchStartRequest,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> JobOut:
    row = await _require_campaign(session, campaign_id, user)
    candidates = row.candidates if isinstance(row.candidates, list) else []
    match = next(
        (item for item in candidates if isinstance(item, dict) and item.get("id") == candidate_id),
        None,
    )
    if match is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    run = await get_candidate_run(
        session,
        campaign_id=campaign_id,
        candidate_id=candidate_id,
    )
    existing = (
        DdResearchDossier.model_validate(run.research)
        if run is not None and isinstance(run.research, dict) and run.research
        else None
    )
    if body.mode == "group" and not body.continue_group and existing is not None:
        raise HTTPException(
            status_code=400,
            detail="Rensa research först innan du kartlägger koncernen igen",
        )
    if body.mode == "people" or body.continue_group:
        if existing is None:
            raise HTTPException(status_code=400, detail="Kör koncernkartan först")
        if body.continue_group and not existing.pending:
            raise HTTPException(status_code=400, detail="Inga fler bolag att kartlägga")
        if body.mode == "people" and _people_research_blocked(existing, body.person_names):
            raise HTTPException(
                status_code=400,
                detail="Rensa research först innan du utreder personer igen",
            )
    try:
        job = await jobs_service.create_job(
            session,
            JobCreate(
                kind="dd_research",
                request={
                    "campaign_id": campaign_id,
                    "candidate_id": candidate_id,
                    "mode": body.mode,
                    "person_names": body.person_names,
                    "continue_group": body.continue_group,
                },
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await upsert_research_job(
        session,
        campaign_id=campaign_id,
        candidate_id=candidate_id,
        job_id=job.id,
    )
    await session.commit()
    jobs_service.enqueue_job(job.id)
    return jobs_service.serialize_job(job)


@router.delete(
    "/campaigns/{campaign_id}/candidates/{candidate_id}/research",
    status_code=204,
)
async def delete_candidate_research(
    campaign_id: int,
    candidate_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> None:
    row = await _require_campaign(session, campaign_id, user)
    candidates = row.candidates if isinstance(row.candidates, list) else []
    match = next(
        (item for item in candidates if isinstance(item, dict) and item.get("id") == candidate_id),
        None,
    )
    if match is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    cleared = await clear_research(
        session,
        campaign_id=campaign_id,
        candidate_id=candidate_id,
    )
    if cleared is None:
        await session.commit()
        return
    await session.commit()


@router.post(
    "/campaigns/{campaign_id}/panel-sessions",
    response_model=PanelSessionOut,
    status_code=201,
)
async def post_dd_panel_session(
    campaign_id: int,
    body: DdPanelSessionCreateRequest,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> PanelSessionOut:
    if body.campaign_id != campaign_id:
        raise HTTPException(status_code=400, detail="campaign_id mismatch")
    await _require_campaign(session, campaign_id, user)
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
