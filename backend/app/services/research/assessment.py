"""Evidence sufficiency assessment. No panel, Word, or live retrieval.

The assessor judges whether persisted EvidenceSet items answer the
validated ResearchPlan. It does not write the expert report.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from app.services.legal_research_result import LegalResearchResult
from app.services.research.models import ResearchError, ResearchPlan
from app.services.research.quality import EvidenceQualityDraft

AssessmentResult = Literal["sufficient", "insufficient"]

ASSESSMENT_RESULTS: tuple[AssessmentResult, ...] = ("sufficient", "insufficient")
INITIAL_ASSESSMENT_PASS = 1
# Review models judge support, not the frozen document. Stored excerpts stay intact.
REVIEW_EXCERPT_CHARS = 2000


def review_excerpt(excerpt: str | None, *, max_chars: int = REVIEW_EXCERPT_CHARS) -> str | None:
    if excerpt is None or len(excerpt) <= max_chars:
        return excerpt
    return excerpt[:max_chars]


class ResearchAssessmentError(ResearchError):
    """Assessor, model, or parsing failed. Not an insufficient outcome."""


@dataclass(frozen=True)
class AssessableEvidence:
    """Persisted EvidenceSet item as the assessor is allowed to see it."""

    evidence_id: str
    research_need_id: str | None
    source_type: str
    status: str
    title: str | None
    excerpt: str | None
    locator: str | None
    source_id: str | None
    source_url: str | None
    provider: str | None
    score: float | None
    provenance: dict[str, object]
    retrieved_at: datetime
    content_hash: str
    quality: EvidenceQualityDraft | None = None
    research_need_ids: tuple[str, ...] = ()
    legal_result: LegalResearchResult | None = None
    claims: tuple[dict[str, object], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "provenance", dict(self.provenance))
        object.__setattr__(self, "research_need_ids", tuple(self.research_need_ids))
        object.__setattr__(self, "claims", tuple(self.claims))


@dataclass(frozen=True)
class EvidenceReviewGroup:
    """One review payload row with all runtime needs that retrieved the source."""

    evidence: AssessableEvidence
    research_need_ids: tuple[str, ...]
    duplicate_evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ResearchNeedAssessment:
    research_need_id: str
    sufficient: bool
    supporting_evidence_ids: list[str] = field(default_factory=list)
    missing_or_weak: str = ""
    contradictions: list[str] = field(default_factory=list)
    further_information: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "supporting_evidence_ids", list(self.supporting_evidence_ids))
        object.__setattr__(self, "contradictions", list(self.contradictions))


@dataclass(frozen=True)
class ResearchAssessmentDraft:
    """Validated assessment ready to persist. Does not mutate evidence."""

    result: AssessmentResult
    rationale: str
    need_assessments: list[ResearchNeedAssessment] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    considered_evidence_ids: list[str] = field(default_factory=list)
    model_provider: str | None = None
    model_name: str | None = None
    model_version: str | None = None

    def __post_init__(self) -> None:
        if self.result not in ASSESSMENT_RESULTS:
            raise ResearchAssessmentError(f"Unknown assessment result: {self.result}")
        object.__setattr__(self, "need_assessments", list(self.need_assessments))
        object.__setattr__(self, "gaps", list(self.gaps))
        object.__setattr__(self, "contradictions", list(self.contradictions))
        object.__setattr__(self, "considered_evidence_ids", list(self.considered_evidence_ids))


class ResearchAssessor(Protocol):
    async def assess(
        self,
        plan: ResearchPlan,
        evidence: Sequence[AssessableEvidence],
    ) -> ResearchAssessmentDraft: ...


def evidence_id_set(evidence: Sequence[AssessableEvidence]) -> frozenset[str]:
    return frozenset(item.evidence_id for item in evidence)


def group_evidence_for_review(
    evidence: Sequence[AssessableEvidence],
) -> list[EvidenceReviewGroup]:
    """Collapse exact source duplicates without losing need lineage."""
    grouped: dict[str, list[AssessableEvidence]] = {}
    for item in evidence:
        source = (item.source_id or item.source_url or "").strip()
        need_ids = item.research_need_ids or (
            (item.research_need_id,) if item.research_need_id else ()
        )
        identity = source or f"content:{item.content_hash}"
        key = f"{identity}:{','.join(sorted(need_ids))}:{item.status}:{item.content_hash}"
        grouped.setdefault(key, []).append(item)
    result: list[EvidenceReviewGroup] = []
    for items in grouped.values():
        primary = items[0]
        need_ids = tuple(
            dict.fromkeys(
                need_id
                for item in items
                for need_id in (
                    item.research_need_ids
                    or ((item.research_need_id,) if item.research_need_id else ())
                )
            )
        )
        result.append(
            EvidenceReviewGroup(
                evidence=primary,
                research_need_ids=need_ids,
                duplicate_evidence_ids=tuple(item.evidence_id for item in items[1:]),
            )
        )
    return result


def evidence_fingerprint(evidence: Sequence[AssessableEvidence]) -> str:
    """Stable hash of the exact EvidenceSet version the assessor saw."""
    payload = "\n".join(
        f"{item.evidence_id}\t{item.content_hash}"
        for item in sorted(evidence, key=lambda row: (row.evidence_id, row.content_hash))
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def need_assessment_to_json(row: ResearchNeedAssessment) -> dict[str, object]:
    return {
        "research_need_id": row.research_need_id,
        "sufficient": row.sufficient,
        "supporting_evidence_ids": list(row.supporting_evidence_ids),
        "missing_or_weak": row.missing_or_weak,
        "contradictions": list(row.contradictions),
        "further_information": row.further_information,
    }


def assessment_draft_from_row(row: object) -> ResearchAssessmentDraft:
    """Rebuild a draft from a persisted ResearchAssessment row."""
    result = getattr(row, "result")
    rationale = getattr(row, "rationale")
    need_raw = getattr(row, "need_assessments") or []
    gaps = getattr(row, "gaps") or []
    contradictions = getattr(row, "contradictions") or []
    considered = getattr(row, "considered_evidence_ids") or []
    if not isinstance(need_raw, list):
        raise ResearchAssessmentError("need_assessments must be a JSON array")
    return ResearchAssessmentDraft(
        result=result,
        rationale=str(rationale),
        need_assessments=[need_assessment_from_json(item) for item in need_raw],
        gaps=[str(item) for item in gaps],
        contradictions=[str(item) for item in contradictions],
        considered_evidence_ids=[str(item) for item in considered],
        model_provider=getattr(row, "model_provider", None),
        model_name=getattr(row, "model_name", None),
        model_version=getattr(row, "model_version", None),
    )


def need_assessment_from_json(raw: object) -> ResearchNeedAssessment:
    if not isinstance(raw, dict):
        raise ResearchAssessmentError("need assessment must be a JSON object")
    supporting = raw.get("supporting_evidence_ids") or []
    contradictions = raw.get("contradictions") or []
    if not isinstance(supporting, list) or not isinstance(contradictions, list):
        raise ResearchAssessmentError("need assessment lists must be arrays")
    further = raw.get("further_information")
    if further is not None:
        further = str(further)
    return ResearchNeedAssessment(
        research_need_id=str(raw.get("research_need_id") or ""),
        sufficient=bool(raw.get("sufficient")),
        supporting_evidence_ids=[str(value) for value in supporting],
        missing_or_weak=str(raw.get("missing_or_weak") or ""),
        contradictions=[str(value) for value in contradictions],
        further_information=further,
    )


def _keep_known_ids(values: Sequence[str], allowed: frozenset[str]) -> list[str]:
    seen: set[str] = set()
    kept: list[str] = []
    for raw in values:
        item = str(raw).strip()
        if not item or item not in allowed or item in seen:
            continue
        seen.add(item)
        kept.append(item)
    return kept


def _found_ids_for_need(need_id: str, evidence: Sequence[AssessableEvidence]) -> list[str]:
    return [
        item.evidence_id
        for item in evidence
        if need_id in (item.research_need_ids or (item.research_need_id,))
        and item.status == "found"
        and (item.legal_result is None or item.legal_result.relation.relation != "irrelevant")
    ]


def programmatic_assessment(
    plan: ResearchPlan,
    evidence: Sequence[AssessableEvidence],
    *,
    model_provider: str = "programmatic",
    model_name: str | None = None,
    model_version: str | None = None,
) -> ResearchAssessmentDraft:
    """Deterministic assessment used when an LLM call would add no information."""
    considered = [item.evidence_id for item in evidence]
    if not plan.needs:
        return ResearchAssessmentDraft(
            result="sufficient",
            rationale="ResearchPlan has no needs; evidence sufficiency is vacuous.",
            need_assessments=[],
            gaps=[],
            contradictions=[],
            considered_evidence_ids=considered,
            model_provider=model_provider,
            model_name=model_name,
            model_version=model_version,
        )

    need_rows: list[ResearchNeedAssessment] = []
    gaps: list[str] = []
    for need in plan.needs:
        supporting = _found_ids_for_need(need.id, evidence)
        if supporting:
            need_rows.append(
                ResearchNeedAssessment(
                    research_need_id=need.id,
                    sufficient=True,
                    supporting_evidence_ids=supporting,
                )
            )
            continue
        missing = "No found evidence persisted for this ResearchNeed."
        gaps.append(f"{need.id}: {missing}")
        need_rows.append(
            ResearchNeedAssessment(
                research_need_id=need.id,
                sufficient=False,
                missing_or_weak=missing,
                further_information=need.question,
            )
        )
    result: AssessmentResult = (
        "sufficient" if all(row.sufficient for row in need_rows) else "insufficient"
    )
    if result == "sufficient":
        rationale = "Every ResearchNeed has at least one persisted found item."
    elif not evidence:
        rationale = "ResearchPlan has needs but the EvidenceSet has no persisted items."
    else:
        rationale = "One or more ResearchNeeds lack persisted found evidence."
    return ResearchAssessmentDraft(
        result=result,
        rationale=rationale,
        need_assessments=need_rows,
        gaps=gaps,
        contradictions=[],
        considered_evidence_ids=considered,
        model_provider=model_provider,
        model_name=model_name,
        model_version=model_version,
    )


def can_assess_programmatically(plan: ResearchPlan, evidence: Sequence[AssessableEvidence]) -> bool:
    """True when the outcome is determined without a model call."""
    if not plan.needs:
        return True
    return not any(item.status == "found" for item in evidence)


def sanitize_assessment_draft(
    draft: ResearchAssessmentDraft,
    *,
    plan: ResearchPlan,
    evidence: Sequence[AssessableEvidence],
) -> ResearchAssessmentDraft:
    """Drop invented evidence/need IDs. Fail closed on unsupported sufficient."""
    allowed = evidence_id_set(evidence)
    plan_ids = [need.id for need in plan.needs]
    plan_id_set = set(plan_ids)
    incoming = {
        row.research_need_id: row
        for row in draft.need_assessments
        if row.research_need_id in plan_id_set
    }
    aligned: list[ResearchNeedAssessment] = []
    for need in plan.needs:
        row = incoming.get(need.id)
        if row is None:
            aligned.append(
                ResearchNeedAssessment(
                    research_need_id=need.id,
                    sufficient=False,
                    missing_or_weak="Assessor omitted this ResearchNeed.",
                    further_information=need.question,
                )
            )
            continue
        need_found = frozenset(_found_ids_for_need(need.id, evidence))
        supporting = _keep_known_ids(row.supporting_evidence_ids, need_found)
        sufficient = row.sufficient
        missing = row.missing_or_weak
        further = row.further_information
        if sufficient and not supporting:
            sufficient = False
            missing = missing or (
                "Sufficient assessments must cite persisted EvidenceSet IDs."
                if not row.supporting_evidence_ids
                else "Supporting evidence IDs were not in the supplied EvidenceSet."
            )
            if not further:
                further = need.question
        aligned.append(
            ResearchNeedAssessment(
                research_need_id=need.id,
                sufficient=sufficient,
                supporting_evidence_ids=supporting,
                missing_or_weak=missing,
                contradictions=[
                    str(item).strip() for item in row.contradictions if str(item).strip()
                ],
                further_information=further,
            )
        )
    result = draft.result
    if any(not row.sufficient for row in aligned):
        result = "insufficient"
    gaps = [str(item).strip() for item in draft.gaps if str(item).strip()]
    for row in aligned:
        if row.sufficient:
            continue
        marker = f"{row.research_need_id}:"
        if not any(item.startswith(marker) for item in gaps) and row.missing_or_weak:
            gaps.append(f"{row.research_need_id}: {row.missing_or_weak}")
    return ResearchAssessmentDraft(
        result=result,
        rationale=draft.rationale.strip() or "Assessor returned no rationale.",
        need_assessments=aligned,
        gaps=gaps,
        contradictions=[str(item).strip() for item in draft.contradictions if str(item).strip()],
        considered_evidence_ids=list(allowed),
        model_provider=draft.model_provider,
        model_name=draft.model_name,
        model_version=draft.model_version,
    )


class ProgrammaticResearchAssessor:
    """No LLM. Empty plans are sufficient; missing found evidence is not."""

    async def assess(
        self,
        plan: ResearchPlan,
        evidence: Sequence[AssessableEvidence],
    ) -> ResearchAssessmentDraft:
        return programmatic_assessment(plan, evidence)
