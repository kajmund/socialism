"""Frozen golden cases for the sufficiency experiment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.services.research.assessment import AssessableEvidence
from app.services.research.models import ResearchNeed, ResearchPlan

SUPPORT_PHRASE = "Högsta domstolen tillämpar 36 § avtalslagen i NJA 2005 s. 142."
CONTRADICTION_SIGNAL = "MOTBEVIS: detta avgörande tillämpar inte 36 § avtalslagen."
LARGE_FILLER = "36 § avtalslagen " * 1_000
# Long enough that the PR #420 60k encoder must trim the excerpt.
TAIL_FILLER = "underlag. " * 8_000


@dataclass(frozen=True)
class GoldenCase:
    case_id: str
    expected: str
    signal: str
    plan: ResearchPlan
    evidence: tuple[AssessableEvidence, ...]


def all_golden_cases() -> tuple[GoldenCase, ...]:
    return (
        tail_counterevidence(),
        late_evidence(),
        large_567k(),
        short_sufficient(),
    )


def tail_counterevidence() -> GoldenCase:
    excerpt = f"{SUPPORT_PHRASE} {TAIL_FILLER} {CONTRADICTION_SIGNAL}"
    return GoldenCase(
        case_id="tail_counterevidence",
        expected="insufficient",
        signal=CONTRADICTION_SIGNAL,
        plan=_plan(),
        evidence=(_item("evidence-0", excerpt, status="found"),),
    )


def late_evidence() -> GoldenCase:
    items = [
        _item(f"evidence-{index}", f"unikt-{index} {SUPPORT_PHRASE} {LARGE_FILLER}", status="found")
        for index in range(48)
    ]
    items.append(
        _item(
            "evidence-48",
            f"unikt-48 {CONTRADICTION_SIGNAL} {LARGE_FILLER}",
            status="found",
        )
    )
    return GoldenCase(
        case_id="late_evidence",
        expected="insufficient",
        signal=CONTRADICTION_SIGNAL,
        plan=_plan(),
        evidence=tuple(items),
    )


def large_567k() -> GoldenCase:
    items: list[AssessableEvidence] = []
    for index in range(33):
        found = index < 17
        tail = f" {CONTRADICTION_SIGNAL}" if index == 0 else ""
        items.append(
            _item(
                f"evidence-{index}",
                f"unikt-{index} {LARGE_FILLER}{tail}",
                status="found" if found else "not_found",
            )
        )
    return GoldenCase(
        case_id="large_567k",
        expected="insufficient",
        signal=CONTRADICTION_SIGNAL,
        plan=_plan(),
        evidence=tuple(items),
    )


def short_sufficient() -> GoldenCase:
    return GoldenCase(
        case_id="short_sufficient",
        expected="sufficient",
        signal=SUPPORT_PHRASE,
        plan=_plan(),
        evidence=(_item("evidence-0", SUPPORT_PHRASE, status="found"),),
    )


def _plan() -> ResearchPlan:
    return ResearchPlan(
        needs=[
            ResearchNeed(
                id="research_1",
                question="Vilka avgöranden har tillämpat 36 § avtalslagen?",
                why_needed="frozen golden case",
                source_types=["case_knowledge"],
            )
        ]
    )


def _item(evidence_id: str, excerpt: str, *, status: str) -> AssessableEvidence:
    return AssessableEvidence(
        evidence_id=evidence_id,
        research_need_id="research_1",
        source_type="case_knowledge",
        status=status,
        title=evidence_id,
        excerpt=excerpt,
        locator=None,
        source_id=f"source-{evidence_id}",
        source_url=None,
        provider="golden",
        score=1.0,
        provenance={},
        retrieved_at=datetime(2026, 4, 1, tzinfo=UTC),
        content_hash=f"hash-{evidence_id}",
    )
