"""Facit QA rejects off-topic sufficient cases and Jev-derived facit."""

from __future__ import annotations

from app.services.research.sufficiency_experiment.facit_qa import (
    FacitCase,
    FacitEvidence,
    FacitRelation,
    FacitReview,
    validate_facit,
)


def _case(
    case_id: str,
    question: str,
    excerpt: str,
    *,
    decision: str = "sufficient",
    provenance: dict[str, object] | None = None,
) -> FacitCase:
    return FacitCase(
        case_id=case_id,
        version="v2",
        status="valid",
        plan_question=question,
        expected_decision=decision,
        evidence=(
            FacitEvidence(
                evidence_id="e1",
                excerpt=excerpt,
                status="found",
                provenance=provenance or {},
            ),
        ),
        relations=(FacitRelation(evidence_ids=("e1",), relation="supportive"),),
        rationale="test",
        review=FacitReview(method="deterministic", reviewed_by="agent"),
    )


def test_off_topic_sufficient_facit_is_rejected() -> None:
    case = _case(
        "off-topic",
        "Vilka avgöranden har tillämpat 36 § avtalslagen?",
        "Uppsägningstiden är tre månader för avtalet.",
    )
    validation = validate_facit((case,))
    assert any("off-topic" in error for error in validation.errors)


def test_on_topic_sufficient_facit_passes() -> None:
    case = _case(
        "on-topic",
        "Vilken uppsägningstid gäller?",
        "Uppsägningstiden är tre månader för avtalet.",
    )
    validation = validate_facit((case,))
    assert not validation.errors


def test_invalid_case_requires_reason() -> None:
    case = _case("invalid", "Fråga?", "Svar.", decision="sufficient")
    object.__setattr__(case, "status", "invalid")
    validation = validate_facit((case,))
    assert any("lacks reason" in error for error in validation.errors)


def test_jev_based_review_is_rejected() -> None:
    case = _case("jev-review", "Fråga?", "Svar.")
    object.__setattr__(
        case,
        "review",
        FacitReview(method="jev", reviewed_by="agent"),
    )
    validation = validate_facit((case,))
    assert any("reuse Jev" in error for error in validation.errors)


def test_v2b_low_lexical_with_provenance_warns() -> None:
    case = _case(
        "low-lexical",
        "Vilka avgöranden har tillämpat 36 § avtalslagen?",
        "Uppsägningstiden är tre månader för avtalet.",
        provenance={"entity_id": "avtal-a"},
    )
    validation = validate_facit((case,), policy="v2b")
    assert not validation.errors
    assert any("independent review required" in warning for warning in validation.warnings)


def test_v2b_low_lexical_without_provenance_is_still_invalid() -> None:
    case = _case(
        "low-lexical-no-provenance",
        "Vilka avgöranden har tillämpat 36 § avtalslagen?",
        "Uppsägningstiden är tre månader för avtalet.",
    )
    validation = validate_facit((case,), policy="v2b")
    assert any("off-topic" in error for error in validation.errors)
