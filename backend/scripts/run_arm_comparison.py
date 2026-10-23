"""Run the pre-registered A0/A2/A3/A1 comparison.

A0 is recorded first; A1 replays its calls from the cassette (fully paired),
A2/A3 replay matching calls and run new calls live. A second independent live
repetition per arm measures operational stability. No production change.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from dataclasses import asdict, replace
from pathlib import Path

from app.jev.system import HttpJevSystemOne, JevSystemOneResult, JevUsage
from app.services.research.sufficiency_experiment.arm_quality import (
    CaseOutcome,
    cost_metrics,
    operational_metrics,
    semantic_metrics,
)
from app.services.research.sufficiency_experiment.assessor import run_experiment
from app.services.research.sufficiency_experiment.cassette import (
    RecordingJev,
    entry_key,
)
from app.services.research.sufficiency_experiment.golden import (
    conflict_benchmark_cases,
    scripted_benchmark_cases,
    tail_claim_contradiction,
)
from app.services.research.sufficiency_experiment.types import ExperimentConfig

ROOT = Path(__file__).resolve().parents[1] / "tests" / "integration" / "baselines"
CASES = tuple(scripted_benchmark_cases()) + tuple(conflict_benchmark_cases()) + (
    tail_claim_contradiction(),
)
TRAPS = {
    "tail_counterevidence",
    "late_evidence",
    "large_567k",
    "duplicate_contradiction",
    "independent_contradiction",
}
COMPATIBLE = {"compatible_periods", "compatible_entities"}
ARMS = ("A0", "A2", "A3", "A1")
ARM_CONFIG = {
    "A0": replace(
        ExperimentConfig(),
        route_authority=False,
        legacy_duplicate_resolution=True,
        pair_judgement=False,
    ),
    "A1": replace(
        ExperimentConfig(),
        route_authority=True,
        legacy_duplicate_resolution=True,
        pair_judgement=False,
    ),
    "A2": replace(
        ExperimentConfig(),
        route_authority=True,
        legacy_duplicate_resolution=False,
        pair_judgement=False,
    ),
    "A3": replace(
        ExperimentConfig(),
        route_authority=True,
        legacy_duplicate_resolution=False,
        pair_judgement=True,
        pair_strategy="deterministic",
    ),
}


class PairingJev:
    """Serve recorded answers by content key; new calls run live and are counted."""

    def __init__(self, entries: list[dict], inner) -> None:
        self._by_key: dict[str, list[dict]] = defaultdict(list)
        for entry in entries:
            self._by_key[str(entry["key"])].append(entry)
        self._inner = inner
        self.matched = 0
        self.live = 0

    async def ask(self, *, state, questions, model, timeout_seconds):
        key = entry_key(questions=questions, state=state, model=model)
        queue = self._by_key.get(key)
        if queue:
            self.matched += 1
            return _result_from_entry(queue.pop(0))
        self.live += 1
        return await self._inner.ask(
            state=state,
            questions=questions,
            model=model,
            timeout_seconds=timeout_seconds,
        )


def _result_from_entry(entry: dict) -> JevSystemOneResult:
    usage = entry.get("usage") or {}
    return JevSystemOneResult(
        answers=dict(entry["answers"]),
        model=str(entry["model"]),
        latency_ms=float(entry["latency_ms"]),
        input_chars=int(entry["input_chars"]),
        usage=JevUsage(
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
        ),
        raw={},
    )


def _conflicts(report):
    return [conflict for row in report.aggregations for conflict in row.conflicts]


def _technical(report) -> bool:
    if any(row.error for row in report.evaluations):
        return True
    if report.pair_coverage and report.pair_coverage.unevaluated:
        return True
    return report.failure_mode is not None and report.failure_mode != "narrative_unbound"


def _verdict_reasons(arm: str, report) -> list[str]:
    unresolved = [c for c in _conflicts(report) if c.status == "unresolved"]
    route = report.route
    reasons: list[str] = []
    if _technical(report):
        reasons.append("technical_failure")
    if unresolved:
        reasons.append("contradiction_detected")
    if report.coverage_report and not report.coverage_report.gate_complete:
        reasons.append("coverage_incomplete")
    if (
        arm == "A1"
        and route is not None
        and route.final_outcome in {"uncertain", "insufficient"}
        and report.quality.allows_sufficient
        and report.draft.result != "sufficient"
    ):
        reasons.append("route_authority")
    if report.draft.result == "sufficient":
        reasons.append("sufficient_verified")
    elif not reasons and report.quality.reasons:
        reasons.extend(f"gate_{row}" for row in report.quality.reasons[:2])
    return reasons or ["unknown"]


def _case_row(arm, rep, case, report, *, matched, live) -> dict[str, object]:
    conflicts = _conflicts(report)
    unresolved = [c for c in conflicts if c.status == "unresolved"]
    pair_conflicts = [c for c in unresolved if c.flagged_by == "jev_fact_pair"]
    technical = _technical(report)
    reasons = _verdict_reasons(arm, report)
    return {
        "case_id": case.case_id,
        "expected": case.expected,
        "arm": arm,
        "rep": rep,
        "draft": report.draft.result,
        "status": report.status,
        "verdict_reasons": reasons,
        "primary_reason": reasons[0],
        "contradiction_detected": bool(unresolved),
        "route_choice": report.route.choice if report.route else None,
        "route_final_outcome": (
            report.route.final_outcome if report.route else None
        ),
        "route_valid": report.route.valid if report.route else None,
        "gate_allows_sufficient": report.quality.allows_sufficient,
        "quality_reasons": list(report.quality.reasons),
        "unresolved_conflicts": [c.conflict_id for c in unresolved],
        "pair_conflicts": [c.conflict_id for c in pair_conflicts],
        "technical_failure": technical,
        "failure_reasons": (
            [row.job_id for row in report.evaluations if row.error]
            or (list(report.pair_coverage.reasons) if report.pair_coverage else [])
            or ([report.failure_mode] if report.failure_mode else [])
        ),
        "coverage_gate_complete": bool(
            report.coverage_report and report.coverage_report.gate_complete
        ),
        "jev_calls": report.jev_calls,
        "matched_calls": matched,
        "live_calls": live,
        "input_chars": report.judged_chars,
        "pair_calls": len(report.pairs),
        "latency_ms": report.latency_ms,
        "jev_latency_ms": sum(e.scores.latency_ms for e in report.evaluations)
        + sum(p.latency_ms for p in report.pairs),
    }


def _outcome(row) -> CaseOutcome:
    case_id = str(row["case_id"])
    return CaseOutcome(
        case_id=case_id,
        repetition=int(row["rep"]),
        expected=str(row["expected"]),
        draft=str(row["draft"]),
        technical_failure=bool(row["technical_failure"]),
        failure_reasons=tuple(row["failure_reasons"] or ()),
        coverage_gate_complete=bool(row["coverage_gate_complete"]),
        true_positive_conflict=case_id in TRAPS
        and bool(row["unresolved_conflicts"]),
        false_contradiction=case_id in COMPATIBLE
        and bool(row["unresolved_conflicts"]),
        jev_calls=int(row["jev_calls"]),
        input_chars=int(row["input_chars"]),
        latency_ms=float(row["latency_ms"]),
        jev_latency_ms=float(row["jev_latency_ms"]),
    )


async def _run(arm: str, rep: int, *, cassette=None, record=False):
    config = ARM_CONFIG[arm]
    inner = HttpJevSystemOne()
    pairing = PairingJev(cassette, inner) if cassette is not None else None
    recorder = RecordingJev(pairing or inner) if record else None
    client = recorder or pairing or inner
    rows = []
    for case in CASES:
        before_matched = pairing.matched if pairing else 0
        before_live = pairing.live if pairing else 0
        report = await run_experiment(
            case.plan,
            case.evidence,
            client=client,
            config=config,
            counterparts=case.counterparts,
        )
        matched = pairing.matched - before_matched if pairing else 0
        live = (
            pairing.live - before_live
            if pairing
            else (report.jev_calls if recorder else 0)
        )
        rows.append(_case_row(arm, rep, case, report, matched=matched, live=live))
    entries = recorder.entries if recorder else None
    return rows, entries or []


def _pairing_info(rows) -> dict[str, int]:
    return {
        "matched": sum(int(row["matched_calls"]) for row in rows),
        "live": sum(int(row["live_calls"]) for row in rows),
    }


def _pass_fail(all_rows: dict[str, list[dict]]) -> dict[str, object]:
    checks = {}
    a1 = [r for r in all_rows["A1"]]
    checks["a1_route_uncertain_never_sufficient"] = all(
        not (r["draft"] == "sufficient" and r["route_final_outcome"] != "sufficient")
        for r in a1
    )
    a3 = [r for r in all_rows["A3"] if r["coverage_gate_complete"] and not r["technical_failure"]]
    checks["a3_traps_not_sufficient"] = all(
        r["draft"] != "sufficient" for r in a3 if r["case_id"] in TRAPS
    )
    checks["a3_short_sufficient"] = all(
        r["draft"] == "sufficient"
        for r in a3
        if r["case_id"] == "short_sufficient"
    )
    checks["a3_compatible_clean"] = all(
        not r["unresolved_conflicts"] for r in a3 if r["case_id"] in COMPATIBLE
    )
    checks["no_silent_success_on_failure"] = all(
        not (r["technical_failure"] and r["draft"] == "sufficient")
        for rows in all_rows.values()
        for r in rows
    )
    checks["a3_budget_unchanged"] = ARM_CONFIG["A3"].max_pairs_per_need == 40
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "arm-comparison-v1.json")
    parser.add_argument("--cassette", type=Path, default=ROOT / "jev-cassette-a0-2026-10-23.json")
    parser.add_argument("--reps", type=int, default=2)
    args = parser.parse_args()
    all_rows: dict[str, list[dict]] = {}
    pairing: dict[str, object] = {}
    cassette_entries: list[dict] = []
    for arm in ARMS:
        all_rows[arm] = []
        for rep in range(args.reps):
            use_cassette = rep == 0 and arm != "A0"
            rows, entries = asyncio.run(
                _run(
                    arm,
                    rep,
                    cassette=cassette_entries if use_cassette else None,
                    record=(arm == "A0" and rep == 0),
                )
            )
            if arm == "A0" and rep == 0:
                cassette_entries = entries
            if use_cassette:
                pairing[arm] = _pairing_info(rows)
            all_rows[arm].extend(rows)
            print(arm, "rep", rep, "done", flush=True)
    args.cassette.write_text(
        json.dumps(
            {"version": 1, "source_arm": "A0", "entries": cassette_entries},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    outcomes = {
        arm: [_outcome(row) for row in rows] for arm, rows in all_rows.items()
    }
    summary = {}
    for arm in ARMS:
        summary[arm] = {
            "semantic": semantic_metrics(outcomes[arm]),
            "operational": operational_metrics(outcomes[arm]),
            "cost": cost_metrics(outcomes[arm]),
            "pairing": pairing.get(arm),
            "reproducibility_error": bool(
                pairing.get(arm, {}).get("live", 0) and arm == "A1"
            ),
        }
    payload = {
        "measurement": "arm_comparison",
        "protocol": "measurement-protocol-v1.json",
        "locked_at": "2026-10-23",
        "arms": list(ARMS),
        "reps": args.reps,
        "case_set": [case.case_id for case in CASES],
        "arm_config": {arm: asdict(config) for arm, config in ARM_CONFIG.items()},
        "cassette": str(args.cassette),
        "runs": all_rows,
        "summary": summary,
        "pass_fail": _pass_fail(all_rows),
    }
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload["pass_fail"], ensure_ascii=False, indent=2))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
