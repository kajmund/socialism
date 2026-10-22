"""Full per-passage trace of one sufficiency run.

The benchmark artifact keeps only metrics. Metrics cannot show where a
contradiction was lost, so this trace keeps the evidence chain behind a verdict:
which passages were judged, what Jev scored them, which obligations verified,
which gate reasons fired, and which route was chosen.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict

from app.services.research.sufficiency_experiment.golden import GoldenCase
from app.services.research.sufficiency_experiment.route import route_state
from app.services.research.sufficiency_experiment.types import (
    ExperimentConfig,
    ExperimentReport,
    PassageEvaluation,
)


def case_trace(
    case: GoldenCase,
    report: ExperimentReport,
    config: ExperimentConfig,
) -> dict[str, object]:
    texts = {passage.passage_id: passage.text for passage in report.passages}
    rows = [
        _evaluation(row, texts.get(row.passage_id, ""), case.signal, config)
        for row in report.evaluations
    ]
    signal_rows = [row for row in rows if row["signal_present"]]
    return {
        "case_id": case.case_id,
        "expected": case.expected,
        "expected_status": case.expected_status,
        "signal": case.signal,
        "config": _config(config),
        "verdict": _verdict(report),
        "signal_passages": signal_rows,
        "contradiction_passages": [
            row["passage_id"] for row in rows if row["contradiction_flagged"]
        ],
        "evaluations": rows,
        "aggregations": [asdict(item) for item in report.aggregations],
        "quality": asdict(report.quality),
        "route_state": route_state(report.aggregations, report.quality),
        "route": _route(report),
        "claim_coverage": (
            asdict(report.claim_coverage) if report.claim_coverage else None
        ),
        "claims_extracted": [
            asdict(item)
            for item in report.claims
            if item.extraction_status == "extracted"
        ],
        "draft": asdict(report.draft),
    }


def _route(report: ExperimentReport) -> dict[str, object] | None:
    if report.route is None:
        return None
    row = asdict(report.route)
    row["jev_answers"] = dict(report.route.jev_answers)
    return row


def _evaluation(
    row: PassageEvaluation,
    text: str,
    signal: str,
    config: ExperimentConfig,
) -> dict[str, object]:
    scores = row.scores
    carries_signal = bool(signal) and signal in text
    return {
        "job_id": row.job_id,
        "need_id": row.need_id,
        "passage_id": row.passage_id,
        "evidence_id": row.evidence_id,
        "chars": len(text),
        "error": row.error,
        "signal_present": carries_signal,
        "counterpart_passage_ids": list(row.counterpart_passage_ids),
        "text": text if carries_signal else "",
        "relevant_to_question": scores.relevant_to_question,
        "directly_supports_answer": scores.directly_supports_answer,
        "contradicts_current_evidence": scores.contradicts_current_evidence,
        "material_new_information": scores.material_new_information,
        "likely_duplicate_or_redundant": scores.likely_duplicate_or_redundant,
        "primary_or_high_authority_for_question": (
            scores.primary_or_high_authority_for_question
        ),
        "support_flagged": scores.directly_supports_answer >= config.support_threshold,
        "contradiction_flagged": (
            scores.contradicts_current_evidence >= config.contradict_threshold
        ),
        "relevance_flagged": scores.relevant_to_question >= config.support_threshold,
    }


def _config(config: ExperimentConfig) -> dict[str, object]:
    return {
        "jev_model": config.jev_model,
        "support_threshold": config.support_threshold,
        "contradict_threshold": config.contradict_threshold,
        "max_passage_chars": config.max_passage_chars,
        "max_jev_calls": config.max_jev_calls,
        "max_narrative_depth": config.max_narrative_depth,
        "max_narrative_input_chars": config.max_narrative_input_chars,
    }


def _verdict(report: ExperimentReport) -> dict[str, object]:
    return {
        "result": report.draft.result,
        "status": report.status,
        "failure_mode": report.failure_mode,
        "coverage": report.coverage,
        "source_chars": report.source_chars,
        "judged_chars": report.judged_chars,
        "jev_calls": report.jev_calls,
        "llm_calls": report.llm_calls,
        "latency_ms": report.latency_ms,
        "passage_count": len(report.passages),
        "evaluation_count": len(report.evaluations),
        "evaluation_errors": _errors(report.evaluations),
    }


def _errors(rows: Sequence[PassageEvaluation]) -> list[str]:
    return [row.job_id for row in rows if row.error]
