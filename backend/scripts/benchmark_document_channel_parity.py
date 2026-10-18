"""Explicitly opted-in CLI for the live Step B channel-parity experiment."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from scripts.document_presentation_benchmark.step_b_runner import run_step_b


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run 50 gold cases through three live expert-turn channels"
    )
    parser.add_argument(
        "--run-live",
        action="store_true",
        help="Required acknowledgement that this makes 150 live model turns.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Required JSON output path; an existing file is never overwritten.",
    )
    args = parser.parse_args()
    if not args.run_live:
        parser.error("--run-live is required")
    if args.output.exists():
        parser.error(f"refusing to overwrite existing output: {args.output}")
    payload = asyncio.run(run_step_b())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()

