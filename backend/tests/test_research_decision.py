"""Structured epistemic research decision — none is explicit, not implicit."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.panel.competency import CompetencyState, SlotCompetency
from app.services.panel.research import (
    ClaimRequiringVerification,
    ExpertResearchNeeds,
    ResearchAssumption,
    ResearchNeedDraft,
    apply_research_decisions,
    format_expert_research_need_turn,
    unqualified_external_claims,
)
from app.services.panel.schemas import PanelExpertSlot, PanelTurn
from app.services.panel.synthesis import (
    GenericPanelSynthesis,
    SynthesizedClaim,
    panel_result_from_synthesis,
)


def _need() -> ResearchNeedDraft:
    return ResearchNeedDraft(
        question="Vilken praxis gäller hävning?",
        why_needed="Behövs för bedömningen.",
        source_types=["case_knowledge"],
    )


def test_none_decision_is_explicit_and_document_grounded():
    bundle = ExpertResearchNeeds(
        research_decision="none",
        can_answer_from_document=True,
        rationale="Avtalet och briefen räcker för en dokumentförankrad bedömning.",
    )
    assert bundle.needs == []
    assert bundle.claims_requiring_verification == []
    text = format_expert_research_need_turn(bundle, locale="sv")
    assert "Researchbeslut: none" in text
    assert "Inga researchbehov." in text
    assert unqualified_external_claims(bundle, "Klausulen är otydlig i dokumentet.") == []


def test_none_cannot_carry_verification_claims():
    with pytest.raises(ValidationError, match="claims_requiring_verification"):
        ExpertResearchNeeds(
            research_decision="none",
            can_answer_from_document=True,
            rationale="Räcker.",
            claims_requiring_verification=[
                ClaimRequiringVerification(
                    claim="+8 procentenheter är branschstandard",
                    why="Måste beläggas",
                    source_types=["web"],
                )
            ],
        )


def test_precise_external_benchmark_cannot_coexist_with_unqualified_none():
    bundle = ExpertResearchNeeds(
        research_decision="none",
        can_answer_from_document=True,
        rationale="Dokumentet räcker.",
    )
    leaked = unqualified_external_claims(
        bundle,
        "Plus 8 percentage points is industry standard, "
        "30-45 day market norms, 5-year confidentiality, 2x/500% liability.",
    )
    assert leaked
    assert any("industry standard" in item.lower() or "%" in item for item in leaked)


def test_assumption_covers_otherwise_unqualified_benchmark():
    bundle = ExpertResearchNeeds(
        research_decision="none",
        can_answer_from_document=True,
        rationale="Dokumentet räcker.",
        assumptions=[
            ResearchAssumption(
                assumption="+8 percentage points is industry standard",
                materiality="high",
            )
        ],
    )
    assert (
        unqualified_external_claims(
            bundle, "+8 percentage points is industry standard"
        )
        == []
    )


def test_required_decision_needs_at_least_one_need():
    with pytest.raises(ValidationError, match="required"):
        ExpertResearchNeeds(
            research_decision="required",
            can_answer_from_document=False,
            rationale="Måste slås upp.",
        )


def test_recommended_needs_keep_provenance_fields():
    bundle = ExpertResearchNeeds(
        research_decision="recommended",
        can_answer_from_document=False,
        needs=[_need()],
        rationale="Praxis saknas i briefen.",
    )
    assert bundle.needs[0].source_types == ["case_knowledge"]
    text = format_expert_research_need_turn(bundle, locale="en")
    assert "Research decision: recommended" in text
    assert "Vilken praxis gäller hävning?" in text


def test_english_none_turn_stays_english():
    text = format_expert_research_need_turn(
        ExpertResearchNeeds(
            research_decision="none",
            can_answer_from_document=True,
            rationale="The brief is enough.",
        ),
        locale="en",
    )
    assert "No research needs." in text
    assert "Inga researchbehov." not in text


def test_norwegian_research_copy_is_not_swedish():
    text = format_expert_research_need_turn(
        ExpertResearchNeeds(
            research_decision="none",
            can_answer_from_document=True,
            rationale="Dokumentet holder.",
        ),
        locale="nb",
    )
    assert "Ingen researchbehov." in text
    assert "Inga researchbehov." not in text
    assert "Researchbeslutning: none" in text


def test_apply_research_decisions_persists_structured_metadata():
    slot = PanelExpertSlot(slot_id="legal", label="Jurist")
    bundle = ExpertResearchNeeds(
        research_decision="none",
        can_answer_from_document=True,
        rationale="Dokumentet räcker.",
        assumptions=[
            ResearchAssumption(
                assumption="+8 percentage points is industry standard",
                materiality="high",
            )
        ],
    )
    state = apply_research_decisions(
        CompetencyState(
            slots=[
                SlotCompetency(
                    slot_id="legal",
                    label="Jurist",
                    competent=True,
                )
            ]
        ),
        [(slot, bundle)],
    )
    assert state.slots[0].research_decision == "none"
    assert state.slots[0].assumptions == ["+8 percentage points is industry standard"]


def test_synthesis_drops_unqualified_external_claim_after_none_decision():
    competency = CompetencyState(
        slots=[
            SlotCompetency(
                slot_id="legal",
                label="Jurist",
                competent=True,
                research_decision="none",
            )
        ]
    )
    transcript = [
        PanelTurn(
            turn_id="e1",
            speaker="Jurist",
            phase="expert",
            slot_id="legal",
            content="Plus 8 percentage points is industry standard.",
        )
    ]
    result = panel_result_from_synthesis(
        GenericPanelSynthesis(
            summary="En punkt.",
            claims=[
                SynthesizedClaim(
                    claim="Plus 8 percentage points is industry standard.",
                    evidence="Expertprosa.",
                    judgment="Så är marknaden.",
                    claim_basis="research",
                    external_normative=True,
                ),
                SynthesizedClaim(
                    claim="Klausulen är otydlig i dokumentet.",
                    evidence="Avtalstexten.",
                    judgment="Behöver skärpas.",
                    claim_basis="document",
                    external_normative=False,
                ),
            ],
        ),
        transcript=transcript,
        competency=competency,
    )
    assert [row.claim for row in result.claims] == ["Klausulen är otydlig i dokumentet."]


def test_structured_external_flag_blocks_even_without_regex_match():
    competency = CompetencyState(
        slots=[
            SlotCompetency(
                slot_id="legal",
                label="Jurist",
                competent=True,
                research_decision="none",
            )
        ]
    )
    result = panel_result_from_synthesis(
        GenericPanelSynthesis(
            summary="En punkt.",
            claims=[
                SynthesizedClaim(
                    claim="Marknadspraxis är väletablerad för den här typen av avtal.",
                    evidence="Allmän orientering.",
                    judgment="Det är standard.",
                    claim_basis="research",
                    external_normative=True,
                )
            ],
        ),
        transcript=[
            PanelTurn(
                turn_id="e1",
                speaker="Jurist",
                phase="expert",
                slot_id="legal",
                content="Marknadspraxis är väletablerad för den här typen av avtal.",
            )
        ],
        competency=competency,
    )
    assert result.claims == []


def test_assumption_metadata_allows_otherwise_blocked_claim():
    competency = CompetencyState(
        slots=[
            SlotCompetency(
                slot_id="legal",
                label="Jurist",
                competent=True,
                research_decision="none",
                assumptions=["+8 percentage points is industry standard"],
            )
        ]
    )
    result = panel_result_from_synthesis(
        GenericPanelSynthesis(
            summary="En punkt.",
            claims=[
                SynthesizedClaim(
                    claim="+8 percentage points is industry standard",
                    evidence="Antagande i researchbeslutet.",
                    judgment="Bärs som antagande.",
                    claim_basis="assumption",
                    external_normative=True,
                )
            ],
        ),
        transcript=[
            PanelTurn(
                turn_id="e1",
                speaker="Jurist",
                phase="expert",
                slot_id="legal",
                content="+8 percentage points is industry standard",
            )
        ],
        competency=competency,
    )
    assert [row.claim for row in result.claims] == [
        "+8 percentage points is industry standard"
    ]
