"""B3c: full live A (current order) vs B (metadata order).

Two repetitions each, A3 contract unchanged. Measures decision quality,
false-sufficient, coverage, Jev calls/latency, false conflicts, duplicate Jev
verdict stability and information value per Jev call. No production change.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path

from app.jev.system import HttpJevSystemOne
from app.services.research.sufficiency_experiment.gap_cases import (
    candidate_miss_synonyms,
)
from app.services.research.sufficiency_experiment.golden import (
    conflict_benchmark_cases,
    scripted_benchmark_cases,
    tail_claim_contradiction,
)
from app.services.research.sufficiency_experiment.assessor import run_experiment
from app.services.research.sufficiency_experiment.types import ExperimentConfig

DEFAULT_OUT = Path("tests/integration/baselines/b3c-live-arms-v1.json")
GOLD = Path("tests/integration/baselines/pair-gold-v1.json")
CASES = tuple(scripted_benchmark_cases()) + tuple(conflict_benchmark_cases()) + (
    tail_claim_contradiction(),
    candidate_miss_synonyms(),
)
CONFIG = {
    "A": replace(
        ExperimentConfig(),
        route_authority=True,
        legacy_duplicate_resolution=False,
        pair_judgement=True,
        pair_strategy="deterministic",
        pair_ordering="current",
    ),
    "B": replace(
        ExperimentConfig(),
        route_authority=True,
        legacy_duplicate_resolution=False,
        pair_judgement=True,
        pair_strategy="deterministic",
        pair_ordering="metadata",
    ),
}
COMPATIBLE = {"compatible_periods", "compatible_entities", "unknown_counterpart"}


def _key(left: str, right: str) -> frozenset[str]:
    return frozenset((left, right))


def _gold_facit() -> dict[str, dict[str, set[frozenset[str]]]]:
    entries = json.loads(GOLD.read_text(encoding="utf-8"))["cases"]
    out = {}
    for entry in entries:
        out[entry["case_id"]] = {
            "contradiction": {_key(*pair) for pair in entry["contradiction_pairs"]},
            "compatible": {_key(*pair) for pair in entry["candidate_pairs"]}
            if not entry["contradiction_pairs"]
            else set(),
        }
    return out


def _marker_facit(case, report) -> dict[str, set[frozenset[str]]]:
    claims = list(report.claims)
    contradiction = next((claim for claim in claims if "MOTBEVIS" in claim.text), None)
    support = next(
        (claim for claim in claims if "Högsta domstolen tillämpar" in claim.text),
        None,
    )
    if case.case_id == "late_evidence" and contradiction and support:
        return {"contradiction": {_key(support.claim_id, contradiction.claim_id)}, "compatible": set()}
    if case.case_id == "candidate_miss_synonyms":
        left = next((claim for claim in claims if "Hundar" in claim.text), None)
        right = next((claim for claim in claims if "Tamdjur" in claim.text), None)
        if left and right:
            return {"contradiction": {_key(left.claim_id, right.claim_id)}, "compatible": set()}
    return {"contradiction": set(), "compatible": set()}


def _info_value(report, facit, seen: set[str]) -> Counter:
    counts: Counter[str] = Counter()
    for evaluation in report.pairs:
        pair_key = _key(evaluation.left_claim_id, evaluation.right_claim_id)
        if evaluation.pair_id in seen:
            counts["repeated_known_relation"] += 1
            continue
        seen.add(evaluation.pair_id)
        verdict = evaluation.verdict
        if pair_key in facit["contradiction"]:
            if verdict == "CONTRADICTS":
                counts["new_relevant_contradiction"] += 1
            else:
                counts["wrong_semantic_verdict"] += 1
        elif pair_key in facit["compatible"]:
            if verdict == "CONTRADICTS":
                counts["wrong_semantic_verdict"] += 1
            else:
                counts["new_verified_compatibility"] += 1
        elif verdict == "CONTRADICTS":
            counts["new_relevant_contradiction"] += 1
        elif verdict in {"COMPATIBLE", "SCOPE_DIFFERENCE"}:
            counts["new_verified_compatibility"] += 1
        elif evaluation.status != "judged" or evaluation.error:
            counts["unevaluated_or_failed"] += 1
        else:
            counts["low_value_other"] += 1
    return counts


async def _run_arm(arm: str, reps: int) -> dict:
    client = HttpJevSystemOne()
    config = CONFIG[arm]
    gold = _gold_facit()
    rows = []
    pair_verdicts: dict[str, list[str]] = {}
    info = Counter()
    seen: set[str] = set()
    for rep in range(reps):
        for case in CASES:
            report = await run_experiment(
                case.plan,
                case.evidence,
                client=client,
                config=config,
                counterparts=case.counterparts,
            )
            facit = {"contradiction": set(), "compatible": set()}
            if case.case_id in gold:
                facit = gold[case.case_id]
            facit = {
                "contradiction": facit["contradiction"] | _marker_facit(case, report)["contradiction"],
                "compatible": facit["compatible"] | _marker_facit(case, report)["compatible"],
            }
            counts = _info_value(report, facit, seen)
            info.update(counts)
            conflicts = [
                conflict for row in report.aggregations for conflict in row.conflicts
            ]
            unresolved = [c for c in conflicts if c.status == "unresolved"]
            false_conflicts = len(
                [c for c in conflicts if c.status == "unresolved" and c.flagged_by == "jev_fact_pair" and case.case_id in COMPATIBLE]
            )
            for evaluation in report.pairs:
                if case.case_id == "duplicate_contradiction":
                    verdicts = pair_verdicts.setdefault(arm, [])
                    verdicts.append(str(evaluation.verdict))
            rows.append(
                {
                    "arm": arm,
                    "rep": rep,
                    "case_id": case.case_id,
                    "draft": report.draft.result,
                    "expected": case.expected,
                    "status": report.status,
                    "correct": report.draft.result == case.expected,
                    "false_sufficient": report.draft.result == "sufficient" and case.expected == "insufficient",
                    "false_insufficient": report.draft.result == "insufficient" and case.expected == "sufficient",
                    "coverage_complete": bool(
                        report.coverage_report and report.coverage_report.gate_complete
                    ),
                    "unresolved_conflicts": len(unresolved),
                    "false_conflicts": false_conflicts,
                    "jev_calls": report.jev_calls,
                    "latency_ms": report.latency_ms,
                    "info_value": dict(counts),
                }
            )
    totals = {
        "correct": sum(row["correct"] for row in rows),
        "false_sufficient": sum(row["false_sufficient"] for row in rows),
        "false_insufficient": sum(row["false_insufficient"] for row in rows),
        "coverage_complete": sum(row["coverage_complete"] for row in rows),
        "false_conflicts": sum(row["false_conflicts"] for row in rows),
        "jev_calls": sum(row["jev_calls"] for row in rows),
        "latency_ms": round(sum(row["latency_ms"] for row in rows), 1),
        "info_value": dict(info),
        "useful_info_calls": info["new_relevant_contradiction"] + info["new_verified_compatibility"],
        "wrong_semantic_verdicts": info["wrong_semantic_verdict"],
    }
    return {
        "config": asdict(config),
        "rows": rows,
        "totals": totals,
        "duplicate_pair_verdicts": pair_verdicts.get(arm, []),
    }


async def _run(out: Path, reps: int) -> dict:
    arms = {}
    for arm in ("A", "B"):
        arms[arm] = await _run_arm(arm, reps)
        print(arm, arms[arm]["totals"], flush=True)
    a, b = arms["A"]["totals"], arms["B"]["totals"]
    criteria = {
        "decision_correct_at_least_A": b["correct"] >= a["correct"],
        "false_sufficient_not_higher": b["false_sufficient"] <= a["false_sufficient"],
        "coverage_not_worse": b["coverage_complete"] >= a["coverage_complete"],
        "jev_calls_not_higher": b["jev_calls"] <= a["jev_calls"],
    }
    adopt = all(criteria.values())
    payload = {
        "measurement": "b3c_live_arms",
        "note": "A current pair order vs B metadata order; A3 contract and 40-pair budget unchanged.",
        "reps": reps,
        "case_set": [case.case_id for case in CASES],
        "arms": arms,
        "criteria": criteria,
        "decision": "ACCEPT_B3_B" if adopt else "KEEP_CURRENT_ORDER",
        "informational_value": {
            arm: arms[arm]["totals"]["info_value"] for arm in arms
        },
        "late_evidence": {
            arm: [
                {"rep": row["rep"], "draft": row["draft"]}
                for row in arms[arm]["rows"]
                if row["case_id"] == "late_evidence"
            ]
            for arm in arms
        },
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"criteria": criteria, "decision": payload["decision"]}, indent=2))
    print(f"wrote {out}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--reps", type=int, default=2)
    args = parser.parse_args()
    asyncio.run(_run(args.out, args.reps))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
