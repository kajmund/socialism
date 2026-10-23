"""Versioned golden-facit schema and deterministic QA checks.

Facit is independent evidence about the test, never a copy of the production
Jev judgement. A valid sufficient case must have evidence that lexically or
explicitly relates to the plan question; off-topic evidence cannot be used to
demand a sufficient verdict.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

FacitStatus = Literal["valid", "invalid", "diagnostic"]
ExpectedRelation = Literal[
    "contradiction",
    "compatible_scope",
    "compatible_entity",
    "supportive",
    "unresolved_unknown",
]

_STOPWORDS = frozenset(
    {
        "och", "i", "att", "det", "som", "en", "ett", "på", "är", "av", "för",
        "med", "den", "till", "inte", "om", "har", "de", "kan", "vid", "samt",
        "eller", "så", "ska", "från", "var", "vara", "detta", "denna", "dessa",
        "sig", "sin", "sitt", "sina", "under", "över", "mellan", "mot", "utan",
        "vilka", "vilken", "vilket", "gäller", "finns", "minst", "har",
    }
)


@dataclass(frozen=True)
class FacitEvidence:
    evidence_id: str
    excerpt: str
    status: str
    source_type: str = "case_knowledge"
    provenance: dict[str, object] = field(default_factory=dict)
    expected_relevance: bool = True


@dataclass(frozen=True)
class FacitRelation:
    evidence_ids: tuple[str, ...]
    relation: ExpectedRelation


@dataclass(frozen=True)
class FacitReview:
    method: str
    reviewed_by: str
    independent_review_required: bool = False
    notes: str = ""


@dataclass(frozen=True)
class FacitCase:
    case_id: str
    version: str
    status: FacitStatus
    plan_question: str
    expected_decision: str
    evidence: tuple[FacitEvidence, ...]
    relations: tuple[FacitRelation, ...]
    rationale: str
    review: FacitReview
    invalidation_reason: str = ""


@dataclass(frozen=True)
class FacitValidation:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


def load_facit(path: Path) -> tuple[FacitCase, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return tuple(
        FacitCase(
            case_id=row["case_id"],
            version=row["version"],
            status=row["status"],
            plan_question=row["plan_question"],
            expected_decision=row["expected_decision"],
            evidence=tuple(FacitEvidence(**item) for item in row["evidence"]),
            relations=tuple(
                FacitRelation(
                    evidence_ids=tuple(item["evidence_ids"]),
                    relation=item["relation"],
                )
                for item in row["relations"]
            ),
            rationale=row["rationale"],
            review=FacitReview(**row["review"]),
            invalidation_reason=row.get("invalidation_reason", ""),
        )
        for row in payload["cases"]
    )


def dump_facit(cases: Sequence[FacitCase], path: Path, *, version: str) -> None:
    path.write_text(
        json.dumps(
            {
                "version": version,
                "cases": [asdict(case) for case in cases],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def validate_facit(
    cases: Sequence[FacitCase], *, policy: str = "v2"
) -> FacitValidation:
    errors: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for case in cases:
        if case.case_id in seen:
            errors.append(f"duplicate case: {case.case_id}")
        seen.add(case.case_id)
        _validate_case(case, errors, warnings, policy=policy)
    return FacitValidation(tuple(errors), tuple(warnings))


def _validate_case(
    case: FacitCase, errors: list[str], warnings: list[str], *, policy: str
) -> None:
    if case.status == "invalid" and not case.invalidation_reason:
        errors.append(f"invalid case lacks reason: {case.case_id}")
    if "jev" in case.review.method.lower():
        errors.append(f"facit must not reuse Jev as review: {case.case_id}")
    if not case.rationale.strip():
        errors.append(f"missing rationale: {case.case_id}")
    evidence_ids = {item.evidence_id for item in case.evidence}
    for relation in case.relations:
        unknown = set(relation.evidence_ids) - evidence_ids
        if unknown:
            errors.append(
                f"relation cites unknown evidence: {case.case_id} {sorted(unknown)}"
            )
    if case.expected_decision == "sufficient" and case.status == "valid":
        _validate_sufficient(case, errors, warnings, policy=policy)
    if case.review.independent_review_required:
        warnings.append(f"independent review pending: {case.case_id}")
    if case.status == "diagnostic":
        warnings.append(f"diagnostic case excluded from accuracy: {case.case_id}")


def _validate_sufficient(
    case: FacitCase,
    errors: list[str],
    warnings: list[str],
    *,
    policy: str,
) -> None:
    relevant = [item for item in case.evidence if item.expected_relevance]
    if not relevant:
        errors.append(f"sufficient case has no relevant evidence: {case.case_id}")
    elif not any(
        lexical_related(case.plan_question, item.excerpt) for item in relevant
    ):
        if policy == "v2":
            errors.append(f"sufficient case evidence is off-topic: {case.case_id}")
        elif all(item.provenance for item in relevant) and any(
            relation.relation in {"supportive", "compatible_scope", "compatible_entity"}
            for relation in case.relations
        ):
            warnings.append(
                f"low lexical relation, independent review required: {case.case_id}"
            )
        else:
            errors.append(
                f"sufficient case evidence is off-topic and unverified: {case.case_id}"
            )
    if not any(
        relation.relation in {"supportive", "compatible_scope", "compatible_entity"}
        for relation in case.relations
    ):
        errors.append(f"sufficient case lacks supportive relation: {case.case_id}")


def lexical_related(question: str, excerpt: str) -> bool:
    return bool(_terms(question) & _terms(excerpt))


def _terms(text: str) -> set[str]:
    words = re.findall(r"[a-zåäö0-9]+", text.lower())
    return {
        _stem(word)
        for word in words
        if word not in _STOPWORDS and len(word) > 2
    }


def _stem(word: str) -> str:
    for suffix in ("ningen", "ingar", "ningar", "ande", "arna", "erna", "ens", "ets", "en", "et", "ar", "er", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word
