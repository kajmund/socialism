"""Deterministic claim-candidate segmentation for A3.

A candidate is one exact slice of a passage, not an atomic fact. A multi-clause
sentence stays one candidate: A3's Jev comparison decides what it asserts. The
exact text and offsets are preserved; normalization only feeds search and
grouping, never the stored text.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence

from app.services.research.assessment import AssessableEvidence
from app.services.research.sufficiency_experiment.types import (
    ClaimCandidate,
    ClaimCoverage,
    ClaimExtractionStatus,
    EvidencePassage,
    ExperimentConfig,
)

METHOD = "deterministic_segment"
_SENTENCE = re.compile(r"(?<=[.!?…])\s+")
_CITATION_ONLY = re.compile(r"^[A-ZÅÄÖ][\wÅÄÖåäö .-]*\b\d{4}\s+s\.\s*\d+\.?$")
_ABBREVIATIONS = frozenset({"s", "nr", "kap", "p", "mom", "st", "jfr", "dvs"})


def extract_claim_candidates(
    passages: Sequence[EvidencePassage],
    evidence_by_id: Mapping[str, AssessableEvidence],
    *,
    config: ExperimentConfig,
) -> tuple[tuple[ClaimCandidate, ...], ClaimCoverage]:
    counts: dict[str, int] = {}
    budget_hit: set[str] = set()
    candidates: list[ClaimCandidate] = []
    per_evidence: dict[str, int] = {}
    for passage in passages:
        item = evidence_by_id.get(passage.evidence_id)
        for ordinal, span in enumerate(_spans(passage.text)):
            candidate = _candidate(
                passage,
                span,
                ordinal,
                item=item,
                config=config,
                counts=counts,
                budget_hit=budget_hit,
            )
            candidates.append(candidate)
            per_evidence[passage.evidence_id] = (
                per_evidence.get(passage.evidence_id, 0) + 1
            )
    return tuple(candidates), _coverage(candidates, per_evidence, counts, budget_hit)


def _spans(text: str) -> list[tuple[int, int]]:
    return _trimmed(text, _split(text, 0, len(text)))


def _split(text: str, start: int, end: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cursor = start
    for match in _SENTENCE.finditer(text, start, end):
        if _is_abbreviation(text, match.start()):
            continue
        spans.append((cursor, match.start()))
        cursor = match.end()
    spans.append((cursor, end))
    return spans


def _is_abbreviation(text: str, position: int) -> bool:
    prefix = text[max(0, position - 12) : position]
    token = prefix.rsplit(" ", 1)[-1].lower().rstrip(".")
    return token in _ABBREVIATIONS


def _trimmed(text: str, spans: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    output: list[tuple[int, int]] = []
    for start, end in spans:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if end > start:
            output.append((start, end))
    return output


def _candidate(
    passage: EvidencePassage,
    span: tuple[int, int],
    ordinal: int,
    *,
    item: AssessableEvidence | None,
    config: ExperimentConfig,
    counts: dict[str, int],
    budget_hit: set[str],
) -> ClaimCandidate:
    start, end = span
    text = passage.text[start:end]
    status, reason = _status(text, config)
    if status == "extracted":
        status, reason = _reserve(passage.research_need_ids, config, counts, budget_hit)
    provenance = item.provenance if item is not None else {}
    return ClaimCandidate(
        claim_id=f"{passage.passage_id}:c{ordinal}",
        evidence_id=passage.evidence_id,
        source_id=item.source_id if item is not None else None,
        passage_id=passage.passage_id,
        start=start,
        end=end,
        text=text,
        normalized_text=_normalize(text),
        canonical_key=_digest(_normalize(text)),
        research_need_ids=tuple(passage.research_need_ids),
        extraction_method=METHOD,
        extraction_status=status,
        uncertain_reason=reason,
        entity_id=_text(provenance.get("entity_id")),
        valid_from=_text(provenance.get("valid_from")),
        valid_to=_text(provenance.get("valid_to")),
        definition_id=_text(provenance.get("definition_id")),
        content_hash=_digest(text),
    )


def _status(
    text: str,
    config: ExperimentConfig,
) -> tuple[ClaimExtractionStatus, str | None]:
    if len(text) < config.min_claim_chars or len(text.split()) < config.min_claim_words:
        return "uncertain", "too_short"
    if text.rstrip().endswith("?"):
        return "uncertain", "question"
    if len(text) > config.max_claim_chars:
        return "uncertain", "too_long"
    if _CITATION_ONLY.match(text):
        return "uncertain", "citation_only"
    return "extracted", None


def _reserve(
    need_ids: Sequence[str],
    config: ExperimentConfig,
    counts: dict[str, int],
    budget_hit: set[str],
) -> tuple[ClaimExtractionStatus, str | None]:
    if not need_ids:
        return "extracted", None
    open_needs = [
        need for need in need_ids if counts.get(need, 0) < config.max_claims_per_need
    ]
    if not open_needs:
        budget_hit.update(need_ids)
        return "unprocessed", "need_claim_budget"
    for need in open_needs:
        counts[need] = counts.get(need, 0) + 1
    return "extracted", None


def _coverage(
    candidates: Sequence[ClaimCandidate],
    per_evidence: Mapping[str, int],
    counts: Mapping[str, int],
    budget_hit: Sequence[str],
) -> ClaimCoverage:
    statuses = [candidate.extraction_status for candidate in candidates]
    unprocessed = statuses.count("unprocessed")
    return ClaimCoverage(
        candidates=len(candidates),
        extracted=statuses.count("extracted"),
        uncertain=statuses.count("uncertain"),
        unprocessed=unprocessed,
        per_evidence=tuple(sorted(per_evidence.items())),
        per_need=tuple(sorted(counts.items())),
        complete=unprocessed == 0,
        reasons=tuple(f"claim_budget:{need}" for need in sorted(budget_hit)),
    )


def _normalize(text: str) -> str:
    return " ".join(text.lower().strip().split()).rstrip(".!?…")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None
