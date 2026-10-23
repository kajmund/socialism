"""Measure live Jev pair judgement and the share of time spent in Jev.

Pair generation is measured separately (scripts/measure_pair_recall.py). This
script sends the selected pairs through Jev, compares the verdicts with
pair-gold, and reports false contradictions on the compatible cases. Two
repetitions are made for every strategy. The optional workflow timing runs the
deterministic strategy end to end once per case.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import replace
from pathlib import Path
from time import perf_counter

from app.jev.system import HttpJevSystemOne
from app.services.knowledge.embeddings import (
    CachingEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from app.services.research.sufficiency_experiment.claims import (
    extract_claim_candidates,
)
from app.services.research.sufficiency_experiment.golden import all_golden_cases
from app.services.research.sufficiency_experiment.loop import SufficiencyLoop
from app.services.research.sufficiency_experiment.pair_eval import (
    evaluate_pairs,
    pair_coverage,
)
from app.services.research.sufficiency_experiment.pairs import select_pairs
from app.services.research.sufficiency_experiment.segment import segment_evidence
from app.services.research.sufficiency_experiment.types import (
    ExperimentConfig,
    PairEvaluation,
)

DEFAULT_GOLD = Path("tests/integration/baselines/pair-gold-v1.json")
DEFAULT_OUT = Path("tests/integration/baselines/pair-judgement-v1.json")
STRATEGIES = ("deterministic", "embeddings", "hybrid")


def _parts(case, config):
    passages = segment_evidence(case.evidence, max_chars=config.max_passage_chars)
    evidence = {item.evidence_id: item for item in case.evidence}
    claims, _ = extract_claim_candidates(passages, evidence, config=config)
    return {
        "passages": {passage.passage_id: passage for passage in passages},
        "claims": {claim.claim_id: claim for claim in claims},
        "evidence": evidence,
    }


def _facit(entry):
    candidate = {"|".join(sorted(pair)) for pair in entry["candidate_pairs"]}
    contradiction = {"|".join(sorted(pair)) for pair in entry["contradiction_pairs"]}
    return candidate, contradiction


def _metrics(entry, evaluations: list[PairEvaluation]) -> dict[str, object]:
    candidate, contradiction = _facit(entry)
    judged = [row for row in evaluations if row.status == "judged"]
    detected = {row.pair_id for row in judged if row.verdict == "CONTRADICTS"}
    false_contradictions = detected - contradiction
    true_positive = detected & contradiction
    calls = [
        row
        for row in evaluations
        if row.error not in {"pair_state_budget", "pair_call_budget"}
    ]
    coverage = pair_coverage(evaluations)
    return {
        "facit_candidate_pairs": sorted(candidate),
        "facit_contradiction_pairs": sorted(contradiction),
        "judged": len(judged),
        "uncertain": coverage.uncertain,
        "unevaluated": coverage.unevaluated,
        "unevaluated_reasons": list(coverage.reasons),
        "verdicts": {
            verdict: sum(1 for row in judged if row.verdict == verdict)
            for verdict in ("CONTRADICTS", "COMPATIBLE", "SCOPE_DIFFERENCE", "INSUFFICIENT")
        },
        "detected_contradictions": sorted(detected),
        "false_contradictions": sorted(false_contradictions),
        "recall": (
            len(true_positive) / len(contradiction) if contradiction else None
        ),
        "precision": (
            len(true_positive) / len(detected) if detected else None
        ),
        "calls": len(calls),
        "jev_latency_ms": round(sum(row.latency_ms for row in calls), 3),
        "max_state_chars": max((row.state_chars for row in evaluations), default=0),
        "models": sorted({row.model for row in calls if row.model}),
    }


async def _pair_measure(
    gold: dict,
    config: ExperimentConfig,
    reps: int,
) -> list[dict[str, object]]:
    client = HttpJevSystemOne()
    provider = CachingEmbeddingProvider(OpenAIEmbeddingProvider.from_settings())
    cases = {case.case_id: case for case in all_golden_cases()}
    output = []
    for entry in gold["cases"]:
        case = cases[entry["case_id"]]
        parts = _parts(case, config)
        rows = []
        for rep in range(reps):
            for strategy in STRATEGIES:
                started = perf_counter()
                selection = await select_pairs(
                    list(parts["claims"].values()),
                    case.plan.needs,
                    strategy=strategy,
                    config=config,
                    embedding_provider=provider if strategy != "deterministic" else None,
                )
                selection_ms = (perf_counter() - started) * 1000
                started = perf_counter()
                evaluations, coverage = await evaluate_pairs(
                    selection.selected,
                    claims=parts["claims"],
                    passages=parts["passages"],
                    evidence_by_id=parts["evidence"],
                    client=client,
                    config=config,
                )
                evaluation_ms = (perf_counter() - started) * 1000
                rows.append(
                    {
                        "rep": rep,
                        "strategy": strategy,
                        "selection_ms": round(selection_ms, 3),
                        "evaluation_ms": round(evaluation_ms, 3),
                        "total_ms": round(selection_ms + evaluation_ms, 3),
                        "selected_pairs": len(selection.selected),
                        "embedding_calls": selection.embedding_calls,
                        "embedding_texts": selection.embedding_texts,
                        "coverage": {
                            "total": coverage.total,
                            "judged": coverage.judged,
                            "uncertain": coverage.uncertain,
                            "unevaluated": coverage.unevaluated,
                            "complete": coverage.complete,
                        },
                        "metrics": _metrics(entry, evaluations),
                    }
                )
        output.append(
            {
                "case_id": entry["case_id"],
                "negative_control": entry["negative_control"],
                "runs": rows,
            }
        )
    return output


def _summary(rows: list[dict[str, object]]) -> dict[str, object]:
    summary: dict[str, object] = {}
    for strategy in STRATEGIES:
        runs = [
            run
            for case in rows
            if not case["negative_control"]
            for run in case["runs"]
            if run["strategy"] == strategy
        ]
        summary[strategy] = {
            "runs": len(runs),
            "mean_recall": _mean(run["metrics"]["recall"] for run in runs),
            "mean_precision": _mean(run["metrics"]["precision"] for run in runs),
            "false_contradictions": sum(
                len(run["metrics"]["false_contradictions"]) for run in runs
            ),
            "uncertain": sum(run["metrics"]["uncertain"] for run in runs),
            "unevaluated": sum(run["metrics"]["unevaluated"] for run in runs),
            "calls": sum(run["metrics"]["calls"] for run in runs),
            "jev_latency_ms": round(
                sum(run["metrics"]["jev_latency_ms"] for run in runs), 3
            ),
            "mean_total_ms": _mean(run["total_ms"] for run in runs),
            "embedding_calls": sum(run["embedding_calls"] for run in runs),
        }
    return summary


def _mean(values) -> float | None:
    values = [value for value in values if value is not None]
    return round(sum(values) / len(values), 4) if values else None


async def _workflow_timing(
    gold: dict,
    config: ExperimentConfig,
) -> list[dict[str, object]]:
    client = HttpJevSystemOne()
    cases = {case.case_id: case for case in all_golden_cases()}
    rows = []
    loop_config = replace(config, pair_strategy="deterministic")
    for entry in gold["cases"]:
        case = cases[entry["case_id"]]
        loop = SufficiencyLoop(case.plan, case.evidence, client=client, config=loop_config)
        await loop.run()
        report = loop.report
        if report is None:
            continue
        jev_ms = sum(row.scores.latency_ms for row in report.evaluations)
        jev_ms += sum(row.latency_ms for row in report.pairs)
        total_ms = report.latency_ms
        rows.append(
            {
                "case_id": case.case_id,
                "total_ms": round(total_ms, 3),
                "jev_latency_ms": round(jev_ms, 3),
                "orchestration_ms": round(max(total_ms - jev_ms, 0.0), 3),
                "jev_calls": report.jev_calls,
                "passage_calls": len(report.evaluations),
                "pair_calls": len(report.pairs),
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--reps", type=int, default=2)
    parser.add_argument("--workflow-timing", action="store_true")
    args = parser.parse_args()
    gold = json.loads(args.gold.read_text(encoding="utf-8"))
    config = ExperimentConfig()
    rows = asyncio.run(_pair_measure(gold, config, args.reps))
    timing = (
        asyncio.run(_workflow_timing(gold, config)) if args.workflow_timing else []
    )
    payload = {
        "measurement": "pair_judgement",
        "note": (
            "Live Jev pair verdicts; pair generation is measured separately. "
            "False contradictions are counted on all judged pairs."
        ),
        "gold": str(args.gold),
        "reps": args.reps,
        "config": {
            "jev_model": config.jev_model,
            "pair_strategy_default": config.pair_strategy,
            "max_pair_state_chars": config.max_pair_state_chars,
            "max_pairs_per_need": config.max_pairs_per_need,
        },
        "summary": _summary(rows),
        "workflow_timing": timing,
        "cases": rows,
    }
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    if timing:
        print(json.dumps(timing, ensure_ascii=False, indent=2))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
