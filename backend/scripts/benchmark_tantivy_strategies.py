"""Inventory benchmark for derived Tantivy index strategies A-D.

Compares a per-backend lexical index, a co-located owner index, an isolated
index process and Overgraph-only retrieval on the same synthetic corpus with
known relevance. No production code is changed.
"""

from __future__ import annotations

import asyncio
import json
import math
import resource
import shutil
import statistics
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import os
for _key in ("CEREBRAS_API_KEY", "OPENAI_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"):
    os.environ.setdefault(_key, "test-key")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import app.main  # noqa: E402,F401 - resolve the app import graph first

from app.services.overgraph.catalogs import open_catalog  # noqa: E402
from app.services.overgraph.labels import FACT, scope_label  # noqa: E402
from app.services.overgraph.owner import OvergraphOwner, OwnerClient  # noqa: E402
from app.services.overgraph.research import search_research_facts  # noqa: E402
from app.services.tantivy_index import (  # noqa: E402
    TextUnitIndex,
    build_from_overgraph,
    pending_updates,
    read_watermark,
    reconcile,
)

DIMENSION = 32
CATEGORIES = ("uppsagning", "semester", "lon", "arbetstid", "diskriminering")
SYNONYMS = {
    "uppsagning": "avslutning", "semester": "ledighet", "lon": "ersattning",
    "arbetstid": "schematid", "diskriminering": "sarkillnad",
}
PER_CATEGORY = 40
QUERIES = CATEGORIES


def _vector(category: int) -> list[float]:
    vector = [0.0] * DIMENSION
    vector[category] = 1.0
    return vector


def _facts() -> list[dict[str, Any]]:
    rows = []
    for category_index, category in enumerate(CATEGORIES):
        for index in range(PER_CATEGORY):
            key = f"fact-{category}-{index}"
            lexical = category if index % 2 == 0 else SYNONYMS[category]
            rows.append({
                "labels": [FACT, scope_label("customer:1")],
                "key": key,
                "props": {
                    "scope_key": "customer:1", "status": "active",
                    "predicate": "legal.rule",
                    "normalized_text": f"{lexical} regel {index} avser {lexical} undantag",
                    "source_key": f"src-{category}-{index}",
                    "target_key": f"dst-{category}-{index}",
                    "fact_text": f"{category} regel {index}",
                    "attributes_json": "{}", "source_refs_json": "[]",
                    "created_at_ms": index,
                },
                "dense_vector": _vector(category_index),
            })
    return rows


def _seed(catalog, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        catalog.upsert_node(
            row["labels"], row["key"], props=row["props"],
            dense_vector=row["dense_vector"],
        )


def _stats(values: list[float]) -> dict[str, Any]:
    ordered = sorted(values)
    if not ordered:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0, "n": 0}

    def pct(share: float) -> float:
        return round(ordered[max(0, int(share * len(ordered)) - 1)], 6)

    return {
        "p50": round(statistics.median(ordered), 6),
        "p95": pct(0.95), "p99": pct(0.99),
        "max": round(ordered[-1], 6), "n": len(ordered),
    }


def _relevance(category: str) -> set[str]:
    return {f"fact-{category}-{index}" for index in range(PER_CATEGORY)}


def _recall(ids: list[str], relevant: set[str], k: int) -> float:
    return len(set(ids[:k]) & relevant) / len(relevant) if relevant else 0.0


def _ndcg(ids: list[str], relevant: set[str], k: int) -> float:
    gains = [1.0 if key in relevant else 0.0 for key in ids[:k]]
    dcg = sum(gain / math.log2(position + 2) for position, gain in enumerate(gains))
    ideal = sum(1 / math.log2(position + 2) for position in range(min(len(relevant), k)))
    return dcg / ideal if ideal else 0.0


def _lexical(index: TextUnitIndex, query: str) -> list[str]:
    return [
        hit.key for hit in index.search_fact_keys(
            query, tenant_ids=("customer:1",), limit=50,
        )
    ]


def _dense(catalog, query: str) -> list[str]:
    hits = search_research_facts(
        catalog, 1, _vector(CATEGORIES.index(query)), 50,
    )
    return [hit.fact.id for hit in hits]


def _hybrid(catalog, index: TextUnitIndex, query: str) -> list[str]:
    from app.services.overgraph.hybrid_retrieval import hybrid_fact_hits

    hits = hybrid_fact_hits(
        catalog, index, customer_id=1, query=query, limit=50,
        dense_query=_vector(CATEGORIES.index(query)),
    )
    return [hit.fact.id for hit in hits]


def _quality(ids: list[str], category: str) -> dict[str, float]:
    relevant = _relevance(category)
    return {
        "recall_at_20": _recall(ids, relevant, 20),
        "recall_at_50": _recall(ids, relevant, 50),
        "ndcg_at_20": _ndcg(ids, relevant, 20),
    }


