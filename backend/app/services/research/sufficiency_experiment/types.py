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
ClaimExtractionStatus = Literal["extracted", "uncertain", "unprocessed"]
PairStrategy = Literal["deterministic", "embeddings", "hybrid"]
PairVerdict = Literal["CONTRADICTS", "COMPATIBLE", "SCOPE_DIFFERENCE", "INSUFFICIENT"]
PairEvaluationStatus = Literal["judged", "uncertain", "unevaluated"]
CoverageStatus = Literal["complete", "incomplete", "not_measured", "not_applicable"]
DecisionReason = Literal[
    "CONTRADICTION_FOUND",
    "COVERAGE_INCOMPLETE",
    "SUPPORT_INCOMPLETE",
    "TECHNICAL_FAILURE",
    "SUFFICIENT",
]
GapVerdict = Literal["VERIFIED_GAP", "SUSPECTED_GAP", "NO_GAP_FOUND", "UNDETERMINED"]
CoverageControl = Literal[
    "provided_evidenceset",
    "character_cover",
    "candidate_status",
    "process",
    "process_and_facit",
    "none",
]
ConflictReasonKind = Literal["temporal", "entity", "definition", "superseding"]
RouteChoice = Literal["FINISH", "RUN_SUBWORKFLOW", "ESCALATE_NARRATIVE", "UNCERTAIN"]
RouteOutcome = Literal["sufficient", "insufficient", "uncertain"]
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
    min_claim_chars: int = 20
    max_claim_chars: int = 500
    min_claim_words: int = 4
    max_claims_per_need: int = 200
    max_pairs_per_need: int = 40
    embedding_neighbors: int = 3
    pair_strategy: PairStrategy = "deterministic"
    pair_ordering: str = "current"
    route_authority: bool = True
    legacy_duplicate_resolution: bool = False
    pair_judgement: bool = True
    pair_jev_concurrency: int = 8
    pair_jev_timeout_seconds: float = 5.0
    gap_review_enabled: bool = False
    max_gap_input_chars: int = 12_000
    max_pair_state_chars: int = 6_000
    max_pair_jev_calls: int = 200


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
class ClaimCandidate:
    """One occurrence of candidate claim text. Not a verified fact."""

    claim_id: str
    evidence_id: str
    source_id: str | None
    passage_id: str
    start: int
    end: int
    text: str
    normalized_text: str
    canonical_key: str
    research_need_ids: tuple[str, ...]
    extraction_method: str
    extraction_status: ClaimExtractionStatus
    uncertain_reason: str | None = None
    entity_id: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    definition_id: str | None = None
    content_hash: str = ""


@dataclass(frozen=True)
class PairCandidate:
    pair_id: str
    need_id: str
    left_claim_id: str
    right_claim_id: str
    score: float
    sources: tuple[str, ...]
    features: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True)
class PairSelection:
    strategy: PairStrategy
    candidates: tuple[PairCandidate, ...]
    selected: tuple[PairCandidate, ...]
    budget: int
    omitted_by_budget: int
    input_claims: int
    latency_ms: float
    embedding_calls: int = 0
    embedding_texts: int = 0
    embedding_ms: float = 0.0
    prioritization_ms: float = 0.0


@dataclass(frozen=True)
class PairEvaluation:
    pair_id: str
    need_id: str
    left_claim_id: str
    right_claim_id: str
    verdict: PairVerdict | None
    status: PairEvaluationStatus
    sources: tuple[str, ...]
    state_chars: int
    latency_ms: float
    error: str | None = None
    model: str | None = None


@dataclass(frozen=True)
class PairFacit:
    candidate_pairs: tuple[str, ...] = ()
    contradiction_pairs: tuple[str, ...] = ()


@dataclass(frozen=True)
class CoverageLevel:
    level: str
    status: CoverageStatus
    control: CoverageControl
    counts: tuple[tuple[str, int], ...] = ()
    reasons: tuple[str, ...] = ()
    note: str = ""
    gate_complete: bool = True


@dataclass(frozen=True)
class CoverageReport:
    levels: tuple[CoverageLevel, ...]

    @property
    def gate_complete(self) -> bool:
        return all(level.gate_complete for level in self.levels)

    def level(self, name: str) -> CoverageLevel | None:
        return next((level for level in self.levels if level.level == name), None)


@dataclass(frozen=True)
class GapHypothesis:
    gap_id: str
    need_id: str
    missing: str
    observations: tuple[str, ...]
    suggested_workflow: str
    anchors: tuple[str, ...] = ()


@dataclass(frozen=True)
class NarrativeGapReport:
    needs_more_evidence: bool
    missing_evidence: tuple[str, ...]
    questions: tuple[str, ...]
    suggested_workflows: tuple[str, ...]
    cited_claim_ids: tuple[str, ...]
    rationale: str
    latency_ms: float = 0.0
    input_chars: int = 0
    model: str | None = None
    error: str | None = None
    verdict: GapVerdict | None = None
    gaps: tuple[GapHypothesis, ...] = ()
    validation_error: str | None = None


@dataclass(frozen=True)
class PairCoverage:
    total: int
    judged: int
    uncertain: int
    unevaluated: int
    complete: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ClaimCoverage:
    candidates: int
    extracted: int
    uncertain: int
    unprocessed: int
    per_evidence: tuple[tuple[str, int], ...]
    per_need: tuple[tuple[str, int], ...]
    complete: bool
    reasons: tuple[str, ...]


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
    claim_coverage_incomplete: bool = False
    pair_coverage_incomplete: bool = False
    coverage_incomplete: bool = False


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
    final_outcome: RouteOutcome | None = None


@dataclass(frozen=True)
class ProvenanceEvent:
    workflow: str
    input_hash: str
    output_hash: str
    parent: str | None = None


@dataclass(frozen=True)
class StopShadow:
    condition: str
    would_stop: bool
    conflict_id: str | None
    pair_verdict: str | None
    remaining_pair_calls: int
    estimated_calls_saved: int
    estimated_latency_saved_ms: float
    coverage_complete: bool
    blocking: bool
    risk: str | None


@dataclass(frozen=True)
class DecisionDiagnostics:
    reasons: tuple[DecisionReason, ...]
    unique_conflicts: tuple[str, ...] = ()


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
    claims: tuple[ClaimCandidate, ...] = ()
    claim_coverage: ClaimCoverage | None = None
    pairs: tuple[PairEvaluation, ...] = ()
    pair_coverage: PairCoverage | None = None
    coverage_report: CoverageReport | None = None
    pair_selection: PairSelection | None = None
    gap_review: NarrativeGapReport | None = None

    @property
    def coverage(self) -> float:
        if self.source_chars <= 0:
            return 1.0
        return self.judged_chars / self.source_chars

    @property
    def stop_shadow(self) -> StopShadow:
        from app.services.research.sufficiency_experiment.stop_conditions import (
            shadow_stop,
        )

        return shadow_stop(
            pairs=self.pairs,
            aggregations=self.aggregations,
            coverage=self.coverage_report,
        )

    @property
    def decision_diagnostics(self) -> DecisionDiagnostics:
        from app.services.research.sufficiency_experiment.diagnostics import (
            decision_diagnostics_from_report,
        )

        return decision_diagnostics_from_report(self)


def evidence_need_ids(item: object) -> tuple[str, ...]:
    need_ids = tuple(getattr(item, "research_need_ids", ()) or ())
    if need_ids:
        return need_ids
    single = getattr(item, "research_need_id", None)
    return (single,) if single else ()


def concat_source_chars(passages: Sequence[EvidencePassage]) -> int:
    return sum(item.end - item.start for item in passages)
