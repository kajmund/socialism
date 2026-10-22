"""Typed records for the opt-in evidence-sufficiency experiment."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from app.services.research.assessment import ResearchAssessmentDraft

PassageVerdict = Literal["SUPPORTED", "UNSUPPORTED", "CONTRADICTS", "UNDECIDED"]
PASSAGE_VERDICTS: tuple[PassageVerdict, ...] = (
    "SUPPORTED",
    "UNSUPPORTED",
    "CONTRADICTS",
    "UNDECIDED",
)

MAX_PASSAGE_CHARS = 1_500
MAX_NARRATIVE_DEPTH = 1
MAX_TOOL_CALLS = 4
MAX_NARRATIVE_INPUT_CHARS = 12_000


@dataclass(frozen=True)
class ExperimentConfig:
    jev_concurrency: int = 8
    jev_timeout_seconds: float = 5.0
    jev_model: str = "jev-latest"
    max_passage_chars: int = MAX_PASSAGE_CHARS
    max_narrative_depth: int = MAX_NARRATIVE_DEPTH
    max_tool_calls: int = MAX_TOOL_CALLS
    max_narrative_input_chars: int = MAX_NARRATIVE_INPUT_CHARS


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
class EvaluationJob:
    job_id: str
    need_id: str
    passage: EvidencePassage


@dataclass(frozen=True)
class PassageEvaluation:
    job_id: str
    need_id: str
    passage_id: str
    evidence_id: str
    verdict: PassageVerdict
    model: str
    latency_ms: float
    input_chars: int
    request_hash: str


@dataclass(frozen=True)
class NeedAggregation:
    research_need_id: str
    sufficient: bool
    supporting_evidence_ids: tuple[str, ...]
    contradictions: tuple[str, ...]
    undecided_passage_ids: tuple[str, ...]
    missing_or_weak: str
    needs_narrative: bool


@dataclass(frozen=True)
class QualityDecision:
    escalate: bool
    reasons: tuple[str, ...]
    coverage: float
    omitted_evidence_ids: tuple[str, ...]
    recursion_depth: int


@dataclass(frozen=True)
class ProvenanceEvent:
    workflow: str
    input_hash: str
    output_hash: str
    parent: str | None = None


@dataclass(frozen=True)
class ExperimentReport:
    draft: ResearchAssessmentDraft
    passages: tuple[EvidencePassage, ...]
    evaluations: tuple[PassageEvaluation, ...]
    aggregations: tuple[NeedAggregation, ...]
    quality: QualityDecision
    provenance: tuple[ProvenanceEvent, ...] = field(default_factory=tuple)
    jev_calls: int = 0
    llm_calls: int = 0
    latency_ms: float = 0.0
    judged_chars: int = 0
    source_chars: int = 0

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


def require_verdict(value: object) -> PassageVerdict:
    text = str(value or "").strip()
    if text not in PASSAGE_VERDICTS:
        raise ValueError(f"unknown passage verdict: {value!r}")
    return text  # type: ignore[return-value]


def concat_source_chars(passages: Sequence[EvidencePassage]) -> int:
    return sum(item.end - item.start for item in passages)
