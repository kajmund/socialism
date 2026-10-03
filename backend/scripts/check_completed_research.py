"""Measure completed-result reuse independently of research execution."""

import argparse
import asyncio
import json
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--need-id")
    parser.add_argument(
        "--question", help="Override the question to exercise nearby-result coverage"
    )
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--output")
    args = parser.parse_args()
    if not 1 <= args.repeat <= 100:
        parser.error("--repeat must be between 1 and 100")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tests.research_reuse.result_live import run

    print(json.dumps(asyncio.run(run(args)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
