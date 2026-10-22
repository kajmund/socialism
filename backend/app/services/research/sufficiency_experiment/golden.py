"""Frozen golden cases for the sufficiency experiment."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.services.research.assessment import AssessableEvidence
from app.services.research.models import ResearchNeed, ResearchPlan

SUPPORT_PHRASE = "Högsta domstolen tillämpar 36 § avtalslagen i NJA 2005 s. 142."
CONTRADICTION_SIGNAL = "MOTBEVIS: detta avgörande tillämpar inte 36 § avtalslagen."
IRRELEVANT = "Vädret i Göteborg var mulet hela veckan."
LARGE_FILLER = "36 § avtalslagen " * 1_000
# Long enough that the PR #420 60k encoder must trim the excerpt.
TAIL_FILLER = "underlag. " * 8_000


@dataclass(frozen=True)
class GoldenCase:
    case_id: str
    expected: str
    expected_status: str
    signal: str
    plan: ResearchPlan
    evidence: tuple[AssessableEvidence, ...]
    counterparts: dict[str, tuple[str, ...]] = field(default_factory=dict)


def all_golden_cases() -> tuple[GoldenCase, ...]:
    return (
        short_sufficient(),
        no_support(),
        tail_counterevidence(),
        late_evidence(),
        large_567k(),
        multi_obligation(),
        missing_source_type(),
        unknown_requirements(),
        duplicate_sources(),
        later_wave_contradiction(),
        adversarial_empty(),
        duplicate_contradiction(),
        independent_contradiction(),
        compatible_periods(),
        compatible_entities(),
        unknown_counterpart(),
        pair_over_budget(),
    )


def scripted_benchmark_cases() -> tuple[GoldenCase, ...]:
    """PR #420 trap set plus a positive control. Scripted only."""
    return (
        tail_counterevidence(),
        late_evidence(),
        large_567k(),
        short_sufficient(),
    )


def conflict_benchmark_cases() -> tuple[GoldenCase, ...]:
    """A2/A3 conflict cases. `pair_over_budget` is A3-only, so it is excluded."""
    return (
        duplicate_contradiction(),
        independent_contradiction(),
        compatible_periods(),
        compatible_entities(),
        unknown_counterpart(),
    )


def tail_counterevidence() -> GoldenCase:
    excerpt = f"{SUPPORT_PHRASE} {TAIL_FILLER} {CONTRADICTION_SIGNAL}"
    return GoldenCase(
        case_id="tail_counterevidence",
        expected="insufficient",
        expected_status="uncertain",
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
        expected_status="uncertain",
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
        expected_status="uncertain",
        signal=CONTRADICTION_SIGNAL,
        plan=_plan(),
        evidence=tuple(items),
    )


def short_sufficient() -> GoldenCase:
    return GoldenCase(
        case_id="short_sufficient",
        expected="sufficient",
        expected_status="sufficient",
        signal=SUPPORT_PHRASE,
        plan=_plan(),
        evidence=(_item("evidence-0", SUPPORT_PHRASE, status="found"),),
    )


def no_support() -> GoldenCase:
    return GoldenCase(
        case_id="no_support",
        expected="insufficient",
        expected_status="insufficient",
        signal=IRRELEVANT,
        plan=_plan(),
        evidence=(_item("evidence-0", IRRELEVANT, status="found"),),
    )


def multi_obligation() -> GoldenCase:
    plan = ResearchPlan(
        needs=[
            ResearchNeed(
                id="research_1",
                question="Vilka avgöranden har tillämpat 36 § avtalslagen?",
                why_needed="multi-obligation golden case",
                source_types=["case_knowledge", "swedish_law"],
            )
        ]
    )
    return GoldenCase(
        case_id="multi_obligation",
        expected="insufficient",
        expected_status="insufficient",
        signal=SUPPORT_PHRASE,
        plan=plan,
        evidence=(_item("evidence-0", SUPPORT_PHRASE, status="found"),),
    )


def missing_source_type() -> GoldenCase:
    plan = ResearchPlan(
        needs=[
            ResearchNeed(
                id="research_1",
                question="Vilka avgöranden har tillämpat 36 § avtalslagen?",
                why_needed="missing source type",
                source_types=["swedish_law"],
            )
        ]
    )
    return GoldenCase(
        case_id="missing_source_type",
        expected="insufficient",
        expected_status="insufficient",
        signal=SUPPORT_PHRASE,
        plan=plan,
        evidence=(_item("evidence-0", SUPPORT_PHRASE, status="found"),),
    )


def unknown_requirements() -> GoldenCase:
    plan = ResearchPlan(
        needs=[
            ResearchNeed(
                id="research_1",
                question="Vilka avgöranden har tillämpat 36 § avtalslagen?",
                why_needed="unknown obligations",
                source_types=[],
            )
        ]
    )
    return GoldenCase(
        case_id="unknown_requirements",
        expected="insufficient",
        expected_status="uncertain",
        signal=SUPPORT_PHRASE,
        plan=plan,
        evidence=(_item("evidence-0", SUPPORT_PHRASE, status="found"),),
    )


