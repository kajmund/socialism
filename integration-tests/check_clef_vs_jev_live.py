"""Live A/B: clef:cloud vs Jev on the same golden set — quality and latency.

Runs the shared decision-model golden set (15 Swedish political-messaging
cases) against Ollama Cloud clef and TypeSafe Jev — the model that currently
drives Auto classification in the backend — and writes a side-by-side report.
Both models share the /v1/systemone protocol, so the same runner and the same
cases drive both.

Opt-in and metered: every run makes 30 real API calls (15 per model) with the
configured OLLAMA_API_KEY and TYPESAFE_API_KEY. Run from the repository root
with the backend environment installed:

    backend/.venv/bin/python integration-tests/check_clef_vs_jev_live.py

Keys are read from the process environment first, then backend/.env. The
report is saved as integration-tests/clef-vs-jev-live.json (gitignored);
credentials are never written to it.

Exit codes: 0 = both models completed and both met the accuracy floor;
1 = a case failed, timed out, or accuracy was below the floor for either
model; 2 = configuration or authentication error.
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
DEFAULT_REPORT = REPO_ROOT / "integration-tests" / "clef-vs-jev-live.json"


class ConfigError(Exception):
    """Missing or invalid configuration; nothing was called."""


@dataclass(frozen=True)
class CompareRun:
    clef: core.RunConfig
    jev: core.RunConfig
    min_accuracy: float
    report_path: Path


def _resolve(
    process: dict[str, str], dotenv: dict[str, str], name: str
) -> str:
    return (process.get(name, "").strip() or dotenv.get(name, "").strip())


def _load_config(args: argparse.Namespace) -> CompareRun:
    dotenv = core.read_dotenv(Path(args.env_file))
    process = os.environ
    clef_key = _resolve(process, dotenv, "OLLAMA_API_KEY")
    if not clef_key:
        raise ConfigError(
            "OLLAMA_API_KEY is missing: set it in the environment or in backend/.env"
        )
    jev_key = _resolve(process, dotenv, "TYPESAFE_API_KEY")
    if not jev_key:
        raise ConfigError(
            "TYPESAFE_API_KEY is missing: set it in the environment or in backend/.env"
        )
    clef_base = (
        _resolve(process, dotenv, "OLLAMA_BASE_URL") or args.clef_base_url
    ).rstrip("/")
    jev_base = (
        _resolve(process, dotenv, "TYPESAFE_BASE_URL") or args.jev_base_url
    ).rstrip("/")
    if not clef_base or not jev_base:
        raise ConfigError("a base URL is empty")
    if not 0.0 <= args.min_accuracy <= 1.0:
        raise ConfigError("--min-accuracy must be between 0.0 and 1.0")
    if args.timeout <= 0:
        raise ConfigError("--timeout must be positive")
    return CompareRun(
        clef=core.RunConfig(
            api_key=clef_key,
            base_url=clef_base,
            model=args.clef_model,
            timeout_seconds=args.timeout,
        ),
        jev=core.RunConfig(
            api_key=jev_key,
            base_url=jev_base,
            model=args.jev_model,
            timeout_seconds=args.timeout,
        ),
        min_accuracy=args.min_accuracy,
        report_path=Path(args.report),
    )


def _per_case(clef_report: dict[str, Any], jev_report: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for clef_case, jev_case in zip(clef_report["cases"], jev_report["cases"]):
        rows.append(
            {
                "id": clef_case["id"],
                "type": clef_case["type"],
                "expected": clef_case["expected"],
                "clef": _side(clef_case),
                "jev": _side(jev_case),
            }
        )
    return rows


def _side(case: dict[str, Any]) -> dict[str, Any]:
    side: dict[str, Any] = {
        "actual": case.get("actual"),
        "correct": case.get("correct"),
        "ok": case.get("ok"),
        "latency_ms": case.get("latency_ms"),
    }
    if case.get("error") is not None:
        side["error"] = case["error"]
    return side


async def _run_comparison(run: CompareRun) -> dict[str, Any]:
    clef_report = await core.run_report(run.clef, stage="clef_case")
    jev_report = await core.run_report(run.jev, stage="jev_case")
    return {
        "clef": clef_report,
        "jev": jev_report,
        "per_case": _per_case(clef_report, jev_report),
    }


def _print_comparison(report: dict[str, Any], run: CompareRun) -> None:
    floor = run.min_accuracy * 100
    print(f"accuracy floor: {floor:.0f}%", flush=True)
    header = (
        f"{'model':<14} {'correct':>8} {'acc':>7} {'choice':>7} "
        f"{'noul':>6} {'score':>6} {'min ms':>8} {'med ms':>8} "
        f"{'p95 ms':>8} {'wall s':>7}"
    )
    print(header, flush=True)
    for label, section in (("clef:cloud", report["clef"]), ("jev", report["jev"])):
        summary = section["summary"]
        by_type = summary["accuracy_by_type"]
        latency = summary["latency"]
        row = (
            f"{label:<14} {summary['cases_correct']:>6}/{summary['cases_total']:<2} "
            f"{summary['accuracy_overall'] * 100:>6.1f}% "
            f"{by_type.get('choice', 0.0) * 100:>6.0f}% "
            f"{by_type.get('noul', 0.0) * 100:>5.0f}% "
            f"{by_type.get('score', 0.0) * 100:>5.0f}% "
            f"{latency['min_ms']:>7.0f} "
            f"{latency['median_ms']:>7.0f} "
            f"{latency['p95_ms']:>7.0f} "
            f"{summary['total_wall_seconds']:>6.1f}"
        )
        print(row, flush=True)
    print(f"report: {run.report_path}", flush=True)


def _passes(report: dict[str, Any], run: CompareRun) -> bool:
    summary = report["summary"]
    return summary["cases_failed"] == 0 and summary["accuracy_overall"] >= run.min_accuracy


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Live A/B: clef:cloud vs Jev on the shared decision golden set"
    )
    parser.add_argument("--clef-model", default="clef:cloud", help="clef model tag")
    parser.add_argument("--jev-model", default="jev-latest", help="Jev model tag")
    parser.add_argument(
        "--clef-base-url", default="https://ollama.com", help="Ollama Cloud base URL"
    )
    parser.add_argument(
        "--jev-base-url", default="https://api.typesafe.ai", help="TypeSafe base URL"
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
        report = asyncio.run(_run_comparison(run))
    except core.AuthError as exc:
        print(f"authentication error: {exc}", file=sys.stderr)
        return 2
    run.report_path.parent.mkdir(parents=True, exist_ok=True)
    run.report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"
    )
    _print_comparison(report, run)
    if _passes(report["clef"], run) and _passes(report["jev"], run):
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
