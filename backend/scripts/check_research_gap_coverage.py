"""Opt-in step-3 quality benchmark; does not run source retrieval or a full research."""

import argparse
import asyncio
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--need-id")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--rubric", required=True)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--output", default="coverage.json")
    args = parser.parse_args()
    if not 1 <= args.repeat <= 100:
        parser.error("--repeat must be between 1 and 100")
    if Path(args.output).name != args.output:
        parser.error("--output must be a filename within the workspace")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tests.research_reuse.coverage_live import run

    result = asyncio.run(run(args))
    print(
        json.dumps(
            [
                {
                    "iteration": row["iteration"],
                    "planning_seconds": row["planning_seconds"],
                    "passed": row["passed"],
                    "criteria": {
                        c["criterion_id"]: c["status"] for c in row["evaluation"]["criteria"]
                    },
                }
                for row in result["runs"]
            ],
            ensure_ascii=False,
            indent=2,
        )
    )
    return int(any(not row["passed"] for row in result["runs"]))


if __name__ == "__main__":
    raise SystemExit(main())
