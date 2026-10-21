"""Benchmark the full retrieval chain: Tantivy lexical, dense, fusion, hydration, hops.

Usage:
    uv run python scripts/benchmark_retrieval_chain.py [--facts N] [--iters N]
"""

from __future__ import annotations

import argparse
import shutil
import statistics
import tempfile
import time
from pathlib import Path

from app.services.knowledge.scope import customer_scope
from app.services.overgraph.catalogs import open_catalog
from app.services.overgraph.hybrid_retrieval import hybrid_fact_hits
from app.services.overgraph.neighbourhood import neighbourhood_facts
from app.services.overgraph.write import upsert_entity, write_fact
from app.services.graph_v2.types import FactInput, NodeInput
from app.services.tantivy_index import build_from_overgraph

CUSTOMER = 11
QUERY = "jämkning av oskäliga avtalsvillkor"
WORDS = (
    "avtalsvillkor", "uppsägningstid", "sekretessförpliktelse", "jämkning",
    "oskälighet", "hävdande", "bevisbörda", "skadestånd",
)


def _p(samples: list[float], q: float) -> float:
    return float(statistics.quantiles(samples, n=100, method="inclusive")[int(q * 100) - 1])


def _time(fn, iters: int) -> list[float]:
    samples: list[float] = []
    for _ in range(iters):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000.0)
    return samples


def _line(name: str, samples: list[float]) -> str:
    return f"{name:26} p50={statistics.median(samples):7.3f} ms  p95={_p(samples, 0.95):7.3f} ms"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts", type=int, default=200)
    parser.add_argument("--iters", type=int, default=100)
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix="retrieval-chain-bench-"))
    try:
        catalog = open_catalog(root / "knowledge", kind="knowledge", dimension=32)
        scope = customer_scope(CUSTOMER)
        seeds: list[str] = []
        for number in range(args.facts):
            word = WORDS[number % len(WORDS)]
            left = upsert_entity(catalog, NodeInput(
                node_type="core.concept", name=f"n{number}-a", scope=scope,
            )).key
            right = upsert_entity(catalog, NodeInput(
                node_type="core.concept", name=f"n{number}-b", scope=scope,
            )).key
            write_fact(
                catalog,
                FactInput(
                    source_id=left, target_id=right, scope=scope,
                    predicate="legal.rule",
                    fact_text=f"{word} regel nummer {number} om avtalsvillkor",
                    sources=(),
                    embedding=tuple(0.01 * ((number + i) % 7) for i in range(32)),
                ),
                key=f"fact-{number}",
            )
            if number < 40:
                seeds.append(left)

        index = build_from_overgraph(catalog, root / "index")
        chain = hybrid_fact_hits(
            catalog, index, customer_id=CUSTOMER, query=QUERY, limit=20,
            dense_query=[0.01] * 32,
        )
        assert chain, "chain returned no facts"

        print(f"facts={args.facts} iters={args.iters}")
        print(_line("tantivy lexical", _time(
            lambda: index.search_fact_keys(QUERY, tenant_ids=(f"customer:{CUSTOMER}",), limit=50),
            args.iters,
        )))
        print(_line("overgraph dense", _time(
            lambda: catalog.scoped_type_search(
                kind="Fact", customer_id=CUSTOMER, k=20, dense_query=[0.01] * 32, mode="dense",
            ),
            args.iters,
        )))
        print(_line("hybrid fusion+hydrate", _time(
            lambda: hybrid_fact_hits(
                catalog, index, customer_id=CUSTOMER, query=QUERY, limit=20,
                dense_query=[0.01] * 32,
            ),
            args.iters,
        )))
        from app.services.research.result_search import _graph_seeds, _question_seeds

        def research_seeds() -> int:
            collected = _graph_seeds(
                catalog, index, QUERY, CUSTOMER, vector=[0.01] * 32,
            )
            return len(_question_seeds(
                catalog, collected["endpoints"] + collected["dependencies"],
                f"customer:{CUSTOMER}",
            ))

        print(_line("research _seeds (integrated)", _time(research_seeds, args.iters)))
        print(_line("neighbourhood 2 hops", _time(
            lambda: neighbourhood_facts(
                catalog, customer_id=CUSTOMER, seeds=seeds, max_hops=2, limit=50,
            ),
            args.iters,
        )))
    finally:
        catalog.close()
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
