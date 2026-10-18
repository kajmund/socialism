"""Live check: Ollama Cloud decision model clef:cloud — quality and latency.

Exercises the real Ollama Cloud /v1/systemone endpoint with the shared golden
set of 15 Swedish political-messaging cases (5 choice, 5 noul, 5 score) and
measures both decision quality and time. One HTTP call per case; quality is
accuracy against the expected answer, time is per-call latency
(min/median/p95/max/mean) plus total wall time.

Opt-in and metered: every run makes 15 real API calls to Ollama Cloud with the
configured OLLAMA_API_KEY. Run from the repository root with the backend
environment installed:

    backend/.venv/bin/python integration-tests/check_clef_cloud_live.py

The API key is read from the process environment first, then backend/.env.
The report is saved as integration-tests/clef-cloud-live.json (gitignored);
credentials are never written to it. Text-only by design: clef also judges
images, but the golden set here uses text states.

Exit codes: 0 = every case completed and overall accuracy met the floor;
1 = a case failed, timed out, or accuracy was below the floor; 2 = configuration
or authentication error.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import decision_check_core as core

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = REPO_ROOT / "backend" / ".env"
DEFAULT_REPORT = REPO_ROOT / "integration-tests" / "clef-cloud-live.json"


class ConfigError(Exception):
    """Missing or invalid configuration; nothing was called."""


@dataclass(frozen=True)
class ClefRun:
    config: core.RunConfig
    min_accuracy: float
    report_path: Path


def _load_config(args: argparse.Namespace) -> ClefRun:
    dotenv = core.read_dotenv(Path(args.env_file))
    api_key = os.environ.get("OLLAMA_API_KEY", "").strip()
    if not api_key:
        api_key = dotenv.get("OLLAMA_API_KEY", "").strip()
    if not api_key:
        raise ConfigError(
            "OLLAMA_API_KEY is missing: set it in the environment or in backend/.env"
        )
    base_url = (
        os.environ.get("OLLAMA_BASE_URL", "").strip()
        or dotenv.get("OLLAMA_BASE_URL", "").strip()
        or args.base_url
    ).rstrip("/")
    if not base_url:
        raise ConfigError("OLLAMA_BASE_URL is empty")
    if not 0.0 <= args.min_accuracy <= 1.0:
        raise ConfigError("--min-accuracy must be between 0.0 and 1.0")
    if args.timeout <= 0:
        raise ConfigError("--timeout must be positive")
    return ClefRun(
        config=core.RunConfig(
            api_key=api_key,
            base_url=base_url,
            model=args.model,
            timeout_seconds=args.timeout,
        ),
        min_accuracy=args.min_accuracy,
        report_path=Path(args.report),
    )


def _print_summary(report: dict[str, Any], run: ClefRun) -> None:
    summary = report["summary"]
    accuracy = summary["accuracy_overall"] * 100
    floor = run.min_accuracy * 100
    print(
        f"{run.config.model} — {summary['cases_total']} cases, "
        f"{summary['cases_correct']} correct ({accuracy:.1f}%), "
        f"{summary['cases_failed']} failed, floor {floor:.0f}%",
        flush=True,
    )
    latency = summary["latency"]
    if latency:
        print(
            f"latency ms — min {latency['min_ms']}, median {latency['median_ms']}, "
            f"p95 {latency['p95_ms']}, max {latency['max_ms']}, "
            f"mean {latency['mean_ms']}; total wall {summary['total_wall_seconds']} s",
            flush=True,
        )
    print(f"report: {run.report_path}", flush=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Live quality and latency check for Ollama Cloud clef:cloud"
    )
    parser.add_argument("--model", default="clef:cloud", help="model tag (default: clef:cloud)")
    parser.add_argument(
        "--base-url", default="https://ollama.com", help="Ollama Cloud base URL"
    )
    parser.add_argument(
        "--timeout", type=float, default=30.0, help="per-call timeout in seconds (default: 30)"
    )
    parser.add_argument(
        "--min-accuracy",
        type=float,
        default=0.8,
        help="overall accuracy floor, 0.0-1.0 (default: 0.8)",
    )
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE), help="dotenv to read")
    parser.add_argument("--report", default=str(DEFAULT_REPORT), help="JSON report path")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        run = _load_config(args)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    try:
        report = asyncio.run(core.run_report(run.config, stage="clef_cloud_case"))
    except core.AuthError as exc:
        print(f"authentication error: {exc}", file=sys.stderr)
        return 2
    run.report_path.parent.mkdir(parents=True, exist_ok=True)
    run.report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"
    )
    _print_summary(report, run)
    summary = report["summary"]
    if summary["cases_failed"] or summary["accuracy_overall"] < run.min_accuracy:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
