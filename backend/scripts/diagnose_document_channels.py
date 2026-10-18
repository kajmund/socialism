"""Run the explicitly opted-in nine-turn document-channel diagnostic."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from scripts.document_presentation_benchmark.diagnostic_runner import run_diagnostic
from scripts.document_presentation_benchmark.step_b_types import CHANNELS


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Trace three chained document scenarios through three channels"
    )
    parser.add_argument("--run-live", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--channel",
        action="append",
        choices=CHANNELS,
        dest="channels",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        choices=("1", "2", "3"),
        dest="scenarios",
    )
    args = parser.parse_args()
    if not args.run_live:
        parser.error("--run-live is required")
    if args.output.exists():
        parser.error(f"refusing to overwrite existing output: {args.output}")
    channels = tuple(args.channels) if args.channels else CHANNELS
    scenarios = (
        tuple(int(value) for value in args.scenarios)
        if args.scenarios
        else (1, 2, 3)
    )
    payload = asyncio.run(
        run_diagnostic(
            channels=channels,
            scenario_sequences=scenarios,
        )
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
