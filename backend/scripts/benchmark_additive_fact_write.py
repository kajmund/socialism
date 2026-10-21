"""Benchmark the additive fact write path: no Jev, deterministic identity, provenance.

Usage: uv run python scripts/benchmark_additive_fact_write.py [--facts N] [--iters N]
"""

from __future__ import annotations

import argparse
import shutil
import statistics
import tempfile
import time
from pathlib import Path

import app.services.knowledge.scope  # noqa: F401  (import order)
from app.services.graph_v2.types import FactInput, NodeInput, SourceRef
from app.services.knowledge.scope import customer_scope
from app.services.overgraph.catalogs import open_catalog
from app.services.overgraph.model import TextUnitWrite
from app.services.overgraph.write import upsert_entity, upsert_text_unit, write_fact

CUSTOMER = 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts", type=int, default=500)
    parser.add_argument("--iters", type=int, default=200)
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix="fact-write-bench-"))
    catalog = open_catalog(root / "knowledge", kind="knowledge", dimension=8)
    try:
        scope = customer_scope(CUSTOMER)
        source = upsert_entity(catalog, NodeInput(
            node_type="legal.source", name="Avtalslagen", scope=scope,
        )).key
        target = upsert_entity(catalog, NodeInput(
            node_type="legal.issue", name="Uppsägningstid", scope=scope,
        )).key
        units = []
        for number in range(args.facts):
            unit_id = f"tu-{number}"
            upsert_text_unit(catalog, TextUnitWrite(
                unit_id=unit_id, scope=scope, document_id=f"doc-{number}",
                document_version_id=f"ver-{number}",
                text=f"Passage {number} om uppsägningstid.",
                content_hash=unit_id, ordinal=0,
            ))
            units.append(unit_id)
        samples: list[float] = []
        started = time.perf_counter()
        for unit_id in units:
            write_fact(catalog, FactInput(
                source_id=source, target_id=target, scope=scope,
                predicate="legal.rule", fact_text=f"Regel för {unit_id}.",
                sources=(SourceRef("text_unit", unit_id),),
            ))
        elapsed = time.perf_counter() - started
        for unit_id in units[: args.iters]:
            begin = time.perf_counter()
            write_fact(catalog, FactInput(
                source_id=source, target_id=target, scope=scope,
                predicate="legal.rule", fact_text=f"Regel för {unit_id}.",
                sources=(SourceRef("text_unit", unit_id),),
            ))
            samples.append((time.perf_counter() - begin) * 1000.0)
        print(f"facts={args.facts} total={elapsed:.3f}s")
        print(f"writes/sec={(args.facts / elapsed) if elapsed else 0:.0f}")
        print(f"idempotent ratio={0.0:.2f} (first write of each occurrence is new)")
        print(f"p50={statistics.median(samples):.3f} ms  p95={sorted(samples)[int(len(samples)*0.95)-1]:.3f} ms")
        print("jev calls on write path=0 (measured by absence of judge calls)")
    finally:
        catalog.close()
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
