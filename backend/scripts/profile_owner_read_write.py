"""Profile owner read/write contention: event-loop lag, reads, queue and writes."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

for _key in ("CEREBRAS_API_KEY", "OPENAI_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"):
    os.environ.setdefault(_key, "test-key")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import app.main  # noqa: E402,F401 - resolve the app import graph first

from app.services.overgraph.labels import FACT, scope_label  # noqa: E402
from app.services.overgraph.owner import OwnerClient  # noqa: E402
from app.services.overgraph.research_owner import collect_research_hits_via_owner  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
DIMENSION = 3072
GROUPS = 10
PER_GROUP = 100
BOUND = 20
MUTATIONS = 1000
READER_COUNTS = (1, 8)


def _stats(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0, "n": 0}

    def percentile(share: float) -> float:
        return ordered[max(0, math.ceil(share * len(ordered)) - 1)]

    return {
        "p50": round(statistics.median(ordered), 6),
        "p95": round(percentile(0.95), 6),
        "p99": round(percentile(0.99), 6),
        "max": round(ordered[-1], 6),
        "n": len(ordered),
    }


def _rows() -> list[dict[str, Any]]:
    rows = []
    for index in range(GROUPS * PER_GROUP):
        group = index % GROUPS
        position = index // GROUPS
        vector = [0.0] * DIMENSION
        if position < 10:
            vector[group] = 1.0
        else:
            vector[group] = 0.4
            vector[(group + 1) % GROUPS] = 0.2
        rows.append({
            "labels": [FACT, scope_label("customer:1")],
            "key": f"profile-fact-{index}",
            "props": {
                "scope_key": "customer:1", "predicate": "legal.rule",
                "status": "active", "source_key": f"missing-{group}",
                "target_key": f"missing-target-{group}",
                "fact_text": f"fact {index}", "attributes_json": "{}",
                "source_refs_json": "[]", "created_at_ms": index,
            },
            "dense_vector": vector,
        })
    return rows


def _vector(group: int = 0) -> list[float]:
    vector = [0.0] * DIMENSION
    vector[group] = 1.0
    return vector


def _spawn(root: Path, *, read_workers: int) -> subprocess.Popen[str]:
    argv = [
        sys.executable, "-m", "app.services.overgraph.owner",
        str(root / "catalog"), "--socket", str(root / "owner.sock"),
        "--dimension", str(DIMENSION), "--no-sync", "--profile-lag",
        "--read-workers", str(read_workers),
    ]
    return subprocess.Popen(
        argv, cwd=BACKEND, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )


async def _start(root: Path, *, read_workers: int) -> tuple[subprocess.Popen[str], OwnerClient]:
    process = _spawn(root, read_workers=read_workers)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            client = OwnerClient(root / "owner.sock")
            await client.health()
            return process, client
        except Exception:  # noqa: BLE001 - startup waiter
            await asyncio.sleep(0.05)
    process.kill()
    raise TimeoutError("owner did not start")


def _slice(samples: list[float], start: int) -> list[float]:
    return samples[start:]


async def _seed(client: OwnerClient) -> None:
    rows = _rows()
    for start in range(0, len(rows), 100):
        await client.mutate(f"profile-seed-{start}", {
            "upsert_nodes": rows[start:start + 100],
        }, kind="batch")


async def _reads(
    client: OwnerClient, *, readers: int, duration: float, bound: int,
) -> tuple[list[float], list[float]]:
    read_latencies: list[float] = []
    health_latencies: list[float] = []
    stop = asyncio.Event()
    query = _vector()

    async def reader() -> None:
        while not stop.is_set():
            started = time.perf_counter()
            await collect_research_hits_via_owner(
                client, customer_id=1, question_id=None,
                dense_query=query, bound=bound,
            )
            read_latencies.append(time.perf_counter() - started)

    async def pinger() -> None:
        own = OwnerClient(client.socket_path)
        while not stop.is_set():
            started = time.perf_counter()
            await own.health()
            health_latencies.append(time.perf_counter() - started)
            await asyncio.sleep(0.02)

    tasks = [asyncio.create_task(reader()) for _ in range(readers)]
    pinger_task = asyncio.create_task(pinger())
    await asyncio.sleep(duration)
    stop.set()
    await asyncio.gather(*tasks, pinger_task, return_exceptions=True)
    return read_latencies, health_latencies


async def _mutations(client: OwnerClient, prefix: str) -> list[float]:
    latencies = []
    row = _rows()[0]
    for index in range(MUTATIONS):
        started = time.perf_counter()
        await client.mutate(f"{prefix}-{index}", {
            "upsert_nodes": [{**row, "key": f"{prefix}-{index}"}],
        }, kind="batch")
        latencies.append(time.perf_counter() - started)
    return latencies


async def _metrics(client: OwnerClient) -> dict[str, Any]:
    return (await client.health())["metrics"]


def _delta(before: dict[str, Any], after: dict[str, Any], name: str) -> list[float]:
    return after[name][len(before[name]):]


def _tail(after: dict[str, Any], name: str, count: int) -> list[float]:
    return after[name][-count:] if count else []


async def _measure_mode(root: Path, *, read_workers: int) -> dict[str, Any]:  # noqa: PLR0915
    process, client = await _start(root, read_workers=read_workers)
    try:
        await _seed(client)
        before = await _metrics(client)
        baseline = await _mutations(client, "profile-baseline")
        after = await _metrics(client)
        baseline_parts = {
            "client": _stats(baseline),
            "queue_wait": _stats(_delta(before, after, "queue_wait_seconds")),
            "commit": _stats(_delta(before, after, "commit_seconds")),
            "loop_lag": _stats(_delta(before, after, "event_loop_lag_seconds")),
        }

        phases = {}
        for readers in READER_COUNTS:
            before_read = await _metrics(client)
            read_latency, health_latency = await _reads(
                client, readers=readers, duration=1.0, bound=BOUND,
            )
            after_read = await _metrics(client)
            read_only = {
                "reads": _stats(read_latency),
                "health": _stats(health_latency),
                "owner_read_seconds": _stats(
                    _tail(
                        after_read, "read_seconds",
                        after_read["read_ops"] - before_read["read_ops"],
                    )
                ),
                "loop_lag": _stats(after_read["event_loop_lag_seconds"]),
            }

            before_write = await _metrics(client)
            stop = asyncio.Event()
            loaded_read_latencies: list[float] = []

            async def reader() -> None:
                while not stop.is_set():
                    started = time.perf_counter()
                    await collect_research_hits_via_owner(
                        client, customer_id=1, question_id=None,
                        dense_query=_vector(), bound=BOUND,
                    )
                    loaded_read_latencies.append(time.perf_counter() - started)

            async def pinger() -> list[float]:
                own = OwnerClient(client.socket_path)
                samples = []
                while not stop.is_set():
                    started = time.perf_counter()
                    await own.health()
                    samples.append(time.perf_counter() - started)
                    await asyncio.sleep(0.02)
                return samples

            reader_tasks = [asyncio.create_task(reader()) for _ in range(readers)]
            pinger_task = asyncio.create_task(pinger())
            await asyncio.sleep(0.2)
            loaded = await _mutations(client, f"profile-loaded-{readers}")
            stop.set()
            health_loaded = await pinger_task
            await asyncio.gather(*reader_tasks, return_exceptions=True)
            after_write = await _metrics(client)
            loaded_parts = {
                "client": _stats(loaded),
                "queue_wait": _stats(_tail(
                    after_write, "queue_wait_seconds", MUTATIONS,
                )),
                "commit": _stats(_tail(
                    after_write, "commit_seconds",
                    after_write["applied"] - before_write["applied"],
                )),
                "read_seconds": _stats(_tail(
                    after_write, "read_seconds",
                    after_write["read_ops"] - before_write["read_ops"],
                )),
                "reads": _stats(loaded_read_latencies),
                "health": _stats(health_loaded),
                "loop_lag": _stats(after_write["event_loop_lag_seconds"]),
            }
            phases[str(readers)] = {
                "read_only": read_only,
                "reads_and_writes": loaded_parts,
            }

        bounds = {}
        for bound in (20, 200):
            before_bound = await _metrics(client)
            read_latency, health_latency = await _reads(
                client, readers=8, duration=0.8, bound=bound,
            )
            after_bound = await _metrics(client)
            bounds[str(bound)] = {
                "reads": _stats(read_latency),
                "health": _stats(health_latency),
                "owner_read_seconds": _stats(_tail(
                    after_bound, "read_seconds",
                    after_bound["read_ops"] - before_bound["read_ops"],
                )),
                "loop_lag": _stats(after_bound["event_loop_lag_seconds"]),
                "owner_reads": after_bound["read_ops"] - before_bound["read_ops"],
                "owner_read_bytes": after_bound["read_bytes"] - before_bound["read_bytes"],
            }
        return {
            "read_workers": read_workers,
            "baseline": baseline_parts,
            "phases": phases,
            "bounds_at_8_readers": bounds,
        }
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        if process.stderr is not None:
            errors = process.stderr.read()
            if errors:
                print(f"owner stderr ({process.pid}): {errors[-4000:]}", file=sys.stderr)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default="")
    args = parser.parse_args()
    report = {}
    for read_workers in (0, 4, 8):
        root = Path(tempfile.mkdtemp(prefix=f"owner-profile-{read_workers}-"))
        report["inline" if read_workers == 0 else f"workers_{read_workers}"] = (
            await _measure_mode(root, read_workers=read_workers)
        )
    print(json.dumps(report, indent=2))
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
