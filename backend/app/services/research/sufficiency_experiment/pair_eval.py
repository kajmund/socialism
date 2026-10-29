"""A3 fact-pair judgement through Jev.

Jev detects possible contradictions. A2 decides whether a detected conflict is
material and resolvable. Technical failures (timeout, invalid answer, budget)
are `unevaluated`; a judgement of `INSUFFICIENT` is `uncertain`. Both block
sufficiency when the pair is mandatory, but they are reported separately.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from time import perf_counter
from typing import Any

from app.jev.system import JevClientError, JevSystemOne
from app.services.research.assessment import AssessableEvidence
from app.services.research.sufficiency_experiment.conflicts import metadata_resolution
from app.services.research.sufficiency_experiment.types import (
    ClaimCandidate,
    ConflictRecord,
    ConflictSide,
    EvidencePassage,
    ExperimentConfig,
    NeedAggregation,
    PairCandidate,
    PairCoverage,
    PairEvaluation,
    PairVerdict,
)

PAIR_CONFLICT_QUESTIONS: dict[str, Any] = {
    "relation": {
        "type": "choice",
        "instructions": (
            "Compare the two complete claim assertions in the state. Choose "
            "CONTRADICTS only if they cannot both be true for the same entity, "
            "period and context. Choose SCOPE_DIFFERENCE if they concern "
            "different entities, periods or definitions. Choose COMPATIBLE if "
            "both can be true in the same scope. Choose INSUFFICIENT if the "
            "supplied context cannot decide the relation."
        ),
        "criteria": {
            "CONTRADICTS": "Mutually exclusive assertions for the same scope.",
            "COMPATIBLE": "Both assertions can be true in the same scope.",
            "SCOPE_DIFFERENCE": "Different entity, period or definition.",
            "INSUFFICIENT": "The supplied context cannot decide the relation.",
        },
    }
}
_VERDICTS = frozenset(PAIR_CONFLICT_QUESTIONS["relation"]["criteria"])


def build_pair_state(
    pair: PairCandidate,
    *,
    claims: Mapping[str, ClaimCandidate],
    passages: Mapping[str, EvidencePassage],
    evidence_by_id: Mapping[str, AssessableEvidence],
) -> dict[str, object]:
    return {
        "need_id": pair.need_id,
        "left": _side_state(claims[pair.left_claim_id], passages, evidence_by_id),
        "right": _side_state(claims[pair.right_claim_id], passages, evidence_by_id),
    }


def _side_state(
    claim: ClaimCandidate,
    passages: Mapping[str, EvidencePassage],
    evidence_by_id: Mapping[str, AssessableEvidence],
) -> dict[str, object]:
    passage = passages.get(claim.passage_id)
    item = evidence_by_id.get(claim.evidence_id)
    return {
        "claim_id": claim.claim_id,
        "evidence_id": claim.evidence_id,
        "source_id": claim.source_id,
        "passage_id": claim.passage_id,
        "claim": claim.text,
        "passage": passage.text if passage is not None else claim.text,
        "entity_id": claim.entity_id or (item.provenance.get("entity_id") if item else None),
        "valid_from": claim.valid_from,
        "valid_to": claim.valid_to,
        "definition_id": claim.definition_id,
    }


async def evaluate_pair(
    pair: PairCandidate,
    *,
    claims: Mapping[str, ClaimCandidate],
    passages: Mapping[str, EvidencePassage],
    evidence_by_id: Mapping[str, AssessableEvidence],
    client: JevSystemOne,
    config: ExperimentConfig,
) -> PairEvaluation:
    state = build_pair_state(
        pair, claims=claims, passages=passages, evidence_by_id=evidence_by_id
    )
    state_chars = len(json.dumps(state, ensure_ascii=False, sort_keys=True, default=str))
    if state_chars > config.max_pair_state_chars:
        return _unevaluated(pair, state_chars, "pair_state_budget")
    started = perf_counter()
    try:
        result = await client.ask(
            state=state,
            questions=PAIR_CONFLICT_QUESTIONS,
            model=config.jev_model,
            timeout_seconds=config.pair_jev_timeout_seconds,
        )
    except (JevClientError, TimeoutError, ValueError) as exc:
        return _unevaluated(pair, state_chars, _error_code(exc), started)
    verdict = _verdict(result.answers)
    if verdict is None:
        return _unevaluated(pair, state_chars, "invalid_response", started)
    status = "uncertain" if verdict == "INSUFFICIENT" else "judged"
    return PairEvaluation(
        pair_id=pair.pair_id,
        need_id=pair.need_id,
        left_claim_id=pair.left_claim_id,
        right_claim_id=pair.right_claim_id,
        verdict=verdict,
        status=status,
        sources=pair.sources,
        state_chars=state_chars,
        latency_ms=(perf_counter() - started) * 1000,
        model=result.model,
    )


async def evaluate_pairs(
    pairs: Sequence[PairCandidate],
    *,
    claims: Mapping[str, ClaimCandidate],
    passages: Mapping[str, EvidencePassage],
    evidence_by_id: Mapping[str, AssessableEvidence],
    client: JevSystemOne,
    config: ExperimentConfig,
) -> tuple[list[PairEvaluation], PairCoverage]:
    slots = asyncio.Semaphore(config.pair_jev_concurrency)
    budget = config.max_pair_jev_calls

    async def one(pair: PairCandidate) -> PairEvaluation:
        async with slots:
            if budget <= 0:
                return _unevaluated(pair, 0, "pair_call_budget")
            return await evaluate_pair(
                pair,
                claims=claims,
                passages=passages,
                evidence_by_id=evidence_by_id,
                client=client,
                config=config,
            )

    rows = await asyncio.gather(*[one(pair) for pair in pairs[:budget]])
    skipped = [
        _unevaluated(pair, 0, "pair_call_budget") for pair in pairs[budget:]
    ]
    evaluations = list(rows) + skipped
    return evaluations, pair_coverage(evaluations)


def pair_coverage(evaluations: Sequence[PairEvaluation]) -> PairCoverage:
    unevaluated = [row for row in evaluations if row.status == "unevaluated"]
    uncertain = [row for row in evaluations if row.status == "uncertain"]
    return PairCoverage(
        total=len(evaluations),
        judged=len(evaluations) - len(unevaluated) - len(uncertain),
        uncertain=len(uncertain),
        unevaluated=len(unevaluated),
        complete=not unevaluated,
        reasons=tuple(sorted({row.error for row in unevaluated if row.error})),
    )


def merge_pair_conflicts(
    aggregations: Sequence[NeedAggregation],
    evaluations: Sequence[PairEvaluation],
    *,
    claims: Mapping[str, ClaimCandidate],
    evidence_by_id: Mapping[str, AssessableEvidence],
) -> list[NeedAggregation]:
    additions: dict[str, list[ConflictRecord]] = {}
    for row in evaluations:
        record = _conflict(row, claims, evidence_by_id)
        if record is not None:
            additions.setdefault(record.need_id, []).append(record)
    return [
        _merge_one(aggregation, additions.get(aggregation.research_need_id, []))
        for aggregation in aggregations
    ]


def _conflict(
    evaluation: PairEvaluation,
    claims: Mapping[str, ClaimCandidate],
    evidence_by_id: Mapping[str, AssessableEvidence],
) -> ConflictRecord | None:
    if evaluation.status == "unevaluated":
        return None
    if evaluation.verdict == "COMPATIBLE":
        return None
    left = _claim_side(evaluation.left_claim_id, claims)
    right = _claim_side(evaluation.right_claim_id, claims)
    resolution = None
    if evaluation.verdict in {"CONTRADICTS", "SCOPE_DIFFERENCE"}:
        resolution = metadata_resolution(left, right, evidence_by_id)
    status = "unresolved" if resolution is None else _resolution_status(resolution.kind)
    return ConflictRecord(
        conflict_id=f"{evaluation.need_id}:{evaluation.pair_id}",
        need_id=evaluation.need_id,
        status=status,
        sides=(left, right),
        resolution=resolution,
        flagged_by="jev_fact_pair",
    )


def _claim_side(
    claim_id: str,
    claims: Mapping[str, ClaimCandidate],
) -> ConflictSide:
    claim = claims[claim_id]
    return ConflictSide(
        evidence_id=claim.evidence_id,
        passage_id=claim.passage_id,
        claim_id=claim.claim_id,
        source_id=claim.source_id,
    )


def _resolution_status(kind: str) -> str:
    return "resolved" if kind == "superseding" else "not_applicable"


def _merge_one(
    aggregation: NeedAggregation,
    additions: Sequence[ConflictRecord],
) -> NeedAggregation:
    if not additions:
        return aggregation
    conflicts = aggregation.conflicts + tuple(additions)
    unresolved = tuple(
        conflict.conflict_id for conflict in conflicts if conflict.status == "unresolved"
    )
    verified = all(state.verified for state in aggregation.obligation_states) and not (
        aggregation.unknown_requirements
    )
    status = _merged_status(unresolved, verified, aggregation.unknown_requirements)
    return replace(
        aggregation,
        status=status,
        sufficient=status == "sufficient",
        conflicts=conflicts,
        unresolved_conflicts=unresolved,
        missing_or_weak=(
            "Material contradictions are unresolved and not shown inapplicable."
            if unresolved
            else aggregation.missing_or_weak
        ),
    )


def _merged_status(
    unresolved: Sequence[str],
    verified: bool,
    unknown: bool,
) -> str:
    if unresolved or unknown:
        return "uncertain"
    return "sufficient" if verified else "insufficient"


def _verdict(answers: Mapping[str, Any]) -> PairVerdict | None:
    row = answers.get("relation")
    choice = row.get("choice") if isinstance(row, dict) else None
    if choice not in _VERDICTS:
        return None
    return choice  # type: ignore[return-value]


def _unevaluated(
    pair: PairCandidate,
    state_chars: int,
    error: str,
    started: float | None = None,
) -> PairEvaluation:
    latency = (perf_counter() - started) * 1000 if started is not None else 0.0
    return PairEvaluation(
        pair_id=pair.pair_id,
        need_id=pair.need_id,
        left_claim_id=pair.left_claim_id,
        right_claim_id=pair.right_claim_id,
        verdict=None,
        status="unevaluated",
        sources=pair.sources,
        state_chars=state_chars,
        latency_ms=latency,
        error=error,
    )


def _error_code(exc: BaseException) -> str:
    if isinstance(exc, JevClientError):
        return exc.category
    if isinstance(exc, TimeoutError):
        return "timeout"
    return type(exc).__name__
