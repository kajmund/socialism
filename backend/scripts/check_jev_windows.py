"""Replay bounded passage ranking and independent contradiction controls."""

import argparse
import asyncio
import json
import sys
from pathlib import Path


async def run(args: argparse.Namespace) -> None:
    from tests.research_reuse.live import workload  # noqa: F401
    from app.config import settings
    from app.services.research.assessment import group_evidence_for_review
    from app.services.research.fast_controller import research_jev_model
    from app.services.research.reuse_gate import assessable_candidates
    from tests.research_reuse.jev_window_controls import snapshots
    from tests.research_reuse.jev_diagnostics import DiagnosticJev
    from tests.research_reuse.jev_window_live import pair_control, variant
    from tests.research_reuse.snapshots import EVIDENCE, digest

    if not settings.typesafe_api_key.strip():
        raise ValueError("Configured Jev credentials are required")
    source = json.loads(Path(args.input).read_text())
    cases = snapshots() if args.controls_only else [{"name": "frozen-evidence", **source}]
    report = {"status": "incomplete", "cases": [], "snapshot_sha256": digest(source)}
    client = DiagnosticJev()
    try:
        for snapshot in cases:
            groups = group_evidence_for_review(assessable_candidates(EVIDENCE.validate_python(snapshot["evidence"])))
            items = [g.evidence for g in groups]
            case = {"name": snapshot["name"], "question": snapshot["need"]["question"],
                "model": research_jev_model(),
                "concurrency": settings.research_jev_concurrency if args.concurrency is None else args.concurrency,
                "timeout_seconds": settings.research_jev_timeout_seconds,
                "state_budget": settings.research_jev_max_state_chars, "runs": [],
                "input_count": len(snapshot["evidence"]), "review_count": len(items),
                "duplicate_bindings": {g.evidence.evidence_id: list(g.duplicate_evidence_ids)
                    for g in groups if g.duplicate_evidence_ids},
                "snapshot_sha256": digest(snapshot)}
            report["cases"].append(case)
            if args.controls_only:
                case["snapshot"] = snapshot
            for iteration in range(args.repeat):
                names = args.variants if iteration % 2 == 0 else args.variants[::-1]
                for name in names:
                    if snapshot.get("kind") == "pair":
                        break
                    await variant(client, items, case, name)
                    finish(case["runs"][-1], snapshot, iteration)
                if snapshot.get("kind") == "pair":
                    await pair_control(client, items, case)
                    finish(case["runs"][-1], snapshot, iteration)
        models = {call["resolved_model"] for c in report["cases"] for r in c["runs"] for call in r["calls"]}
        if len(models) != 1:
            raise ValueError("Resolved model changed during the window experiment")
        report["status"] = "completed"
    finally:
        report["api_errors"] = client.errors
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2))


def finish(row: dict, snapshot: dict, iteration: int) -> None:
    row["iteration"] = iteration + 1
    row["checks"] = [{"evidence_id": evidence_id, "criterion": criterion,
        "score": row["scores"][evidence_id][criterion], "expected": expected,
        "passed": (row["scores"][evidence_id][criterion] >= 0.5) == expected,
    } for evidence_id, criteria in snapshot.get("expected", {}).items()
        for criterion, expected in criteria.items()]
    if snapshot.get("support_span") and row.get("passage_scores"):
        span = snapshot["support_span"]
        row["passage_checks"] = [{
            "passage_id": p["passage_id"],
            "expected": p["context_start"] <= span["start"] and p["context_end"] >= span["end"],
            "score": row["passage_scores"][p["passage_id"]]["directly_supports_answer"],
        } for p in row["coverage"]]
        for check in row["passage_checks"]:
            check["passed"] = (check["score"] >= 0.5) == check["expected"]
    print(json.dumps({k: row[k] for k in ("variant", "iteration", "seconds", "requests", "evidence_count")}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--controls-only", action="store_true")
    parser.add_argument("--concurrency", type=int, choices=range(1, 33))
    parser.add_argument("--repeat", type=int, choices=range(1, 11), default=2)
    parser.add_argument("--variants", nargs="+", choices=["compact_rank", "excerpt_windows", "source_windows"],
        default=["compact_rank", "excerpt_windows", "source_windows"])
    args = parser.parse_args()
    if Path(args.output).exists():
        parser.error("Preserve the existing report; choose a new output path")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
