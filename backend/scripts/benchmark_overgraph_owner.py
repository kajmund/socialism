"""Measure owner RPC/batch overhead against direct Overgraph graph_patch."""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
from pathlib import Path

from app.services.overgraph.catalogs import open_catalog
from app.services.overgraph.owner import OvergraphOwner, OwnerClient

SIZES = (1, 100, 1000)
REPEATS = 3


def _nodes(prefix: str, count: int) -> list[dict]:
    return [
        {"labels": ["TextUnit", "bench"], "key": f"{prefix}-{index}", "props": {"text": str(index), "content_hash": str(index)}}
        for index in range(count)
    ]


async def _owner_time(socket_path: Path, size: int) -> dict:
    client = OwnerClient(socket_path)
    durations = []
    for repeat in range(REPEATS):
        nodes = _nodes(f"owner-{size}-{repeat}", size)
        started = time.perf_counter()
        result = await client.mutate(f"owner-{size}-{repeat}", {
            "generation": {"label": "Generation", "key": "scope", "prop": "generation"},
            "upsert_nodes": nodes,
        }, kind="batch")
        durations.append(time.perf_counter() - started)
        if not result.get("ok"):
            raise RuntimeError(result)
    noop_started = time.perf_counter()
    await client.mutate("owner-noop", {
        "generation": {"label": "Generation", "key": "scope", "prop": "generation"},
        "upsert_nodes": _nodes("owner-0-0", size),
    }, kind="batch")
    noop = time.perf_counter() - noop_started
    return {"durations": durations, "noop_seconds": noop}


def _direct_time(path: Path, size: int) -> list[float]:
    catalog = open_catalog(path, kind="knowledge", dimension=4)
    try:
        durations = []
        for repeat in range(REPEATS):
            started = time.perf_counter()
            catalog.graph_patch(upsert_nodes=_nodes(f"direct-{size}-{repeat}", size))
            durations.append(time.perf_counter() - started)
        return durations
    finally:
        catalog.close()


def _stats(values: list[float]) -> dict:
    values = sorted(values)
    return {
        "p50": round(values[len(values) // 2], 4),
        "p95": round(values[min(len(values) - 1, int(len(values) * 0.95))], 4),
        "min": round(values[0], 4),
    }


async def run() -> dict:
    root = Path(tempfile.mkdtemp(prefix="owner-bench-"))
    socket_path = root / "owner.sock"
    owner = OvergraphOwner(root / "owner-catalog", dimension=4, socket_path=socket_path)
    await owner.start()
    try:
        await OwnerClient(socket_path).mutate("seed-gen", {
            "upsert_nodes": [{"labels": ["Generation"], "key": "scope", "props": {"generation": 0}}]
        })
        result = {}
        for size in SIZES:
            owner_times = await _owner_time(socket_path, size)
            direct_times = _direct_time(root / f"direct-{size}", size)
            result[str(size)] = {
                "direct": _stats(direct_times),
                "owner": _stats(owner_times["durations"]),
                "owner_noop": round(owner_times["noop_seconds"], 4),
            }
        return result
    finally:
        await owner.close()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run()), indent=2))