def duplicate_sources() -> GoldenCase:
    plan = ResearchPlan(
        needs=[
            ResearchNeed(
                id="research_1",
                question="Vilka avgöranden har tillämpat 36 § avtalslagen?",
                why_needed="independence",
                source_types=["case_knowledge"],
                capabilities=["corroboration"],
            )
        ]
    )
    copies = tuple(
        _item(
            f"evidence-{index}",
            SUPPORT_PHRASE,
            status="found",
            source_id="source-shared",
        )
        for index in range(5)
    )
    return GoldenCase(
        case_id="duplicate_sources",
        expected="insufficient",
        expected_status="insufficient",
        signal=SUPPORT_PHRASE,
        plan=plan,
        evidence=copies,
    )


def later_wave_contradiction() -> GoldenCase:
    first = _item("evidence-0", SUPPORT_PHRASE, status="found")
    later = _item(
        "evidence-1",
        CONTRADICTION_SIGNAL,
        status="found",
        provenance={"wave": 2},
    )
    return GoldenCase(
        case_id="later_wave_contradiction",
        expected="insufficient",
        expected_status="uncertain",
        signal=CONTRADICTION_SIGNAL,
        plan=_plan(),
        evidence=(first, later),
    )


def adversarial_empty() -> GoldenCase:
    return GoldenCase(
        case_id="adversarial_empty",
        expected="insufficient",
        expected_status="insufficient",
        signal="",
        plan=_plan(),
        evidence=(_item("evidence-0", "", status="found"),),
    )


def duplicate_contradiction() -> GoldenCase:
    evidence = (
        _item("dup-support", SUPPORT_PHRASE, status="found"),
        _item(
            "dup-contra",
            f"{CONTRADICTION_SIGNAL} Avgörandet gäller ett annat avtal.",
            status="found",
        ),
    )
    return GoldenCase(
        case_id="duplicate_contradiction",
        expected="insufficient",
        expected_status="uncertain",
        signal=CONTRADICTION_SIGNAL,
        plan=_plan(),
        evidence=evidence,
    )


def independent_contradiction() -> GoldenCase:
    evidence = (
        _item("ind-support", SUPPORT_PHRASE, status="found"),
        _item(
            "ind-contra",
            f"{CONTRADICTION_SIGNAL} Avgörandet gäller samma avtal.",
            status="found",
        ),
    )
    return GoldenCase(
        case_id="independent_contradiction",
        expected="insufficient",
        expected_status="uncertain",
        signal=CONTRADICTION_SIGNAL,
        plan=_plan(),
        evidence=evidence,
    )


def compatible_periods() -> GoldenCase:
    evidence = (
        _item(
            "period-old",
            "Uppsägningstiden är tre månader för avtalet.",
            status="found",
            provenance={
                "valid_from": "2024-01-01",
                "valid_to": "2024-12-31",
                "entity_id": "avtal-period",
            },
        ),
        _item(
            "period-new",
            "Uppsägningstiden är sex månader för avtalet.",
            status="found",
            provenance={
                "valid_from": "2026-01-01",
                "valid_to": "2026-12-31",
                "entity_id": "avtal-period",
            },
        ),
    )
    return GoldenCase(
        case_id="compatible_periods",
        expected="sufficient",
        expected_status="sufficient",
        signal="",
        plan=_plan(),
        evidence=evidence,
        counterparts={"period-new:p0": ("period-old:p0",)},
    )


def compatible_entities() -> GoldenCase:
    evidence = (
        _item(
            "entity-a",
            "Avtal A har tre månaders uppsägningstid.",
            status="found",
            provenance={"entity_id": "avtal-a"},
        ),
        _item(
            "entity-b",
            "Avtal B har sex månaders uppsägningstid.",
            status="found",
            provenance={"entity_id": "avtal-b"},
        ),
    )
    return GoldenCase(
        case_id="compatible_entities",
        expected="sufficient",
        expected_status="sufficient",
        signal="",
        plan=_plan(),
        evidence=evidence,
        counterparts={"entity-b:p0": ("entity-a:p0",)},
    )


def unknown_counterpart() -> GoldenCase:
    return GoldenCase(
        case_id="unknown_counterpart",
        expected="insufficient",
        expected_status="uncertain",
        signal=CONTRADICTION_SIGNAL,
        plan=_plan(),
        evidence=(
            _item(
                "unknown-contra",
                f"{CONTRADICTION_SIGNAL} Ingen motpart är identifierad.",
                status="found",
            ),
        ),
    )


def pair_over_budget() -> GoldenCase:
    """A3-only: a required pair that does not fit the pair context budget."""
    filler = "underlag. " * 400
    return GoldenCase(
        case_id="pair_over_budget",
        expected="insufficient",
        expected_status="uncertain",
        signal=CONTRADICTION_SIGNAL,
        plan=_plan(),
        evidence=(
            _item("budget-left", f"{SUPPORT_PHRASE} {filler}", status="found"),
            _item(
                "budget-right",
                f"{CONTRADICTION_SIGNAL} {filler}",
                status="found",
            ),
        ),
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


def _item(
    evidence_id: str,
    excerpt: str,
    *,
    status: str,
    source_id: str | None = None,
    provenance: dict[str, object] | None = None,
) -> AssessableEvidence:
    return AssessableEvidence(
        evidence_id=evidence_id,
        research_need_id="research_1",
        source_type="case_knowledge",
        status=status,
        title=evidence_id,
        excerpt=excerpt,
        locator=None,
        source_id=source_id or f"source-{evidence_id}",
        source_url=None,
        provider="golden",
        score=1.0,
        provenance=provenance or {},
        retrieved_at=datetime(2026, 4, 1, tzinfo=UTC),
        content_hash=f"hash-{evidence_id}",
    )
