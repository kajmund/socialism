"""B1b synthetic gap cases: coverage metadata looks complete but content differs.

They are run with the scripted Jev client so the only live model is the narrative
gap reviewer. They are not part of the frozen benchmark arm.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.services.research.assessment import AssessableEvidence
from app.services.research.models import ResearchNeed, ResearchPlan
from app.services.research.sufficiency_experiment.golden import GoldenCase


def _case(case_id: str, expected: str, question: str, excerpts: tuple[str, ...]) -> GoldenCase:
    plan = ResearchPlan(
        needs=[
            ResearchNeed(
                id="research_1",
                question=question,
                why_needed="b1b synthetic semantic gap",
                source_types=["case_knowledge"],
            )
        ]
    )
    evidence = tuple(
        AssessableEvidence(
            evidence_id=f"{case_id}-{index}",
            research_need_id="research_1",
            source_type="case_knowledge",
            status="found",
            title=f"{case_id} {index}",
            excerpt=excerpt,
            locator=None,
            source_id=f"{case_id}-source-{index}",
            source_url=None,
            provider="golden",
            score=1.0,
            provenance={},
            retrieved_at=datetime(2026, 4, 1, tzinfo=UTC),
            content_hash=f"{case_id}-hash-{index}",
        )
        for index, excerpt in enumerate(excerpts)
    )
    return GoldenCase(
        case_id=case_id,
        expected=expected,
        expected_status="uncertain",
        signal=excerpts[-1],
        plan=plan,
        evidence=evidence,
    )


def semantic_gap_synonyms() -> GoldenCase:
    return _case(
        "semantic_gap_synonyms",
        "insufficient",
        "Får hundar vistas i stadsparken?",
        (
            "Hundar får vistas i stadsparken enligt lokala ordningsstadgan.",
            "Kommunfullmäktige förbjuder tamdjur i grönområdet.",
        ),
    )


def semantic_gap_hours() -> GoldenCase:
    return _case(
        "semantic_gap_hours",
        "insufficient",
        "Vilken stängningstid gäller för krogarna?",
        (
            "Serveringstillstånd gäller till klockan 02:00 enligt beslutet.",
            "Krogarna måste stänga senast klockan 23:00.",
        ),
    )


def clean_consistent_pair() -> GoldenCase:
    return _case(
        "clean_consistent_pair",
        "sufficient",
        "Får hundar vistas i stadsparken?",
        (
            "Hundar får vistas i stadsparken enligt ordningsstadgan.",
            "Stadsparken är öppen för hundar under dagtid.",
        ),
    )


def clean_single_short() -> GoldenCase:
    return _case(
        "clean_single_short",
        "sufficient",
        "Får hundar vistas i stadsparken?",
        ("Hundar får vistas i stadsparken enligt ordningsstadgan.",),
    )


def clean_scope_difference() -> GoldenCase:
    return _case(
        "clean_scope_difference",
        "sufficient",
        "Vilken stängningstid gäller för krogarna?",
        (
            "Serveringstillstånd gäller till klockan 02:00 under 2024.",
            "Reglerna ändrades till klockan 01:00 under 2025.",
        ),
    )


def candidate_miss_synonyms() -> GoldenCase:
    """No shared content tokens: candidate generation should miss this pair."""
    return _case(
        "candidate_miss_synonyms",
        "insufficient",
        "Får hundar vistas i parken?",
        (
            "Hundar får vistas i stadsparken enligt ordningsstadgan.",
            "Tamdjur tillåts i grönområdet enligt kommunen.",
        ),
    )
