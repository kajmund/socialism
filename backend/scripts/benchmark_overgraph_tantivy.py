"""Benchmark the OverGraph + Tantivy primitives (proposed architecture, §10).

Measures warm latency/throughput of the authoritative exact lookup and the
derived fulltext index on a synthetic corpus, plus index rebuild, reconcile and
disk footprint. Read-only: uses a temp directory, no production data.

Usage:
    uv run python scripts/benchmark_overgraph_tantivy.py [--units N] [--claims N] [--queries N]
"""

from __future__ import annotations

import argparse
import shutil
import statistics
import tempfile
import time
from pathlib import Path

from app.services.knowledge.scope import shared_scope
from app.services.overgraph.catalogs import open_catalog
from app.services.overgraph.claims import find_claims, find_claims_by_class
from app.services.overgraph.labels import CLAIM, TEXT_UNIT, scope_label
from app.services.tantivy_index import (
    build_from_overgraph,
    reconcile,
)


def _latency_ms(fn, iters: int) -> list[float]:
    samples: list[float] = []
    for _ in range(iters):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000.0)
    return samples


def _p(samples: list[float], q: float) -> float:
    return float(statistics.quantiles(samples, n=100, method="inclusive")[int(q * 100) - 1])


def _dir_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--units", type=int, default=5000)
    parser.add_argument("--claims", type=int, default=5000)
    parser.add_argument("--queries", type=int, default=200)
    parser.add_argument("--dim", type=int, default=16)
    args = parser.parse_args()

    root = Path(tempfile.mkdtemp(prefix="bench-og-tantivy-"))
    catalog = open_catalog(root / "knowledge", kind="knowledge", dimension=args.dim)
    scope = shared_scope()

    seed_start = time.perf_counter()
    for i in range(args.units):
        catalog.upsert_node(
            [TEXT_UNIT, scope_label("shared")],
            f"tu-{i}",
            props={
                "scope_key": "shared",
                "document_id": f"doc-{i % 100}",
                "document_version_id": f"ver-{i % 100}",
                "section_id": "",
                "content_hash": f"hash-{i}",
                "text": f"Sekretessklausul nummer {i} i avtalet.",
            },
        )
    for i in range(args.claims):
        catalog.upsert_node(
            [CLAIM, scope_label("shared")],
            f"claim-{i}",
            props={
                "scope_key": "shared",
                "class_id": f"class-{i % 20}",
                "value": i % 2 == 0,
                "document_id": f"doc-{i % 100}",
                "document_version_id": f"ver-{i % 100}",
                "polarity": "positive",
                "taxonomy_version": "v1",
            },
        )
    seed_seconds = time.perf_counter() - seed_start

    build_start = time.perf_counter()
    index = build_from_overgraph(catalog, root / "idx")
    build_seconds = time.perf_counter() - build_start

    lookup = _latency_ms(
        lambda: find_claims(
            catalog, scope=scope, class_id="class-3", value=True, limit=100,
        ),
        args.queries,
    )
    lookup_by_class = _latency_ms(
        lambda: find_claims_by_class(catalog, scope=scope, class_id="class-3", limit=100),
        args.queries,
    )
    fulltext = _latency_ms(
        lambda: index.search("sekretess", tenant_ids=("shared",), limit=100),
        args.queries,
    )

    reconcile_start = time.perf_counter()
    reconcile(catalog, index, watermark_ms=0)
    reconcile_seconds = time.perf_counter() - reconcile_start

    catalog_bytes = _dir_bytes(root / "knowledge")
    index_bytes = _dir_bytes(root / "idx")

    def row(name: str, value: str) -> None:
        print(f"{name:42s} {value}")

    print(f"corpus: {args.units} TextUnits, {args.claims} claims, dim={args.dim}")
    print("-" * 60)
    row("seed graph writes", f"{seed_seconds:.2f} s ({args.units + args.claims} nodes)")
    row("fulltext index rebuild", f"{build_seconds:.3f} s")
    row("reconcile (full, watermark=0)", f"{reconcile_seconds:.3f} s")
    row("exact lookup (class_id AND value)", f"p50 {_p(lookup, 0.5):.3f} ms  p95 {_p(lookup, 0.95):.3f} ms")
    row("exact lookup (class_id only)", f"p50 {_p(lookup_by_class, 0.5):.3f} ms  p95 {_p(lookup_by_class, 0.95):.3f} ms")
    row("fulltext BM25 (warm)", f"p50 {_p(fulltext, 0.5):.3f} ms  p95 {_p(fulltext, 0.95):.3f} ms")
    row("disk: OverGraph catalog", f"{catalog_bytes / 1024:.1f} KiB")
    row("disk: Tantivy index", f"{index_bytes / 1024:.1f} KiB")

    shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
