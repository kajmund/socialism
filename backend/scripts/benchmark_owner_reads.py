"""Compare bounded owner reads with local catalog reads (same seeded data)."""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from app.services.overgraph.owner import OwnerClient

BACKEND = Path(__file__).resolve().parents[1]
DIMENSION = 4
NODE_COUNT = 3000
SIZES = (1, 100, 1000)
REPEATS = 20
CONCURRENCY = (1, 8, 32, 100)


def _stats(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "p50": round(statistics.median(ordered), 5),
        "p95": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 5),
        "max": round(ordered[-1], 5),
    }


def _spawn_owner(root: Path) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        [
            sys.executable, "-m", "app.services.overgraph.owner",
            str(root / "catalog"), "--socket", str(root / "owner.sock"),
            "--dimension", str(DIMENSION), "--no-sync",
        ],
        cwd=BACKEND, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True,
    )
    return process


async def _wait_owner(root: Path) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            await OwnerClient(root / "owner.sock").health()
            return
        except Exception:  # noqa: BLE001 - startup waiter
            await asyncio.sleep(0.05)
    raise TimeoutError("owner did not start")


def _nodes(prefix: str, count: int, *, start: int = 0) -> list[dict[str, Any]]:
    return [
        {
            "labels": ["TextUnit", "scope.customer.1"],
            "key": f"{prefix}-{start + index}",
            "props": {
                "scope_key": "customer:1",
                "document_id": "doc-read-bench",
                "document_version_id": "ver-read-bench",
                "ordinal": start + index,
                "text": f"unit {start + index}",
                "content_hash": f"hash-{start + index}",
            },
            "dense_vector": [float((start + index) % 7), 0.1, 0.2, 0.3],
        }
        for index in range(count)
    ]


async def _seed(client: OwnerClient) -> None:
    for start in range(0, NODE_COUNT, 500):
        batch = _nodes(
            "read", min(500, NODE_COUNT - start), start=start,
        )
        await client.mutate(f"seed-reads-{start}", {"upsert_nodes": batch}, kind="batch")


async def _owner_measure(root: Path) -> dict[str, Any]:  # noqa: C901, PLR0915
    owner = _spawn_owner(root)
    await _wait_owner(root)
    try:
        client = OwnerClient(root / "owner.sock")
        await _seed(client)
        reads: dict[str, Any] = {}
        for size in SIZES:
            durations: list[float] = []
            bytes_total = 0
            for _ in range(REPEATS):
                started = time.perf_counter()
                page = await client.query_nodes("TextUnit", limit=size)
                durations.append(time.perf_counter() - started)
                bytes_total += len(json.dumps(page))
            reads[str(size)] = {
                "latency": _stats(durations),
                "avg_response_kb": round(bytes_total / REPEATS / 1024, 1),
            }
        first = await client.query_nodes("TextUnit", limit=100)
        node_latencies = []
        for row in first["nodes"][:50]:
            started = time.perf_counter()
            await client.node(int(row["id"]))
            node_latencies.append(time.perf_counter() - started)
        reads["node_by_id"] = _stats(node_latencies)
        reads["count"] = _stats([
            await _count(client) for _ in range(20)
        ])

        mutation_baseline: list[float] = []
        for index in range(20):
            started = time.perf_counter()
            await client.mutate(
                f"write-base-{index}",
                {"upsert_nodes": _nodes("write-base", 1, start=index)},
                kind="batch",
            )
            mutation_baseline.append(time.perf_counter() - started)

        stop = asyncio.Event()

        async def reader() -> None:
            own = OwnerClient(root / "owner.sock")
            while not stop.is_set():
                await own.query_nodes("TextUnit", limit=100)
                await asyncio.sleep(0.001)

        readers = [asyncio.create_task(reader()) for _ in range(8)]
        mutation_loaded: list[float] = []
        try:
            for index in range(20):
                started = time.perf_counter()
                await client.mutate(
                    f"write-loaded-{index}",
                    {"upsert_nodes": _nodes("write-loaded", 1, start=index)},
                    kind="batch",
                )
                mutation_loaded.append(time.perf_counter() - started)
        finally:
            stop.set()
            await asyncio.gather(*readers, return_exceptions=True)

        concurrent: dict[str, Any] = {}
        for clients in CONCURRENCY:
            async def worker() -> None:
                own = OwnerClient(root / "owner.sock")
                for _ in range(10):
                    await own.query_nodes("TextUnit", limit=100)

            started = time.perf_counter()
            await asyncio.gather(*(worker() for _ in range(clients)))
            wall = time.perf_counter() - started
            concurrent[str(clients)] = {
                "queries": clients * 10,
                "wall_seconds": round(wall, 3),
                "queries_per_second": round(clients * 10 / wall, 1),
            }
        return {
            "reads": reads,
            "concurrent": concurrent,
            "write_under_read_load": {
                "baseline": _stats(mutation_baseline),
                "with_8_readers": _stats(mutation_loaded),
            },
        }
    finally:
        if owner.poll() is None:
            owner.send_signal(signal.SIGTERM)
        try:
            owner.wait(timeout=10)
        except subprocess.TimeoutExpired:
            owner.kill()


async def _count(client: OwnerClient) -> float:
    started = time.perf_counter()
    await client.count_nodes("TextUnit")
    return time.perf_counter() - started


def _local_measure(root: Path) -> dict[str, Any]:
    from app.services.overgraph.catalogs import open_catalog

    catalog = open_catalog(root / "catalog", kind="knowledge", dimension=DIMENSION)
    try:
        reads: dict[str, Any] = {}
        for size in SIZES:
            durations = []
            for _ in range(REPEATS):
                started = time.perf_counter()
                catalog.query_nodes(
                    label_filter={"labels": ["TextUnit"], "mode": "all"}, limit=size,
                )
                durations.append(time.perf_counter() - started)
            reads[str(size)] = _stats(durations)
        return reads
    finally:
        catalog.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default="")
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix="owner-read-bench-"))
    report = asyncio.run(_owner_measure(root))
    report["local_catalog"] = _local_measure(root)
    report["nodes"] = NODE_COUNT
    print(json.dumps(report, indent=2))
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
