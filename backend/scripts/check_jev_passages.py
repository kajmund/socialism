"""Compare compact, full and batched Jev screening on one frozen evidence replay."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.jev.system import JevSystemOne
    from app.services.research.assessment import AssessableEvidence


async def run(args: argparse.Namespace) -> dict:
    # Same standalone bootstrap as the four-step real-service laboratory.
    from tests.research_reuse.live import workload  # noqa: F401
    from app.config import settings
    from app.jev.system import HttpJevSystemOne
    from app.services.research.assessment import group_evidence_for_review
    from app.services.research.fast_controller import research_jev_model
    from app.services.research.evidence_screen import EVIDENCE_SCREEN_QUESTIONS
    from app.services.research.reuse_gate import assessable_candidates
    from tests.research_reuse.snapshots import EVIDENCE, digest

    if not settings.typesafe_api_key.strip():
        raise ValueError("The configured Jev API key is required")
    snapshot = json.loads(Path(args.input).read_text(encoding="utf-8"))
    candidates = assessable_candidates(EVIDENCE.validate_python(snapshot["evidence"]))
    groups = group_evidence_for_review(candidates)
    items = [group.evidence for group in groups]
    if args.limit:
        items = items[:args.limit]
    model = research_jev_model()
    report = {
        "snapshot_sha256": digest(snapshot), "question": snapshot["need"]["question"],
        "configured_model": model,
        "concurrency": args.concurrency if args.concurrency is not None else settings.research_jev_concurrency,
        "timeout_seconds": settings.research_jev_timeout_seconds, "runs": [],
        "original_evidence_count": len(candidates), "review_groups": len(groups),
        "duplicate_bindings": {group.evidence.evidence_id: list(group.duplicate_evidence_ids)
            for group in groups if group.duplicate_evidence_ids},
        "question_schema_sha256": digest(EVIDENCE_SCREEN_QUESTIONS),
        "compact_max_state_chars": settings.research_jev_max_state_chars,
        "selected_evidence_ids": [item.evidence_id for item in items],
        "variants": args.variants,
    }
    # Equal connection behavior: the production client owns one HTTP client per request.
    client = HttpJevSystemOne()
    report["status"] = "incomplete"
    try:
        if not args.controls_only:
            await replay(client, items, report, repeat=args.repeat)
        if args.controls:
            report["controls"] = []
            await control_runs(client, report, repeat=args.repeat)
        report["status"] = "completed"
    finally:
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


async def replay(
    client: JevSystemOne, items: list[AssessableEvidence], report: dict, *, repeat: int,
) -> None:
    from app.config import settings
    from tests.research_reuse.jev_passages import measure, requests

    for iteration in range(repeat):
        order = list(report["variants"])
        if iteration % 2:
            order.reverse()
        for variant in order:
            report["active_variant"] = variant
            row = {"variant": variant, "iteration": iteration + 1,
                "status": "incomplete", "calls": []}
            report["runs"].append(row)
            measured = await measure(
                client, requests(items, objective=report["question"], variant=variant,
                    max_state_chars=settings.research_jev_max_state_chars),
                model=report["configured_model"], concurrency=report["concurrency"],
                timeout_seconds=settings.research_jev_timeout_seconds,
                journal=row["calls"],
            )
            row.update(measured)
            models = {call["resolved_model"] for call in row["calls"]}
            if report["runs"] and models != {report["runs"][0]["calls"][0]["resolved_model"]}:
                raise ValueError("Resolved Jev model changed between variants")
            row["status"] = "completed"
            print(json.dumps({k: row[k] for k in (
                "variant", "iteration", "seconds", "requests", "evidence_count",
            )}), flush=True)


async def control_runs(client: JevSystemOne, report: dict, *, repeat: int) -> None:
    from app.services.research.reuse_gate import assessable_candidates
    from tests.research_reuse.jev_controls import snapshots
    from tests.research_reuse.snapshots import EVIDENCE, digest

    for snapshot in snapshots():
        case = {
            "name": snapshot["name"], "question": snapshot["need"]["question"],
            "expected": snapshot["expected"], "configured_model": report["configured_model"],
            "concurrency": report["concurrency"], "variants": report["variants"], "runs": [],
            "snapshot": snapshot, "snapshot_sha256": digest(snapshot),
        }
        report["controls"].append(case)
        await replay(client, assessable_candidates(EVIDENCE.validate_python(snapshot["evidence"])),
            case, repeat=repeat)
        reference = report["runs"] or report["controls"][0]["runs"]
        if (
            case["runs"][0]["calls"][0]["resolved_model"]
            != reference[0]["calls"][0]["resolved_model"]
        ):
            raise ValueError("Resolved Jev model changed between workload and controls")
        for row in case["runs"]:
            row["checks"] = [{
                "evidence_id": evidence_id, "criterion": criterion, "expected": expected,
                "score": row["scores"][evidence_id][criterion],
                "passed": (row["scores"][evidence_id][criterion] >= 0.5) == expected,
            } for evidence_id, criteria in case["expected"].items()
                for criterion, expected in criteria.items()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--repeat", type=int, default=2, choices=range(1, 11))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--controls", action="store_true", help="Also run synthetic labeled controls")
    parser.add_argument("--controls-only", action="store_true")
    parser.add_argument("--concurrency", type=int, choices=range(1, 33), help="Explicit experiment concurrency")
    parser.add_argument("--variants", nargs="+", choices=["compact", "full", "batched", "batched_refs"],
        default=["compact", "full", "batched_refs"])
    args = parser.parse_args()
    if Path(args.output).exists():
        parser.error("Output already exists; preserve the previous experiment and choose a new path")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if args.controls_only and not args.controls:
        parser.error("--controls-only requires --controls")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
