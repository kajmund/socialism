"""Isolated probe: which raw OverGraph operations tolerate parallel access?"""

from __future__ import annotations

import json
import statistics
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from overgraph import OverGraph

DIMENSION = 32
NODES = 1000
READS_PER_THREAD = 50


def _vector(index: int) -> list[float]:
    vector = [0.0] * DIMENSION
    vector[index % DIMENSION] = 1.0
    return vector


def _open(root: Path) -> OverGraph:
    return OverGraph.open(
        str(root / "catalog"), create_if_missing=True,
        dense_vector_dimension=DIMENSION, dense_vector_metric="cosine",
        wal_sync_mode="group_commit", edge_uniqueness=True,
    )


def _seed(db: OverGraph) -> None:
    for start in range(0, NODES, 100):
        rows = [{
            "labels": ["Fact", "scope.customer.1"], "key": f"f-{index}",
            "props": {"scope_key": "customer:1", "status": "active"},
            "dense_vector": _vector(index),
        } for index in range(start, min(NODES, start + 100))]
        db.batch_upsert_nodes(rows)


def _read_once(db: OverGraph, index: int) -> None:
    db.get_node_by_key("Fact", f"f-{index % NODES}")
    db.vector_search("dense", k=20, dense_query=_vector(index),
                     label_filter={"labels": ["Fact", "scope.customer.1"], "mode": "all"})


def _measure_reads(db: OverGraph, threads: int) -> dict:
    def worker(offset: int) -> list[float]:
        latencies = []
        for index in range(READS_PER_THREAD):
            started = time.perf_counter()
            _read_once(db, offset * READS_PER_THREAD + index)
            latencies.append(time.perf_counter() - started)
        return latencies

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=threads) as pool:
        results = list(pool.map(worker, range(threads)))
    wall = time.perf_counter() - started
    values = [value for rows in results for value in rows]
    ordered = sorted(values)
    return {
        "threads": threads,
        "reads": len(values),
        "wall_seconds": round(wall, 3),
        "p50": round(statistics.median(ordered), 5),
        "p95": round(ordered[int(0.95 * len(ordered)) - 1], 5),
        "max": round(ordered[-1], 5),
    }


def _read_write_probe(db: OverGraph) -> dict:
    errors: list[str] = []
    stop = threading.Event()

    def reader(offset: int) -> None:
        try:
            while not stop.is_set():
                _read_once(db, offset)
        except Exception as exc:  # noqa: BLE001 - probe records engine errors
            errors.append(f"reader: {type(exc).__name__}: {exc}")

    def writer() -> None:
        try:
            for index in range(200):
                db.upsert_node(
                    ["Fact", "scope.customer.1"], f"probe-write-{index}",
                    props={"scope_key": "customer:1", "status": "active"},
                    dense_vector=_vector(index),
                )
        except Exception as exc:  # noqa: BLE001 - probe records engine errors
            errors.append(f"writer: {type(exc).__name__}: {exc}")
        finally:
            stop.set()

    threads = [threading.Thread(target=reader, args=(index,)) for index in range(4)]
    writer_thread = threading.Thread(target=writer)
    for thread in threads:
        thread.start()
    writer_thread.start()
    writer_thread.join()
    for thread in threads:
        thread.join()
    return {"errors": errors, "write_nodes": 200}


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="overgraph-concurrency-"))
    db = _open(root)
    report = {}
    try:
        _seed(db)
        report["serial"] = _measure_reads(db, 1)
        report["parallel_4"] = _measure_reads(db, 4)
        report["parallel_8"] = _measure_reads(db, 8)
        report["read_write"] = _read_write_probe(db)
        report["node_count"] = db.count_nodes_by_labels(["Fact"])
    finally:
        db.close()
    print(json.dumps(report, indent=2))
    return 0 if all(not run["errors"] for run in [report["read_write"]]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
