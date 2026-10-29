"""Pair-evaluation step with the optional existential stop check."""

from __future__ import annotations

from typing import Any

from app.services.research.sufficiency_experiment.pair_eval import evaluate_pair
from app.services.research.sufficiency_experiment.types import (
    PairCandidate,
    PairEvaluation,
)


async def evaluate_pair_step(loop: Any, pair: PairCandidate) -> dict[str, Any]:
    existential = loop._config.stop_mode == "existential"
    if existential and loop._stop_requested:
        loop._pair_calls_skipped += 1
        row = PairEvaluation(
            pair_id=pair.pair_id,
            need_id=pair.need_id,
            left_claim_id=pair.left_claim_id,
            right_claim_id=pair.right_claim_id,
            verdict=None,
            status="unevaluated",
            sources=("stop_condition",),
            state_chars=0,
            latency_ms=0.0,
            error="stop_condition_met",
        )
        loop._pair_evaluations.append(row)
        return {"pair_id": row.pair_id, "status": row.status, "verdict": None}
    loop._pair_calls_started += 1
    if existential:
        loop._pair_in_flight += 1
    row = await evaluate_pair(
        pair,
        claims=loop._claims_by_id,
        passages=loop._passages_by_id,
        evidence_by_id=loop._evidence_by_id(),
        client=loop._client,
        config=loop._config,
    )
    if existential:
        loop._pair_in_flight -= 1
    if row.error not in {"pair_state_budget", "pair_call_budget"}:
        loop._jev_calls += 1
    loop._pair_evaluations.append(row)
    if (
        existential
        and not loop._stop_requested
        and row.verdict == "CONTRADICTS"
        and _relevance_verified(loop)
    ):
        loop._stop_requested = True
        loop._stop_conflict_id = row.pair_id
        loop._pair_in_flight_at_stop = loop._pair_in_flight
    return {"pair_id": row.pair_id, "status": row.status, "verdict": row.verdict}


def _relevance_verified(loop: Any) -> bool:
    return any(
        state.kind == "relevance" and state.verified
        for row in loop._aggregations
        for state in row.obligation_states
    )
