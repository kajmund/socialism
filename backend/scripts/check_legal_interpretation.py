"""Run isolated legal interpretation with fixed models and source-bound quality criteria."""

import argparse
import asyncio
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--inputs", required=True)
    parser.add_argument("--configuration-ids", type=int, nargs="+", required=True)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 100:
        parser.error("--repeat must be between 1 and 100")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tests.research_reuse.legal_live import run

    result = asyncio.run(run(args))
    return int(any(not row["passed"] for row in result["runs"]))


if __name__ == "__main__":
    raise SystemExit(main())
