"""Benchmark OASIS simulations across DeepSeek model variants.

Compares wall time and simulation output for the same körning with different
DEEPSEEK_MODEL values. Intended for reasoning (deepseek-reasoner) vs chat
(deepseek-chat) comparisons.

Usage (from backend/):
  uv run python scripts/benchmark_simulation_models.py --run-id 3
  uv run python scripts/benchmark_simulation_models.py --run-id 3 \\
      --models deepseek-reasoner deepseek-chat
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database.models import Run
from app.database.session import SessionLocal
from app.services.oasis_run import OasisUnavailable, attempt_all_failed, simulate_run


@dataclass
class ModelBenchmarkResult:
    model: str
    wall_seconds: float
    status: str
    error: str | None
    variants: int
    ticks_run: int
    agent_count: int
    trace_events: int
    posts: int
    comments: int
    action_histogram: list[dict[str, Any]]


def _summarize_attempt(attempt: dict[str, Any]) -> dict[str, Any]:
    variants = attempt.get("variants") or []
    trace_events = 0
    posts = 0
    comments = 0
    ticks_run = 0
    agent_count = 0
    action_histogram: dict[str, int] = {}

    for variant in variants:
        ticks_run += int(variant.get("ticks_run") or 0)
        agent_count = max(agent_count, int(variant.get("agent_count") or 0))
        posts += len(variant.get("posts") or [])
        comments += len(variant.get("comments") or [])
        trace_events += len(variant.get("trace") or [])
        for row in variant.get("action_histogram") or []:
            action = str(row.get("action") or "unknown")
            action_histogram[action] = action_histogram.get(action, 0) + int(
                row.get("count") or 0
            )

    histogram_out = [
        {"action": action, "count": count}
        for action, count in sorted(action_histogram.items(), key=lambda x: (-x[1], x[0]))
    ]
    return {
        "variants": len(variants),
        "ticks_run": ticks_run,
        "agent_count": agent_count,
        "trace_events": trace_events,
        "posts": posts,
        "comments": comments,
        "action_histogram": histogram_out,
    }


async def benchmark_model(*, run_id: int, model: str) -> ModelBenchmarkResult:
    settings.deepseek_model = model
    settings.apply_oasis_env()

    async with SessionLocal() as session:
        result = await session.execute(
            select(Run)
            .options(selectinload(Run.population))
            .where(Run.id == run_id)
        )
        run = result.scalar_one_or_none()
        if run is None:
            raise SystemExit(f"Run {run_id} not found")

        started = time.perf_counter()
        error: str | None = None
        attempt: dict[str, Any] = {}
        try:
            results = await simulate_run(session, run)
            attempts = results.get("attempts") or []
            attempt = attempts[0] if attempts else {}
            if attempt.get("error"):
                error = str(attempt["error"])
            elif attempt_all_failed(attempt):
                error = "All variants failed"
        except (OasisUnavailable, RuntimeError, OSError) as exc:
            error = str(exc)
        elapsed = time.perf_counter() - started

        summary = _summarize_attempt(attempt)
        status = "failed" if error else "ok"
        return ModelBenchmarkResult(
            model=model,
            wall_seconds=round(elapsed, 2),
            status=status,
            error=error,
            variants=summary["variants"],
            ticks_run=summary["ticks_run"],
            agent_count=summary["agent_count"],
            trace_events=summary["trace_events"],
            posts=summary["posts"],
            comments=summary["comments"],
            action_histogram=summary["action_histogram"],
        )


def _format_comparison(results: list[ModelBenchmarkResult]) -> str:
    if len(results) < 2:
        return ""

    base, other = results[0], results[1]
    if base.wall_seconds <= 0:
        speed = "n/a"
    else:
        ratio = other.wall_seconds / base.wall_seconds
        faster = other.model if ratio < 1 else base.model
        pct = abs(1 - ratio) * 100
        speed = f"{faster} was ~{pct:.0f}% faster ({base.wall_seconds}s vs {other.wall_seconds}s)"

    lines = [
        "",
        "=== Jämförelse ===",
        f"Modell A ({base.model}): {base.wall_seconds}s — {base.status}",
        f"Modell B ({other.model}): {other.wall_seconds}s — {other.status}",
        f"Varaktighet: {speed}",
        f"Trace-händelser: {base.trace_events} vs {other.trace_events}",
        f"Inlägg: {base.posts} vs {other.posts}",
        f"Kommentarer: {base.comments} vs {other.comments}",
    ]
    return "\n".join(lines)


async def main_async(args: argparse.Namespace) -> None:
    if not settings.deepseek_api_key or settings.deepseek_api_key.startswith("placeholder"):
        raise SystemExit(
            "DEEPSEEK_API_KEY is required. Set it in backend/.env or the environment."
        )

    out: dict[str, Any] = {
        "run_id": args.run_id,
        "models": args.models,
        "results": [],
    }

    for model in args.models:
        print(f"\n--- Kör simulation med {model} ---")
        result = await benchmark_model(run_id=args.run_id, model=model)
        out["results"].append(asdict(result))
        print(
            f"{model}: {result.wall_seconds}s ({result.status}) "
            f"trace={result.trace_events} posts={result.posts} comments={result.comments}"
        )
        if result.error:
            print(f"  error: {result.error}")

    comparison = _format_comparison(
        [ModelBenchmarkResult(**row) for row in out["results"]]
    )
    if comparison:
        print(comparison)
        out["comparison_note"] = comparison.strip()

    if args.output:
        Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
        print(f"\nSparat till {args.output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark OASIS simulation models")
    parser.add_argument("--run-id", type=int, default=3, help="Körning id (default: 3)")
    parser.add_argument(
        "--models",
        nargs="+",
        default=["deepseek-reasoner", "deepseek-chat"],
        help="Models to compare (default: deepseek-reasoner deepseek-chat)",
    )
    parser.add_argument(
        "--output",
        default="data/benchmark_simulation_models.json",
        help="JSON output path (default: data/benchmark_simulation_models.json)",
    )
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
