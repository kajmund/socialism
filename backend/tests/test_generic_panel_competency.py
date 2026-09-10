"""Competency gating for generic_panel research-need and raise-hand."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.llm import set_structured_completer, set_text_completer, set_tools_completer
from app.services.panel.engine import run_generic_panel
from app.services.panel.raise_hand import parse_raise_hand_reply, raise_hand_is_yes
from app.services.panel.research import (
    ConsolidatedResearchNeed,
    ExpertResearchNeeds,
    MISSING_EXPERTISE_SIGNAL,
    ModeratorResearchPlan,
    ResearchNeedDraft,
    ResearchPlan,
    format_expert_research_need_turn,
)
from app.services.panel.schemas import PanelExpertSlot, PanelSessionConfig, PanelSessionCreate
from app.services.panel.sessions import create_panel_session, get_panel_session
from app.services.panel.synthesis import GenericPanelSynthesis
from app.services.prompt_catalog import default_prompts, render_prompt


def _wrong_panel_config() -> PanelSessionConfig:
    return PanelSessionConfig(
        protocol="generic_panel",
        topic="Vad är rekvisiten för dråp vid självförsvar?",
        brief="Straffrättslig fråga om Brottsbalken 3:2 och nödvärn.",
        max_rounds=2,
        expert_slots=[
            PanelExpertSlot(
                slot_id="dd",
                label="Nils",
                profile="Due diligence / M&A-transaktioner",
            ),
            PanelExpertSlot(
                slot_id="val",
                label="Rolf",
                profile="Bolagsvärdering och finansiell analys",
            ),
            PanelExpertSlot(
                slot_id="mkt",
                label="Mira",
                profile="Marknadsanalys och konkurrens",
            ),
            PanelExpertSlot(
                slot_id="pmo",
                label="Pia",
                profile="PMO, ERP och integrationsprocesser",
            ),
        ],
    )


def _criminal_law_config() -> PanelSessionConfig:
    return PanelSessionConfig(
        protocol="generic_panel",
        topic="Vad är rekvisiten för dråp vid självförsvar?",
        brief="Straffrättslig fråga om Brottsbalken 3:2 och nödvärn.",
        max_rounds=1,
        expert_slots=[
            PanelExpertSlot(
                slot_id="crime",
                label="Straffrättsjurist",
                profile="Straffrätt, Brottsbalken och nödvärn",
            )
        ],
    )


def _fake_criminal_need() -> ResearchNeedDraft:
    return ResearchNeedDraft(
        question="Vad säger BrB 3:2 och BrB 24:1 om dråp och nödvärn?",
        why_needed="Behövs för rekvisit och proportionalitet.",
        source_types=["swedish_law"],
    )


def _turns_by_phase(transcript: list[dict], phase: str) -> list[dict]:
    return [row for row in transcript if row["phase"] == phase]


async def _run_panel(factory, config: PanelSessionConfig):
    prompts = default_prompts("sv")
    async with factory() as db:
        created = await create_panel_session(db, PanelSessionCreate(config=config))
        row = await get_panel_session(db, created.id)
        assert row is not None
        await run_generic_panel(db, row, prompts)
        await db.commit()
        return row


def _install_llm(
    *,
    expert_needs: dict[str, ExpertResearchNeeds] | ExpertResearchNeeds,
    raise_replies: dict[str, str] | str = "JA",
    expert_turns: dict[str, str] | str = "Sakbedömning.",
    unanswered: str = "Frågan är unanswered på grund av missing expertise.",
    plan: ModeratorResearchPlan | None = None,
    synthesis: GenericPanelSynthesis | None = None,
) -> list[str]:
    seen_users: list[str] = []

    async def _complete(messages, *, model=None):
        user = messages[-1]["content"]
        seen_users.append(user)
        identity = ""
        for item in messages:
            if item.get("role") == "system":
                identity += item["content"]
        if "JA eller NEJ" in user or "YES or NO" in user:
            if isinstance(raise_replies, str):
                return raise_replies
            for label, reply in raise_replies.items():
                if f"som {label} i en expertpanel" in identity:
                    return reply
            return "NEJ"
        if "privata anteckningar" in user or "private notes" in user.lower():
            return "Pad"
        if "offentliga inlägg" in user or "public contribution" in user.lower():
            if isinstance(expert_turns, str):
                return expert_turns
            for label, reply in expert_turns.items():
                if f"som {label} i en expertpanel" in identity:
                    return reply
            return "Sakbedömning."
        if "missing expertise" in user and "Ingen expert" in user:
            return unanswered
        if "strukturerad syntes" in user or "structured synthesis" in user.lower():
            return "Fri analys."
        if "Öppna panelen" in user or "Open the panel" in user:
            return "Välkommen. Vad är rekvisiten för dråp vid självförsvar?"
        if "Det här är delfråga" in user or "This is sub-question" in user:
            return "Hur relaterar nödvärn till ERP-processer?"
        return "Svar"

    async def _tools(messages, tools=None):
        return SimpleNamespace(content=await _complete(messages), tool_calls=None)

    async def _structured(messages, response_model):
        if response_model is ExpertResearchNeeds:
            if isinstance(expert_needs, ExpertResearchNeeds):
                return expert_needs
            identity = ""
            for item in messages:
                if item.get("role") == "system":
                    identity += item["content"]
            for key, bundle in expert_needs.items():
                if f"som {key} i en expertpanel" in identity:
                    return bundle
            return ExpertResearchNeeds(has_domain_competence=False)
        if response_model is ModeratorResearchPlan:
            return plan if plan is not None else ModeratorResearchPlan()
        if response_model is GenericPanelSynthesis:
            return synthesis or GenericPanelSynthesis(summary="Lucka.", claims=[], unanswered=[])
        raise RuntimeError(f"Unexpected structured model {response_model}")

    set_text_completer(_complete)
    set_tools_completer(_tools)
    set_structured_completer(_structured)
    return seen_users


def test_out_of_domain_research_needs_are_dropped():
    bundle = ExpertResearchNeeds(
        has_domain_competence=False,
        competence_reason="missing expertise / requires domain expert",
        needs=[_fake_criminal_need()],
    )
    assert bundle.needs == []
    text = format_expert_research_need_turn(bundle)
    assert MISSING_EXPERTISE_SIGNAL in text
    assert "BrB" not in text

    contradicted = ExpertResearchNeeds(
        has_domain_competence=True,
        competence_reason="Faller utanför mitt kompetensområde, men här är BrB 3:2.",
        needs=[_fake_criminal_need()],
    )
    assert contradicted.has_domain_competence is False
    assert contradicted.needs == []


def test_raise_hand_yes_requires_competence_not_disclaimer():
    assert raise_hand_is_yes("JA") is True
    assert raise_hand_is_yes("YES") is True
    assert raise_hand_is_yes("NEJ") is False
    assert raise_hand_is_yes("Jag avstår i sakfrågan") is False
    assert (
        raise_hand_is_yes(
            "JA\nJag avstår i sakfrågan — faller utanför mitt kompetensområde."
        )
        is False
    )
    assert raise_hand_is_yes("JA\nAllmän orientering från PMO.") is False
    assert parse_raise_hand_reply("JA\nStraffrätt är min kärnkompetens.")[0] is True
    assert raise_hand_is_yes("JA\nStraffrätt är min kärnkompetens.") is True


def test_research_and_raise_hand_prompts_require_domain_competence():
    prompts = default_prompts("sv")
    research = render_prompt(
        prompts,
        "panel.expert.research_need",
        topic="Dråp",
        brief="Nödvärn",
        opening="Öppning",
        profile="M&A",
        source_types="- swedish_law",
    )
    raise_hand = render_prompt(
        prompts,
        "panel.expert.raise_hand",
        topic="Dråp",
        transcript="Öppning",
        scratchpad="(tom)",
    )
    missing = render_prompt(
        prompts,
        "panel.moderator.missing_expertise",
        topic="Dråp",
        brief="Nödvärn",
        expert_list="- Pia: PMO",
    )
    assert "has_domain_competence" in research
    assert "missing expertise" in research
    assert "Analogier" in research
    assert "faktisk domänkompetens" in raise_hand
    assert "Svara endast JA eller NEJ" in raise_hand
    assert "utanför mitt kompetensområde" in raise_hand
    assert "missing expertise" in missing
    assert "analogier" in missing


@pytest.mark.asyncio
async def test_wrong_panel_stops_with_missing_expertise(client_db):
    _client, factory = client_db
    fake_needs = ExpertResearchNeeds(
        has_domain_competence=False,
        competence_reason="missing expertise / requires domain expert",
        needs=[_fake_criminal_need()],
    )
    seen = _install_llm(
        expert_needs={
            "Nils": fake_needs,
            "Rolf": fake_needs,
            "Mira": fake_needs,
            "Pia": fake_needs,
        },
        raise_replies="JA\nJag avstår i sakfrågan — faller utanför mitt kompetensområde.",
        unanswered="Huvudfrågan är unanswered: missing expertise. Panelen saknar straffrätt.",
        synthesis=GenericPanelSynthesis(
            summary="Ingen relevant kompetens.",
            claims=[],
            unanswered=[],
        ),
    )
    row = await _run_panel(factory, _wrong_panel_config())
    plan = ResearchPlan.model_validate(row.research_plan)
    assert plan.needs == []
    research_turns = _turns_by_phase(row.transcript, "research_need")
    assert len(research_turns) == 4
    assert all(MISSING_EXPERTISE_SIGNAL in turn["content"] for turn in research_turns)
    assert all("BrB" not in turn["content"] for turn in research_turns)
    assert _turns_by_phase(row.transcript, "raise_hand") == []
    assert _turns_by_phase(row.transcript, "expert") == []
    assert _turns_by_phase(row.transcript, "scratchpad") == []
    assert _turns_by_phase(row.transcript, "sub_question") == []
    unanswered = _turns_by_phase(row.transcript, "unanswered")
    assert len(unanswered) == 1
    assert "missing expertise" in unanswered[0]["content"]
    assert row.result["claims"] == []
    assert row.result["unanswered"]
    assert "missing expertise" in row.result["unanswered"][0]
    assert not any("ERP-processer" in text for text in seen)


@pytest.mark.asyncio
async def test_criminal_law_expert_still_researches_and_raises(client_db):
    _client, factory = client_db
    _install_llm(
        expert_needs={
            "Straffrättsjurist": ExpertResearchNeeds(
                has_domain_competence=True,
                competence_reason="Straffrätt är min kärnkompetens.",
                needs=[_fake_criminal_need()],
            )
        },
        plan=ModeratorResearchPlan(
            needs=[
                ConsolidatedResearchNeed(
                    question="Vad säger BrB 3:2 och BrB 24:1 om dråp och nödvärn?",
                    why_needed="Behövs för rekvisit och proportionalitet.",
                    proposal_ids=["proposal_1"],
                    source_types=["swedish_law"],
                )
            ]
        ),
        raise_replies="JA",
        expert_turns="Rekvisiten för dråp och nödvärn följer BrB 3:2 och 24:1.",
        synthesis=GenericPanelSynthesis(
            summary="Straffrättsexperten identifierade rekvisiten.",
            claims=[],
            unanswered=[],
        ),
    )
    row = await _run_panel(factory, _criminal_law_config())
    plan = ResearchPlan.model_validate(row.research_plan)
    assert len(plan.needs) == 1
    assert "BrB 3:2" in plan.needs[0].question
    research = _turns_by_phase(row.transcript, "research_need")
    assert len(research) == 1
    assert "BrB 3:2" in research[0]["content"]
    assert MISSING_EXPERTISE_SIGNAL not in research[0]["content"]
    raise_hands = _turns_by_phase(row.transcript, "raise_hand")
    assert [turn["content"] for turn in raise_hands] == ["JA"]
    experts = _turns_by_phase(row.transcript, "expert")
    assert experts
    assert "BrB 3:2" in experts[0]["content"]
    assert _turns_by_phase(row.transcript, "unanswered") == []


@pytest.mark.asyncio
async def test_competent_experts_may_all_abstain(client_db):
    _client, factory = client_db
    _install_llm(
        expert_needs=ExpertResearchNeeds(
            has_domain_competence=True,
            competence_reason="Straffrätt är min kompetens, men jag avstår den här rundan.",
        ),
        raise_replies="NEJ",
        synthesis=GenericPanelSynthesis(
            summary="Kompetent expert avstod.",
            claims=[],
            unanswered=["Ingen expert valde att svara."],
        ),
    )
    row = await _run_panel(factory, _criminal_law_config())
    assert _turns_by_phase(row.transcript, "unanswered") == []
    assert [turn["content"] for turn in _turns_by_phase(row.transcript, "raise_hand")] == [
        "NEJ"
    ]
    assert _turns_by_phase(row.transcript, "expert") == []
    assert row.result["claims"] == []