def _build_and_search(root: Path, catalog) -> dict[str, Any]:
    index_dir = root / "tantivy"
    started = time.perf_counter()
    index = build_from_overgraph(catalog, index_dir)
    build_seconds = time.perf_counter() - started
    index_size = sum(path.stat().st_size for path in index_dir.rglob("*") if path.is_file())
    quality = {}
    latency = {"lexical": [], "dense": [], "hybrid": []}
    for query in QUERIES:
        for _ in range(5):
            started = time.perf_counter()
            lexical = _lexical(index, query)
            latency["lexical"].append(time.perf_counter() - started)
            started = time.perf_counter()
            dense = _dense(catalog, query)
            latency["dense"].append(time.perf_counter() - started)
            started = time.perf_counter()
            hybrid = _hybrid(catalog, index, query)
            latency["hybrid"].append(time.perf_counter() - started)
        quality[query] = {
            "lexical": _quality(lexical, query),
            "dense": _quality(dense, query),
            "hybrid": _quality(hybrid, query),
        }
    return {
        "build_seconds": round(build_seconds, 3),
        "index_size_kb": round(index_size / 1024, 1),
        "quality": quality,
        "latency": {name: _stats(values) for name, values in latency.items()},
        "index": index,
        "dir": index_dir,
    }


def _update_and_delete(catalog, index: TextUnitIndex, root: Path) -> dict[str, Any]:
    watermark = read_watermark(root / "tantivy")
    added = [{
        "labels": [FACT, scope_label("customer:1")],
        "key": f"fact-new-{index}",
        "props": {
            "scope_key": "customer:1", "status": "active",
            "normalized_text": "uppsagning ny regel", "created_at_ms": 1000 + index,
        },
        "dense_vector": _vector(0),
    } for index in range(20)]
    for row in added:
        catalog.upsert_node(
            row["labels"], row["key"], props=row["props"],
            dense_vector=row["dense_vector"],
        )
    pending = pending_updates(catalog, watermark_ms=watermark)
    started = time.perf_counter()
    reconcile(catalog, index, watermark_ms=watermark)
    reconcile_seconds = time.perf_counter() - started
    found_new = {hit.key for hit in index.search_fact_keys(
        "uppsagning ny", tenant_ids=("customer:1",), limit=50,
    )}

    stale_key = added[0]["key"]
    row = catalog.get_by_key(FACT, stale_key)
    if row is not None and row.engine_id is not None:
        catalog.delete_node(row.engine_id)
    started = time.perf_counter()
    reconcile(catalog, index, watermark_ms=read_watermark(root / "tantivy"))
    delete_reconcile_seconds = time.perf_counter() - started
    still_present = stale_key in {hit.key for hit in index.search_fact_keys(
        "uppsagning ny", tenant_ids=("customer:1",), limit=50,
    )}
    started = time.perf_counter()
    index.delete_keys((stale_key,))
    manual_delete_seconds = time.perf_counter() - started
    after_manual = stale_key in {hit.key for hit in index.search_fact_keys(
        "uppsagning ny", tenant_ids=("customer:1",), limit=50,
    )}
    return {
        "pending_after_ingest": pending,
        "reconcile_seconds": round(reconcile_seconds, 4),
        "found_new_after_reconcile": bool(found_new & {node["key"] for node in added}),
        "delete_seen_by_reconcile": still_present,
        "delete_reconcile_seconds": round(delete_reconcile_seconds, 4),
        "manual_delete_seconds": round(manual_delete_seconds, 4),
        "delete_seen_after_manual": after_manual,
    }


async def _mutation_impact(catalog, index: TextUnitIndex) -> dict[str, Any]:
    owner = OvergraphOwner(
        Path(tempfile.mkdtemp(prefix="tantivy-owner-")) / "catalog",
        dimension=DIMENSION,
        socket_path=Path(tempfile.mkdtemp(prefix="tantivy-sock-")) / "owner.sock",
    )
    await owner.start()
    client = OwnerClient(owner.socket_path, catalog_id=owner.catalog_id)
    try:
        async def mutations(prefix: str) -> list[float]:
            samples = []
            for number in range(100):
                started = time.perf_counter()
                await client.mutate(f"{prefix}-{number}", {"upsert_nodes": [{
                    "labels": [FACT, scope_label("customer:1")],
                    "key": f"{prefix}-{number}",
                    "props": {"scope_key": "customer:1", "status": "active"},
                }]}, kind="batch")
                samples.append(time.perf_counter() - started)
            return samples

        baseline = await mutations("baseline")
        stop = False

        def searcher() -> None:
            while not stop:
                _lexical(index, "uppsagning")
                _dense(catalog, "uppsagning")
                _hybrid(catalog, index, "uppsagning")

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(searcher) for _ in range(4)]
            loaded = await mutations("loaded")
            stop = True
            for future in futures:
                future.result(timeout=5)
        return {"baseline": _stats(baseline), "with_index_searches": _stats(loaded)}
    finally:
        await owner.close()


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="tantivy-strategies-"))
    catalog = open_catalog(root / "catalog", kind="knowledge", dimension=DIMENSION)
    try:
        _seed(catalog, _facts())
        result = _build_and_search(root, catalog)
        index = result.pop("index")
        result["update"] = _update_and_delete(catalog, index, root)
        result["mutation_impact"] = asyncio.run(_mutation_impact(catalog, index))
        rss_raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        divisor = 1024 * 1024 if __import__("platform").system() == "Darwin" else 1024
        result["rss_mb"] = round(rss_raw / divisor, 1)
        print(json.dumps(result, indent=2, default=str))
    finally:
        catalog.close()
        shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
