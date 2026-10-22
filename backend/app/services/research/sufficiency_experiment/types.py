"""Thin experiment records. Product contracts stay in assessment/quality."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from app.services.research.assessment import ResearchAssessmentDraft
from app.services.research.quality import EvidenceQualityDraft

if TYPE_CHECKING:
    from app.services.research.evidence_screen import EvidenceJevScores

ObligationKind = Literal["relevance", "factual_support", "completeness"]
ExperimentStatus = Literal["sufficient", "insufficient", "uncertain", "failed"]
ConflictStatus = Literal["unresolved", "resolved", "not_applicable"]
ConflictReasonKind = Literal["temporal", "entity", "definition", "superseding"]
RouteChoice = Literal["FINISH", "RUN_SUBWORKFLOW", "ESCALATE_NARRATIVE", "UNCERTAIN"]
ROUTE_CHOICES: tuple[RouteChoice, ...] = (
    "FINISH",
    "RUN_SUBWORKFLOW",
    "ESCALATE_NARRATIVE",
    "UNCERTAIN",
)

MAX_PASSAGE_CHARS = 1_500
MAX_NARRATIVE_DEPTH = 1
MAX_STEPS = 2_000
MAX_DEPTH = 6
TIMEOUT_SECONDS = 1_800


@dataclass(frozen=True)
class ExperimentConfig:
    jev_concurrency: int = 8
    jev_timeout_seconds: float = 5.0
    jev_model: str = "jev-latest"
    max_passage_chars: int = MAX_PASSAGE_CHARS
    max_narrative_depth: int = MAX_NARRATIVE_DEPTH
    max_jev_calls: int = 2_000
    max_steps: int = MAX_STEPS
    max_depth: int = MAX_DEPTH
    timeout_seconds: int = TIMEOUT_SECONDS
    support_threshold: float = 0.6
    contradict_threshold: float = 0.6
    max_tool_calls: int = 8
    max_narrative_input_chars: int = 12_000


@dataclass(frozen=True)
class EvidenceObligation:
    """Projected from ResearchNeed.source_types / capabilities. Not a product table."""

    obligation_id: str
    need_id: str
    kind: ObligationKind
    description: str
    mandatory: bool = True
    min_independent_sources: int = 1


@dataclass(frozen=True)
class EvidencePassage:
    passage_id: str
    evidence_id: str
    research_need_ids: tuple[str, ...]
    start: int
    end: int
    text: str
    content_hash: str
    source_chars: int


@dataclass(frozen=True)
class PassageEvaluation:
    job_id: str
    need_id: str
    passage_id: str
    evidence_id: str
    scores: EvidenceJevScores
    independence_key: str
    quality: EvidenceQualityDraft | None = None
    error: str | None = None
    counterpart_passage_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ObligationState:
    obligation_id: str
    kind: ObligationKind
    verified: bool
    independent_support: int
    contradicting_passage_ids: tuple[str, ...]


@dataclass(frozen=True)
class ConflictSide:
    """One identified side of a conflict. A missing side is never invented."""

    evidence_id: str
    passage_id: str | None = None
    claim_id: str | None = None
    source_id: str | None = None


@dataclass(frozen=True)
class ConflictResolution:
    """A motivated resolution. Redundancy and counts are not reasons."""

    kind: ConflictReasonKind
    rule_id: str
    evidence_ids: tuple[str, ...]
    detail: str


@dataclass(frozen=True)
class ConflictRecord:
    conflict_id: str
    need_id: str
    status: ConflictStatus
    sides: tuple[ConflictSide, ...]
    resolution: ConflictResolution | None = None
    flagged_by: str = "jev_passage_screen"

    @property
    def has_unknown_counterpart(self) -> bool:
        return len(self.sides) < 2


@dataclass(frozen=True)
class NeedAggregation:
    research_need_id: str
    status: ExperimentStatus
    sufficient: bool
    obligation_states: tuple[ObligationState, ...]
    supporting_evidence_ids: tuple[str, ...]
    contradictions: tuple[str, ...]
    unresolved_conflicts: tuple[str, ...]
    missing_or_weak: str
    unknown_requirements: bool
    conflicts: tuple[ConflictRecord, ...] = ()


@dataclass(frozen=True)
class GateInputs:
    span_coverage: float
    omitted_evidence_ids: tuple[str, ...] = ()
    missing_evaluations: tuple[str, ...] = ()
    evaluation_errors: tuple[str, ...] = ()
    budget_exhausted: bool = False
    narrative_rounds: int = 0


@dataclass(frozen=True)
class QualityDecision:
    allows_sufficient: bool
    escalate_permitted: bool
    applicable_subworkflows: tuple[str, ...]
    reasons: tuple[str, ...]
    span_coverage: float
    semantic_complete: bool
    omitted_evidence_ids: tuple[str, ...]
    missing_evaluations: tuple[str, ...]
    budget_exhausted: bool


@dataclass(frozen=True)
class RouteDecision:
    choice: RouteChoice
    rationale: str
    evidence_ids: tuple[str, ...]
    criteria: tuple[str, ...]
    subworkflow: str | None
    valid: bool
    jev_outcome: str | None = None
    rejection: str | None = None
    jev_answers: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True)
class ProvenanceEvent:
    workflow: str
    input_hash: str
    output_hash: str
    parent: str | None = None


@dataclass(frozen=True)
class ExperimentReport:
    draft: ResearchAssessmentDraft
    status: ExperimentStatus
    passages: tuple[EvidencePassage, ...]
    evaluations: tuple[PassageEvaluation, ...]
    aggregations: tuple[NeedAggregation, ...]
    quality: QualityDecision
    route: RouteDecision | None = None
    swe_events: tuple[str, ...] = ()
    swe_run_id: str = ""
    jev_calls: int = 0
    llm_calls: int = 0
    latency_ms: float = 0.0
    judged_chars: int = 0
    source_chars: int = 0
    failure_mode: str | None = None
    live_measurement: str = "not_run"

    @property
    def coverage(self) -> float:
        if self.source_chars <= 0:
            return 1.0
        return self.judged_chars / self.source_chars


def evidence_need_ids(item: object) -> tuple[str, ...]:
    need_ids = tuple(getattr(item, "research_need_ids", ()) or ())
    if need_ids:
        return need_ids
    single = getattr(item, "research_need_id", None)
    return (single,) if single else ()


def concat_source_chars(passages: Sequence[EvidencePassage]) -> int:
    return sum(item.end - item.start for item in passages)
