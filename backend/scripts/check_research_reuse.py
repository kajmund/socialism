"""Run one research reuse stage with real services, using replay files between stages."""

import argparse
import asyncio
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        required=True,
        help="Explicitly use the configured database and external services",
    )
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--need-id", help="Probe a subquestion; omit for the main question")
    parser.add_argument("--step", choices=["1", "2", "3", "4", "all"], default="all")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--workspace", help="Local directory for snapshots and timings")
    parser.add_argument(
        "--fetch-gap", type=int, help="Step 3: run lagen.nu for one gap (one-based)"
    )
    args = parser.parse_args()
    if not 1 <= args.repeat <= 100:
        parser.error("--repeat must be between 1 and 100")
    if args.fetch_gap is not None and args.step not in {"3", "all"}:
        parser.error("--fetch-gap requires step 3")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tests.research_reuse.live import run

    result = asyncio.run(run(args))
    print(
        json.dumps(
            {"question": result["question"], "summary": result["summary"]},
            ensure_ascii=False,
            indent=2,
        )
    )
    return int(any(row["status"] in {"error", "contract_failed"} for row in result["measurements"]))


if __name__ == "__main__":
    raise SystemExit(main())
