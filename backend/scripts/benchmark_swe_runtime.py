"""Baseline SWE runtime overhead. No LLM or network."""

from __future__ import annotations

import argparse
import asyncio
import time
from collections.abc import Mapping
from typing import Any

from app.swe.definition import compile_definition
from app.swe.runtime import run_workflow


def _compile(nodes: dict[str, Any], **kwargs: Any) -> object:
    document = {
        "version": "1.0",
        "name": kwargs.get("name", "bench"),
        "entrypoint": kwargs.get("entrypoint", "loop"),
        "limits": kwargs["limits"],
        "nodes": nodes,
    }
    return compile_definition(document, handlers=kwargs.get("handlers"))


def _decision_loop(steps: int) -> object:
    return _compile(
        {
            "loop": {
                "type": "decision",
                "evaluator": "expression",
                "condition": {
                    "lt": [
                        {"var": "$.run.steps_used"},
                        {"const": steps},
                    ]
                },
                "routes": {"true": "loop", "false": "done"},
            },
            "done": {"type": "end", "status": "completed"},
        },
        name="bench_loop",
        entrypoint="loop",
        limits={"max_steps": steps + 8, "max_depth": 1, "timeout_seconds": 60},
    )


def _fanout(count: int) -> object:
    return _compile(
        {
            "fanout": {
                "type": "map",
                "items": "$.items",
                "child": "work",
                "concurrency": 32,
                "next": "done",
            },
            "work": {"type": "task", "handler": "bench.work"},
            "done": {"type": "end", "status": "completed"},
        },
        name="bench_map",
        entrypoint="fanout",
        limits={"max_steps": count + 16, "max_depth": 2, "timeout_seconds": 60},
        handlers=frozenset({"bench.work"}),
    )


async def _work(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    return {"index": payload["index"]}


async def _run() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, default=10000)
    parser.add_argument("--fanout", type=int, default=1000)
    args = parser.parse_args()

    started = time.perf_counter()
    loop = await run_workflow(_decision_loop(args.steps), {}, {})
    loop_ms = (time.perf_counter() - started) * 1000
    if loop.status != "completed":
        raise SystemExit(f"decision loop failed: {loop.status} {loop.error}")

    started = time.perf_counter()
    fan = await run_workflow(
        _fanout(args.fanout),
        {"bench.work": _work},
        {"items": list(range(args.fanout))},
    )
    fan_ms = (time.perf_counter() - started) * 1000
    if fan.status != "completed":
        raise SystemExit(f"fan-out failed: {fan.status} {fan.error}")

    print(f"deterministic_transitions steps={args.steps} ms={loop_ms:.2f}")
    print(f"async_fanout items={args.fanout} ms={fan_ms:.2f}")
    print(f"events loop={len(loop.events)} fanout={len(fan.events)}")


if __name__ == "__main__":
    asyncio.run(_run())
