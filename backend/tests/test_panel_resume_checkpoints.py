"""Committed panel decisions are reused exactly after a crash."""

from __future__ import annotations

import pytest

from app.services.panel import engine
from app.services.panel.competency import CompetencyState, SlotCompetency
from app.services.panel.research import ExpertResearchNeeds, ResearchPlan
from app.services.panel.result import PanelResult
from app.services.panel.schemas import (
    PanelExpertSlot,
    PanelSessionConfig,
    PanelSessionCreate,
)
from app.services.panel.sessions import create_panel_session, get_panel_session
from app.services.panel.watch import load_transcript
from app.services.prompt_catalog import default_prompts


def _config() -> PanelSessionConfig:
    return PanelSessionConfig(
        protocol="generic_panel",
        topic="Avtalsrättslig fråga",
        brief="Ett kort avtal.",
        max_rounds=1,
        expert_slots=[
            PanelExpertSlot(
                slot_id="contract",
                label="Avtalsjurist",
                profile="Svensk avtalsrätt",
            )
        ],
    )


@pytest.mark.asyncio
async def test_resume_reuses_committed_competency(monkeypatch, client_db):
    _client, factory = client_db
    calls = {
        "opening": 0,
        "competency": 0,
        "raise": 0,
        "scratchpad": 0,
        "expert": 0,
        "analysis": 0,
        "synthesis": 0,
    }
    competency = CompetencyState(
        slots=[
            SlotCompetency(
                slot_id="contract",
                label="Avtalsjurist",
                competent=True,
                reason="Avtalsrätt är kärnkompetens.",
            )
        ]
    )

    async def opening(*_args, **_kwargs):
        calls["opening"] += 1
        return "Öppning"

    async def assess(*_args, **_kwargs):
        calls["competency"] += 1
        return competency

    async def raise_hand(*_args, **_kwargs):
        calls["raise"] += 1
        return True

    async def scratchpad(*_args, **_kwargs):
        calls["scratchpad"] += 1
        return "Intern analys"

    async def expert(*_args, **_kwargs):
        calls["expert"] += 1
        return "Expertsvar"

    async def analysis(*_args, **_kwargs):
        calls["analysis"] += 1
        return "Moderatoranalys"

    async def synthesis(*_args, **_kwargs):
        calls["synthesis"] += 1
        if calls["synthesis"] == 1:
            raise RuntimeError("crash after committed turns")
        return PanelResult(
            protocol="generic_panel",
            summary="Klar efter resume",
            competency=competency.slots,
        )

    monkeypatch.setattr(engine, "_moderator_opening", opening)
    monkeypatch.setattr(engine, "assess_panel_competency", assess)
    monkeypatch.setattr(engine, "_expert_raise_hand", raise_hand)
    monkeypatch.setattr(engine, "_expert_scratchpad", scratchpad)
    monkeypatch.setattr(engine, "_expert_turn", expert)
    monkeypatch.setattr(engine, "_moderator_analysis", analysis)
    monkeypatch.setattr(engine, "synthesize_generic_panel_result", synthesis)

    async with factory() as db:
        created = await create_panel_session(db, PanelSessionCreate(config=_config()))
        row = await get_panel_session(db, created.id)
        assert row is not None
        with pytest.raises(RuntimeError, match="crash after committed turns"):
            await engine.run_generic_panel(
                db,
                row,
                default_prompts("sv"),
                frozen_evidence=True,
            )

        crashed = await get_panel_session(db, created.id)
        assert crashed is not None
        opening_turn = load_transcript(crashed)[0]
        assert opening_turn.checkpoint == {"competency": competency.model_dump(mode="json")}
        before_resume = dict(calls)

        await engine.run_generic_panel(
            db,
            crashed,
            default_prompts("sv"),
            frozen_evidence=True,
        )

    assert calls["synthesis"] == before_resume["synthesis"] + 1
    for name in calls.keys() - {"synthesis"}:
        assert calls[name] == before_resume[name]


@pytest.mark.asyncio
async def test_resume_reuses_committed_research_need(monkeypatch, client_db):
    _client, factory = client_db
    calls = {"collect": 0, "plan": 0}
    bundle = ExpertResearchNeeds(
        has_domain_competence=True,
        competence_reason="Relevant expert.",
        can_answer_from_document=True,
        rationale="Ingen extern research krävs.",
    )

    async def collect(*_args, **_kwargs):
        calls["collect"] += 1
        return bundle

    async def build(*_args, **_kwargs):
        calls["plan"] += 1
        if calls["plan"] == 1:
            raise RuntimeError("crash after committed research need")
        return ResearchPlan()

    monkeypatch.setattr(engine, "collect_expert_research_needs", collect)
    monkeypatch.setattr(engine, "build_research_plan", build)

    async with factory() as db:
        created = await create_panel_session(db, PanelSessionCreate(config=_config()))
        panel = await get_panel_session(db, created.id)
        assert panel is not None
        transcript = load_transcript(panel)
        scratchpads = {"contract": ""}

        with pytest.raises(RuntimeError, match="crash after committed research need"):
            await engine._run_research_plan_phase(
                db,
                panel,
                transcript,
                _config(),
                default_prompts("sv"),
                scratchpads,
                opening="Öppning",
            )
        assert calls == {"collect": 1, "plan": 1}
        stored = load_transcript(panel)
        assert stored[0].checkpoint == bundle.model_dump(mode="json")

        result = await engine._run_research_plan_phase(
            db,
            panel,
            stored,
            _config(),
            default_prompts("sv"),
            scratchpads,
            opening="Öppning",
        )

    assert calls == {"collect": 1, "plan": 2}
    assert result.is_competent("contract")
