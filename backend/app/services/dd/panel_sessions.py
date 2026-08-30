"""Create dd_panel sessions from DD campaigns."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.dd.campaigns import get_campaign, resolve_expert_panel_id
from app.services.dd.candidate_runs import get_candidate_run
from app.services.dd.expert_roles import load_expert_slots, load_expert_slots_from_population
from app.services.dd.schemas import DdCandidateCompany, DdResearchDossier
from app.services.panel.dd_engine import _candidate_brief
from app.services.panel.schemas import DdPanelSessionCreateRequest, PanelSessionConfig, PanelSessionCreate
from app.services.panel.sessions import create_panel_session


async def create_dd_panel_session_from_campaign(
    session: AsyncSession,
    body: DdPanelSessionCreateRequest,
) -> tuple[PanelSessionCreate, DdCandidateCompany]:
    campaign = await get_campaign(session, body.campaign_id)
    if campaign is None:
        raise LookupError("Campaign not found")

    candidates = [DdCandidateCompany.model_validate(c) for c in (campaign.candidates or [])]
    candidate = next((c for c in candidates if c.id == body.candidate_id), None)
    if candidate is None:
        raise LookupError(f"Candidate not found: {body.candidate_id}")

    expert_panel_id = resolve_expert_panel_id(campaign, body.candidate_id)
    if expert_panel_id is not None:
        expert_slots = await load_expert_slots_from_population(
            session,
            expert_panel_id,
        )
        role_keys = [slot.slot_id for slot in expert_slots]
    else:
        role_keys = body.expert_role_keys or list(campaign.expert_role_keys or [])
        expert_slots = await load_expert_slots(
            session,
            customer_id=campaign.customer_id,
            role_keys=role_keys or None,
        )

    research = None
    run = await get_candidate_run(
        session,
        campaign_id=body.campaign_id,
        candidate_id=candidate.id,
    )
    if run is not None and isinstance(run.research, dict) and run.research:
        research = DdResearchDossier.model_validate(run.research)

    config = PanelSessionConfig(
        protocol="dd_panel",
        topic=f"Due diligence: {candidate.namn}",
        brief=_candidate_brief(candidate, research=research),
        expert_slots=expert_slots,
        campaign_id=body.campaign_id,
        candidate=candidate,
        candidate_id=candidate.id,
        expert_role_keys=role_keys,
    )
    return PanelSessionCreate(config=config), candidate
