"""Assemble the immutable experiment report from loop state."""

from __future__ import annotations

from typing import Any
from time import perf_counter

from app.services.research.assessment import sanitize_assessment_draft
from app.services.research.sufficiency_experiment.quality import quality_gate
from app.services.research.sufficiency_experiment.types import (
    ExperimentReport,
    GateInputs,
)


def build_experiment_report(loop: Any, *, run_id: str, events: tuple[str, ...]) -> ExperimentReport:
    draft = loop._draft or loop._fail_closed_draft()
    quality = loop._quality or quality_gate(
        loop._aggregations,
        GateInputs(span_coverage=0.0, budget_exhausted=True),
        loop._config,
    )
    return ExperimentReport(
        draft=sanitize_assessment_draft(
            draft, plan=loop._plan, evidence=loop._evidence
        ),
        status=loop._status,
        passages=tuple(loop._passages),
        evaluations=tuple(loop._evaluations),
        aggregations=loop._aggregations,
        quality=quality,
        route=loop._route,
        swe_events=events,
        swe_run_id=run_id,
        jev_calls=loop._jev_calls,
        llm_calls=loop._llm_calls,
        latency_ms=(perf_counter() - loop._started) * 1000,
        judged_chars=loop._judged_chars,
        source_chars=loop._source_chars,
        failure_mode=loop._failure,
        live_measurement=loop._live_measurement,
        claims=loop._claims,
        claim_coverage=loop._claim_coverage,
        pairs=tuple(loop._pair_evaluations),
        pair_coverage=loop._pair_coverage,
        coverage_report=loop._coverage_report,
        pair_selection=loop._pair_selection,
        stop_mode=loop._config.stop_mode,
        gap_review=loop._gap_review,
    )
