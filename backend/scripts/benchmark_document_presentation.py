"""CLI and compatibility exports for the document-presentation benchmark.

Run from ``backend/``:

    uv run python scripts/benchmark_document_presentation.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from app.llm import complete_with_tools
from app.services.document_tool_retrieval import expose_workspace_tools
from scripts.document_presentation_benchmark.cases import (
    build_gold_cases,
    state_for_case as _state_for_case,
)
from scripts.document_presentation_benchmark.report import summarize_results
from scripts.document_presentation_benchmark.runner import (
    run_benchmark as _run_benchmark,
    run_paired_case as _run_paired_case_impl,
)
from scripts.document_presentation_benchmark.types import (
    BenchmarkEnvironment,
    CallCounts,
    CaseResult,
    FindRunner,
    GoldCase,
    PresentationDecision,
)
from scripts.document_presentation_benchmark.validation import (
    experimental_find_spec,
    production_find_arguments,
    validate_gallery_continuation,
)

__all__ = (
    "CallCounts",
    "GoldCase",
    "PresentationDecision",
    "_run_paired_case",
    "_state_for_case",
    "build_gold_cases",
    "experimental_find_spec",
    "main",
    "production_find_arguments",
    "run_benchmark",
    "summarize_results",
    "validate_gallery_continuation",
)


async def run_benchmark() -> dict:
    return await _run_benchmark(
        expose_tools=expose_workspace_tools,
        complete_tools=complete_with_tools,
    )


async def _run_paired_case(
    case: GoldCase,
    *,
    environment: BenchmarkEnvironment,
    find_runner: FindRunner,
) -> tuple[CaseResult, CaseResult]:
    return await _run_paired_case_impl(
        case,
        environment=environment,
        find_runner=find_runner,
        expose_tools=expose_workspace_tools,
        complete_tools=complete_with_tools,
    )


def _default_output() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path("data") / f"benchmark_document_presentation-{stamp}.json"


def _write_output(payload: dict, output: Path, *, explicit: bool) -> None:
    if output.exists() and not explicit:
        raise FileExistsError(f"refusing to overwrite default benchmark output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark deterministic document gallery continuation"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="JSON output path. Explicit paths may overwrite an existing file.",
    )
    args = parser.parse_args()
    output = args.output or _default_output()
    payload = asyncio.run(run_benchmark())
    _write_output(payload, output, explicit=args.output is not None)
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
