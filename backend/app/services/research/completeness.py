"""Global research completeness. No panel, Word, or live retrieval.

Local sufficiency asks whether known ResearchNeeds are supported.
This reviewer asks whether the original research objective still has
material questions the plan never asked.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

from app.services.research.assessment import (
    AssessableEvidence,
    ResearchAssessmentDraft,
)
from app.services.research.followup import (
    FollowUpNeedDraft,
    RuntimeResearchNeed,
    research_question_key,
)
from app.services.research.models import (
    RESEARCH_SOURCE_TYPES,
    ResearchError,
    ResearchPlan,
    ResearchSourceType,
)
from app.services.research.planner import ResearchObjective

CompletenessResult = Literal["complete", "incomplete"]

COMPLETENESS_RESULTS: tuple[CompletenessResult, ...] = ("complete", "incomplete")
INITIAL_COMPLETENESS_PASS = 1
GLOBAL_NEED_ORIGIN = "global_completeness"

_SOURCE_TYPES: frozenset[str] = frozenset(RESEARCH_SOURCE_TYPES)


class ResearchCompletenessError(ResearchError):
    """Reviewer, model, or parsing failed. Not an incomplete outcome."""


@dataclass(frozen=True)
class MaterialMissingQuestion:
    """Candidate question. Orchestration validates before persist/retrieval."""

    question: str
    why_needed: str
    rationale: str
    source_types: list[ResearchSourceType] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_types", list(self.source_types))


@dataclass(frozen=True)
class ResearchCompletenessDraft:
    """Validated global-completeness judgment ready to persist."""

    result: CompletenessResult
    rationale: str
    missing_questions: list[MaterialMissingQuestion] = field(default_factory=list)
    considered_evidence_ids: list[str] = field(default_factory=list)
    considered_question_keys: list[str] = field(default_factory=list)
    model_provider: str | None = None
    model_name: str | None = None
    model_version: str | None = None

    def __post_init__(self) -> None:
        if self.result not in COMPLETENESS_RESULTS:
            raise ResearchCompletenessError(
                f"Unknown completeness result: {self.result}"
            )
        object.__setattr__(self, "missing_questions", list(self.missing_questions))
        object.__setattr__(
            self, "considered_evidence_ids", list(self.considered_evidence_ids)
        )
        object.__setattr__(
            self, "considered_question_keys", list(self.considered_question_keys)
        )


class ResearchCompletenessReviewer(Protocol):
    async def review(
        self,
        *,
        objective: ResearchObjective | None,
        plan: ResearchPlan,
        runtime_needs: Sequence[RuntimeResearchNeed],
        assessment: ResearchAssessmentDraft | None,
        assessments: Sequence[ResearchAssessmentDraft],
        evidence: Sequence[AssessableEvidence],
    ) -> ResearchCompletenessDraft: ...


def question_fingerprint(
    needs: Sequence[RuntimeResearchNeed],
    objective: ResearchObjective | None = None,
) -> str:
    """Stable hash of the questions and objective the reviewer saw."""
    lines = sorted(row.question_key for row in needs)
    objective_text = objective.objective.strip() if objective is not None else ""
    payload = "\n".join([*lines, f"objective:{objective_text}"])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def missing_question_to_json(row: MaterialMissingQuestion) -> dict[str, object]:
    return {
        "question": row.question,
        "why_needed": row.why_needed,
        "rationale": row.rationale,
        "source_types": list(row.source_types),
    }


def missing_question_from_json(raw: object) -> MaterialMissingQuestion:
    if not isinstance(raw, dict):
        raise ResearchCompletenessError("missing question must be a JSON object")
    source_types = raw.get("source_types") or []
    if not isinstance(source_types, list):
        raise ResearchCompletenessError("missing question source_types must be an array")
    return MaterialMissingQuestion(
        question=str(raw.get("question") or ""),
        why_needed=str(raw.get("why_needed") or ""),
        rationale=str(raw.get("rationale") or ""),
        source_types=[str(item).strip() for item in source_types if str(item).strip()],  # type: ignore[misc]
    )


def completeness_draft_from_row(row: object) -> ResearchCompletenessDraft:
    raw_questions = getattr(row, "missing_questions") or []
    if not isinstance(raw_questions, list):
        raise ResearchCompletenessError("missing_questions must be a JSON array")
    considered_ids = getattr(row, "considered_evidence_ids") or []
    considered_keys = getattr(row, "considered_question_keys") or []
    return ResearchCompletenessDraft(
        result=getattr(row, "result"),
        rationale=str(getattr(row, "rationale")),
        missing_questions=[missing_question_from_json(item) for item in raw_questions],
        considered_evidence_ids=[str(item) for item in considered_ids],
        considered_question_keys=[str(item) for item in considered_keys],
        model_provider=getattr(row, "model_provider", None),
        model_name=getattr(row, "model_name", None),
        model_version=getattr(row, "model_version", None),
    )


def _clean_source_types(values: Sequence[object]) -> list[ResearchSourceType]:
    cleaned: list[ResearchSourceType] = []
    seen: set[str] = set()
    for raw in values:
        item = str(raw).strip()
        if not item or item in seen or item not in _SOURCE_TYPES:
            continue
        seen.add(item)
        cleaned.append(item)  # type: ignore[arg-type]
    return cleaned


def sanitize_completeness_draft(
    draft: ResearchCompletenessDraft,
    *,
    runtime_needs: Sequence[RuntimeResearchNeed],
    evidence: Sequence[AssessableEvidence],
) -> ResearchCompletenessDraft:
    """Drop empty/duplicate questions. Complete drafts cannot carry candidates."""
    considered_ids = [item.evidence_id for item in evidence]
    considered_keys = [row.question_key for row in runtime_needs]
    seen_keys = set(considered_keys)
    questions: list[MaterialMissingQuestion] = []
    for raw in draft.missing_questions:
        question = raw.question.strip()
        why = raw.why_needed.strip() or raw.rationale.strip()
        rationale = raw.rationale.strip() or why
        if not question or not why:
            continue
        key = research_question_key(question)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        source_types = _clean_source_types(raw.source_types)
        questions.append(
            MaterialMissingQuestion(
                question=question,
                why_needed=why,
                rationale=rationale,
                source_types=source_types,
            )
        )
    result = draft.result
    if result == "complete":
        questions = []
    return ResearchCompletenessDraft(
        result=result,
        rationale=draft.rationale.strip() or "Completeness reviewer returned no rationale.",
        missing_questions=questions,
        considered_evidence_ids=considered_ids,
        considered_question_keys=considered_keys,
        model_provider=draft.model_provider,
        model_name=draft.model_name,
        model_version=draft.model_version,
    )


def programmatic_completeness(
    *,
    objective: ResearchObjective | None,
    runtime_needs: Sequence[RuntimeResearchNeed],
    evidence: Sequence[AssessableEvidence],
    model_provider: str = "programmatic",
    model_name: str | None = None,
    model_version: str | None = None,
) -> ResearchCompletenessDraft:
    """Deterministic reviewer used when an LLM call would add no information."""
    if objective is None:
        rationale = (
            "No persisted research objective; the validated ResearchPlan is "
            "the full research scope."
        )
    else:
        rationale = (
            "Programmatic reviewer does not invent missing questions beyond "
            "the known ResearchNeeds."
        )
    return ResearchCompletenessDraft(
        result="complete",
        rationale=rationale,
        missing_questions=[],
        considered_evidence_ids=[item.evidence_id for item in evidence],
        considered_question_keys=[row.question_key for row in runtime_needs],
        model_provider=model_provider,
        model_name=model_name,
        model_version=model_version,
    )


def can_review_programmatically(objective: ResearchObjective | None) -> bool:
    """True when there is no objective beyond the already-validated plan."""
    return objective is None


def missing_questions_to_follow_up_drafts(
    questions: Sequence[MaterialMissingQuestion],
) -> list[FollowUpNeedDraft]:
    return [
        FollowUpNeedDraft(
            question=row.question,
            why_needed=row.why_needed,
            source_types=list(row.source_types),
            source_gap=row.rationale or row.why_needed,
        )
        for row in questions
    ]


class ProgrammaticResearchCompletenessReviewer:
    """No LLM. Vacuous complete when the Attempt has no research objective."""

    async def review(
        self,
        *,
        objective: ResearchObjective | None,
        plan: ResearchPlan,
        runtime_needs: Sequence[RuntimeResearchNeed],
        assessment: ResearchAssessmentDraft | None,
        assessments: Sequence[ResearchAssessmentDraft],
        evidence: Sequence[AssessableEvidence],
    ) -> ResearchCompletenessDraft:
        return programmatic_completeness(
            objective=objective,
            runtime_needs=runtime_needs,
            evidence=evidence,
        )


def next_completeness_pass(existing_count: int) -> int:
    return existing_count + 1
