"""Structured epistemic research decision — none is explicit, not implicit."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.panel.research import (
    ClaimRequiringVerification,
    ExpertResearchNeeds,
    ResearchAssumption,
    ResearchNeedDraft,
    format_expert_research_need_turn,
    unqualified_external_claims,
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
