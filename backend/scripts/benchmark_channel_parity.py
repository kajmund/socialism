"""Run the isolated deterministic Step A channel-parity experiment."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.main import app as _application
from scripts.channel_parity_experiment import run_experiment


def main() -> None:
    if _application is None:
        raise RuntimeError("application import failed")
    parser = argparse.ArgumentParser(description="Capture deterministic channel parity")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = asyncio.run(run_experiment())
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
