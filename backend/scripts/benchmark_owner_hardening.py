"""Measure owner RPC, queue, commit, sync, concurrency and restart behavior."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
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

import app.main  # noqa: E402,F401 - resolves the app import graph before direct module imports

from app.services.graph_v2.types import FactInput, SourceRef  # noqa: E402
from app.services.knowledge.scope import customer_scope  # noqa: E402
from app.services.overgraph.owner import OwnerClient  # noqa: E402
from app.services.overgraph.owner_facts import write_fact_via_owner  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
DIMENSION = 4
SIZES = (1, 100, 1000)
REPEATS = 30
CONCURRENT_CLIENTS = 16
CONCURRENT_EACH = 25


def _stats(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "p50": round(statistics.median(ordered), 5),
        "p95": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 5),
        "max": round(ordered[-1], 5),
    }


def _spawn_owner(root: Path, *, sync: bool) -> subprocess.Popen[str]:
    argv = [
        sys.executable, "-m", "app.services.overgraph.owner",
        str(root / "catalog"), "--socket", str(root / "owner.sock"),
        "--dimension", str(DIMENSION),
    ]
    if not sync:
        argv.append("--no-sync")
    process = subprocess.Popen(
        argv, cwd=BACKEND, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        text=True,
    )
    return process


async def _wait_owner(root: Path) -> None:
    deadline = time.monotonic() + 20
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            await OwnerClient(root / "owner.sock").health()
            return
        except Exception as exc:  # noqa: BLE001 - waiter
            last = exc
            await asyncio.sleep(0.05)
    raise TimeoutError(f"owner not ready: {last}")


def _stop(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _nodes(prefix: str, count: int) -> list[dict[str, Any]]:
    return [
        {
            "labels": ["TextUnit", "bench"],
            "key": f"{prefix}-{index}",
            "props": {"text": f"unit {index}", "content_hash": f"{prefix}-{index}"},
        }
        for index in range(count)
    ]


def _metric_slice(before: dict[str, Any], after: dict[str, Any], name: str) -> list[float]:
    return list(after["metrics"].get(name) or [])[len(before["metrics"].get(name) or []):]


async def _rpc_batch(
    client: OwnerClient, prefix: str, size: int, repeats: int,
) -> dict[str, Any]:
    latencies: list[float] = []
    errors = 0
    for repeat in range(repeats):
        nodes = _nodes(f"{prefix}-{repeat}", size)
        started = time.perf_counter()
        result = await client.mutate(f"{prefix}-{repeat}", {"upsert_nodes": nodes}, kind="batch")
        latencies.append(time.perf_counter() - started)
        if not result.get("ok"):
            errors += 1
    return {"latencies": latencies, "errors": errors, "bytes": size}


async def _measure_mode(root: Path, *, sync: bool) -> dict[str, Any]:
    owner = _spawn_owner(root, sync=sync)
    await _wait_owner(root)
    try:
        client = OwnerClient(root / "owner.sock")
        health_before = await client.health()
        batches = {}
        for size in SIZES:
            result = await _rpc_batch(client, f"{'sync' if sync else 'nosync'}-{size}", size, REPEATS)
            batches[str(size)] = {
                "rpc": _stats(result["latencies"]),
                "errors": result["errors"],
            }
        health_after = await client.health()
        batches["queue_wait"] = _stats(
            _metric_slice(health_before, health_after, "queue_wait_seconds") or [0.0],
        )
        batches["commit"] = _stats(
            _metric_slice(health_before, health_after, "commit_seconds") or [0.0],
        )
        batches["sync"] = _stats(
            _metric_slice(health_before, health_after, "sync_seconds") or [0.0],
        )
        return {
            "sync_on_commit": sync,
            "batches": batches,
            "owner_metrics": health_after["metrics"],
        }
    finally:
        _stop(owner)


async def _concurrent_writes(root: Path) -> dict[str, Any]:
    owner = _spawn_owner(root, sync=True)
    await _wait_owner(root)
    try:
        async def worker(index: int) -> list[float]:
            client = OwnerClient(root / "owner.sock")
            latencies = []
            for repeat in range(CONCURRENT_EACH):
                key = f"conc-{index}-{repeat}"
                started = time.perf_counter()
                result = await client.mutate(key, {"upsert_nodes": _nodes(key, 1)}, kind="batch")
                latencies.append(time.perf_counter() - started)
                if not result.get("ok"):
                    raise RuntimeError(result)
            return latencies

        started = time.perf_counter()
        results = await asyncio.gather(*(worker(index) for index in range(CONCURRENT_CLIENTS)))
        wall = time.perf_counter() - started
        values = [value for row in results for value in row]
        return {
            "clients": CONCURRENT_CLIENTS,
            "mutations_per_client": CONCURRENT_EACH,
            "total": len(values),
            "wall_seconds": round(wall, 3),
            "throughput_per_second": round(len(values) / wall, 1),
            "rpc": _stats(values),
        }
    finally:
        _stop(owner)


async def _concurrent_fact_writes(root: Path) -> dict[str, Any]:
    owner = _spawn_owner(root, sync=True)
    await _wait_owner(root)
    try:
        client = OwnerClient(root / "owner.sock")
        scope = customer_scope(1)
        await client.mutate("seed-facts", {"upsert_nodes": [
            {"labels": ["Entity", "scope.customer.1"], "key": "src", "props": {"scope_key": scope.scope_key}},
            {"labels": ["Entity", "scope.customer.1"], "key": "dst", "props": {"scope_key": scope.scope_key}},
            *[
                {
                    "labels": ["TextUnit", "scope.customer.1"],
                    "key": f"u{index}",
                    "props": {
                        "scope_key": scope.scope_key, "text": "text",
                        "content_hash": f"u{index}", "document_id": "doc",
                        "document_version_id": "ver",
                    },
                }
                for index in range(CONCURRENT_CLIENTS)
            ],
        ]}, kind="batch")

        async def worker(index: int) -> float:
            started = time.perf_counter()
            await write_fact_via_owner(
                client,
                FactInput(
                    source_id="src", target_id="dst", scope=scope,
                    predicate="legal.has", fact_text=f"faktum {index}",
                    sources=(SourceRef("text_unit", f"u{index}"),),
                ),
            )
            return time.perf_counter() - started

        started = time.perf_counter()
        latencies = await asyncio.gather(*(worker(index) for index in range(CONCURRENT_CLIENTS)))
        wall = time.perf_counter() - started
        return {
            "concurrent": CONCURRENT_CLIENTS,
            "wall_seconds": round(wall, 3),
            "mutations": len(latencies),
            "latency": _stats(list(latencies)),
        }
    finally:
        _stop(owner)


async def _durability_measure(root: Path, *, sync: bool, mutations: int = 30) -> dict[str, Any]:
    owner = _spawn_owner(root, sync=sync)
    await _wait_owner(root)
    try:
        client = OwnerClient(root / "owner.sock")
        for index in range(mutations):
            result = await client.mutate(
                f"durability-{index}",
                {"upsert_nodes": [{
                    "labels": ["DurabilityTrial", "owner-test"],
                    "key": f"trial-{index}",
                    "props": {"value": index},
                }]},
                kind="batch",
            )
            if not result.get("ok"):
                raise RuntimeError(result)
        owner.kill()  # SIGKILL right after the last ack
        owner.wait(timeout=10)
        owner = _spawn_owner(root, sync=sync)
        await _wait_owner(root)
        rows = await OwnerClient(root / "owner.sock").list_nodes("DurabilityTrial")
        return {
            "sync_on_commit": sync,
            "acked": mutations,
            "recovered": len(rows),
            "lost": mutations - len(rows),
        }
    finally:
        _stop(owner)


async def _restart_measure(root: Path) -> dict[str, Any]:
    owner = _spawn_owner(root, sync=True)
    await _wait_owner(root)
    try:
        client = OwnerClient(root / "owner.sock")
        await client.mutate("before-restart", {"upsert_nodes": _nodes("before", 1)}, kind="batch")
        started = time.perf_counter()
        _stop(owner)
        owner = _spawn_owner(root, sync=True)
        await _wait_owner(root)
        ready_seconds = time.perf_counter() - started
        started = time.perf_counter()
        await OwnerClient(root / "owner.sock").mutate(
            "after-restart", {"upsert_nodes": _nodes("after", 1)}, kind="batch",
        )
        first_write_seconds = time.perf_counter() - started
        return {
            "restart_to_ready_seconds": round(ready_seconds, 3),
            "first_write_after_restart_seconds": round(first_write_seconds, 4),
        }
    finally:
        _stop(owner)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default="")
    args = parser.parse_args()
    base = Path(tempfile.mkdtemp(prefix="owner-bench-"))

    async def run() -> dict[str, Any]:
        sync = await _measure_mode(base / "sync", sync=True)
        nosync = await _measure_mode(base / "nosync", sync=False)
        concurrent = await _concurrent_writes(base / "concurrent")
        facts = await _concurrent_fact_writes(base / "facts")
        restart = await _restart_measure(base / "restart")
        durability_sync = await _durability_measure(base / "durability-sync", sync=True)
        durability_nosync = await _durability_measure(
            base / "durability-nosync", sync=False,
        )
        return {
            "durable_mode": sync,
            "no_sync_mode": nosync,
            "concurrent_text_units": concurrent,
            "concurrent_facts": facts,
            "restart": restart,
            "durability": {
                "sync": durability_sync,
                "no_sync": durability_nosync,
            },
        }

    report = asyncio.run(run())
    report["root"] = str(base)
    print(json.dumps(report, indent=2))
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
