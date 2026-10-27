"""Owner graph retrieval: quality parity, latency, transport and write impact."""

from __future__ import annotations

import asyncio
import json
import math
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

for _key in ("CEREBRAS_API_KEY", "OPENAI_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"):
    import os

    os.environ.setdefault(_key, "test-key")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import app.main  # noqa: E402,F401 - resolve the app import graph first

from app.services.overgraph.catalogs import open_catalog  # noqa: E402
from app.services.overgraph.labels import FACT, scope_label  # noqa: E402
from app.services.overgraph.owner import OwnerClient  # noqa: E402
from app.services.overgraph.research import collect_research_hits  # noqa: E402
from app.services.overgraph.research_owner import collect_research_hits_via_owner  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
DIMENSION = 32
GROUPS = 10
PER_GROUP = 100
QUERIES = 10
REPEATS = 5
BOUND = 20


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
            "key": f"retrieval-fact-{index}",
            "props": {
                "scope_key": "customer:1", "predicate": "legal.rule",
                "status": "active",
                "source_key": f"missing-src-{group}",
                "target_key": f"missing-target-{group}",
                "fact_text": f"fact {index}", "attributes_json": "{}",
                "source_refs_json": "[]", "created_at_ms": index,
            },
            "dense_vector": vector,
        })
    return rows


def _stats(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    def pct(share: float) -> float:
        return ordered[max(0, math.ceil(share * len(ordered)) - 1)]
    return {
        "p50": round(statistics.median(ordered), 5),
        "p95": round(pct(0.95), 5),
        "p99": round(pct(0.99), 5),
        "max": round(ordered[-1], 5),
        "n": len(ordered),
    }


def _spawn(root: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable, "-m", "app.services.overgraph.owner",
            str(root / "catalog"), "--socket", str(root / "owner.sock"),
            "--dimension", str(DIMENSION), "--no-sync",
        ],
        cwd=BACKEND, stdout=subprocess.DEVNULL, stderr=None, text=True,
    )


async def _start(root: Path) -> tuple[subprocess.Popen[str], OwnerClient]:
    process = _spawn(root)
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


def _recall_at(ids: list[str], relevant: set[str], k: int) -> float:
    return len(set(ids[:k]) & relevant) / len(relevant) if relevant else 0.0


def _ndcg_at(ids: list[str], relevant: set[str], k: int) -> float:
    gains = [1.0 if key in relevant else 0.0 for key in ids[:k]]
    dcg = sum(gain / math.log2(position + 2) for position, gain in enumerate(gains))
    ideal = sum(1 / math.log2(position + 2) for position in range(min(len(relevant), k)))
    return dcg / ideal if ideal else 0.0


def _quality(ids: list[str], group: int) -> dict[str, float]:
    relevant = {
        f"retrieval-fact-{group + position * GROUPS}"
        for position in range(10)
    }
    return {
        "recall_at_20": _recall_at(ids, relevant, 20),
        "recall_at_50": _recall_at(ids, relevant, 50),
        "ndcg_at_20": _ndcg_at(ids, relevant, 20),
    }


async def _owner_measure(root: Path) -> dict[str, Any]:  # noqa: PLR0915
    process, client = await _start(root)
    try:
        rows = _rows()
        for start in range(0, len(rows), 100):
            await client.mutate(f"seed-retrieval-{start}", {
                "upsert_nodes": rows[start:start + 100],
            }, kind="batch")
        durations: list[float] = []
        read_ops = read_bytes = 0
        quality = {}
        for group in range(QUERIES):
            query = [0.0] * DIMENSION
            query[group % GROUPS] = 1.0
            for _ in range(REPEATS):
                before = (await client.health())["metrics"]
                started = time.perf_counter()
                hits = await collect_research_hits_via_owner(
                    client, customer_id=1, question_id=None,
                    dense_query=query, bound=BOUND,
                )
                durations.append(time.perf_counter() - started)
                after = (await client.health())["metrics"]
                read_ops += after["read_ops"] - before["read_ops"]
                read_bytes += after["read_bytes"] - before["read_bytes"]
                ids = [hit.fact.id for hit in hits]
                if group in quality:
                    assert quality[group]["ids"] == ids
                else:
                    quality[group] = {"ids": ids, **_quality(ids, group % GROUPS)}

        baseline_metrics = (await client.health())["metrics"]
        baseline = []
        for index in range(20):
            started = time.perf_counter()
            await client.mutate(f"write-base-{index}", {
                "upsert_nodes": [_rows()[0] | {"key": f"write-base-{index}"}],
            }, kind="batch")
            baseline.append(time.perf_counter() - started)
        after_baseline = (await client.health())["metrics"]
        baseline_queue = after_baseline["queue_wait_seconds"][
            len(baseline_metrics["queue_wait_seconds"]):
        ]

        stop = asyncio.Event()

        async def reader() -> None:
            query = [0.0] * DIMENSION
            query[0] = 1.0
            while not stop.is_set():
                await collect_research_hits_via_owner(
                    client, customer_id=1, question_id=None,
                    dense_query=query, bound=BOUND,
                )

        readers = [asyncio.create_task(reader()) for _ in range(8)]
        loaded = []
        try:
            for index in range(20):
                started = time.perf_counter()
                await client.mutate(f"write-loaded-{index}", {
                    "upsert_nodes": [_rows()[0] | {"key": f"write-loaded-{index}"}],
                }, kind="batch")
                loaded.append(time.perf_counter() - started)
        finally:
            stop.set()
            await asyncio.gather(*readers, return_exceptions=True)
        after_loaded = (await client.health())["metrics"]
        loaded_queue = after_loaded["queue_wait_seconds"][
            len(after_baseline["queue_wait_seconds"]):
        ]
        return {
            "latency": _stats(durations),
            "read_ops": round(read_ops / (QUERIES * REPEATS), 2),
            "read_bytes": round(read_bytes / (QUERIES * REPEATS), 1),
            "quality": {
                str(group): {key: value for key, value in row.items() if key != "ids"}
                for group, row in quality.items()
            },
            "write_under_read_load": {
                "baseline": _stats(baseline),
                "with_8_readers": _stats(loaded),
                "queue_wait_baseline": _stats(baseline_queue),
                "queue_wait_with_8_readers": _stats(loaded_queue),
            },
        }
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def _local_measure(root: Path) -> dict[str, Any]:
    catalog = open_catalog(root / "catalog", kind="knowledge", dimension=DIMENSION)
    try:
        durations = []
        for group in range(QUERIES):
            query = [0.0] * DIMENSION
            query[group % GROUPS] = 1.0
            for _ in range(REPEATS):
                started = time.perf_counter()
                collect_research_hits(
                    catalog, customer_id=1, question_id=None,
                    dense_query=query, bound=BOUND,
                )
                durations.append(time.perf_counter() - started)
        return {"latency": _stats(durations)}
    finally:
        catalog.close()


async def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="owner-retrieval-bench-"))
    owner = await _owner_measure(root)
    owner["local"] = _local_measure(root)
    print(json.dumps(owner, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
