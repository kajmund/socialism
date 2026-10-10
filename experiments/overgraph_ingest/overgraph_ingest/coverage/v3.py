"""Coverage v3: document budget curves and proof-kind stop. Classify unchanged."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from overgraph_ingest.config import RetrievalConfig
from overgraph_ingest.coverage.budget import budget_metrics, run_budget_controller
from overgraph_ingest.coverage.cache import CachedAnswer
from overgraph_ingest.coverage.run import _golds, _ranked_hits
from overgraph_ingest.coverage.v2 import DEFAULT_CACHE, _cache_for
from overgraph_ingest.graph.writer import GraphWriter, open_database, resolve_dimension
from overgraph_ingest.jev.candidates import load_graph_context
from overgraph_ingest.jev.client import HttpJevClient, JevClient
from overgraph_ingest.jev.questions import CLASSIFY_QUESTION
from overgraph_ingest.retrieval.encode import LexicalSparseEncoder
from overgraph_ingest.retrieval.evaluate import evaluate_strategy, judge_units
from overgraph_ingest.retrieval.expand import BASELINE, query_for
from overgraph_ingest.retrieval.run import _dense_encoder
from overgraph_ingest.retrieval.search import encode_query

DEFAULT_BUDGETS: tuple[int | None, ...] = (1, 2, 3, 5)


@dataclass
class CoverageV3Report:
    payload: dict[str, object]


def run_coverage_v3(
    config: RetrievalConfig,
    *,
    gold_dir: Path | None = None,
    client: JevClient | None = None,
    typesafe_api_key: str | None = None,
    typesafe_base_url: str = "https://api.typesafe.ai",
    jev_model: str = "jev-1.13.0",
    timeout_seconds: float = 8.0,
    concurrency: int = 8,
    global_k: int = 50,
    budgets: tuple[int | None, ...] = DEFAULT_BUDGETS,
    cache_root: Path | None = None,
    scorer: str = "hybrid",
    query_variant: str = BASELINE,
    gold_ids: tuple[str, ...] | None = None,
) -> CoverageV3Report:
    golds = _golds(config.gold_path, gold_dir)
    if gold_ids:
        wanted = set(gold_ids)
        golds = [gold for gold in golds if gold.id in wanted]
        if not golds:
            raise ValueError(f"no golds matched {gold_ids}")
    dimension = resolve_dimension(config.db_path, config.dense_dimension)
    dense = _dense_encoder(config, dimension)
    sparse = LexicalSparseEncoder()
    jev = client or HttpJevClient(api_key=typesafe_api_key or "", base_url=typesafe_base_url)
    started = time.perf_counter()
    db = open_database(config.db_path, dimension)
    try:
        writer = GraphWriter(db, batch_size=config.write_batch_size)
        context = load_graph_context(writer)
        if any(unit.dense is None or unit.sparse is None for unit in context.units):
            raise RuntimeError("TextUnits are missing vectors; rerun with --embed")
        sparse.fit([unit.text for unit in context.units])
        gold_rows: list[dict[str, object]] = []
        for gold in golds:
            gold_started = time.perf_counter()
            query = query_for(gold, query_variant)
            dense_query, sparse_query = encode_query(query, dense=dense, sparse=sparse)
            ranked = _ranked_hits(context.units, scorer, dense_query, sparse_query)
            ranking = _ranking_snapshot(ranked, gold, context.units)
            cache = _cache_for(gold.id, cache_root)
            question = gold.classify_question or CLASSIFY_QUESTION
            budget_rows: list[dict[str, object]] = []
            matched_at: dict[str, object] | None = None
            for budget in budgets:
                result = run_budget_controller(
                    ranked=ranked,
                    context=context,
                    gold=gold,
                    client=jev,
                    cache=cache,
                    question=question,
                    model=jev_model,
                    timeout_seconds=timeout_seconds,
                    concurrency=concurrency,
                    global_k=global_k,
                    budget=budget,
                )
                for judged in result.judgments:
                    cache.setdefault(
                        judged.key,
                        CachedAnswer(judged.predicted, judged.confidence, "v3-live"),
                    )
                payload = budget_metrics(result, gold, budget=budget)
                payload["wall_seconds"] = time.perf_counter() - gold_started
                budget_rows.append(payload)
                if payload["matched_v2_recall"] and matched_at is None:
                    matched_at = {
                        "budget": budget,
                        "classified": payload["classified"],
                        "jev_calls": payload["jev_calls"],
                        "jev_yes_document_recall": payload["jev_yes_document_recall"],
                    }
            gold_rows.append(
                {
                    "gold_id": gold.id,
                    "query": gold.query,
                    "query_used": query,
                    "query_variant": query_variant,
                    "proof_kind": gold.proof_kind,
                    "recall_at_50": ranking["recall_at_50"],
                    "document_coverage_at_50": ranking["document_coverage_at_50"],
                    "relevant_documents": gold.relevant_documents,
                    "budgets": budget_rows,
                    "matched_v2_at": matched_at,
                }
            )
        payload = {
            "operation": "coverage",
            "controller": "deterministic_v3",
            "classify_unchanged": True,
            "verified_absent_requires_absence_and_all_units": True,
            "budget_exhausted_is_not_absent": True,
            "scorer": scorer,
            "query_variant": query_variant,
            "default_retriever_unchanged": True,
            "global_k": global_k,
            "budgets": ["inf" if item is None else item for item in budgets],
            "jev_model": jev_model,
            "concurrency": concurrency,
            "cache_files": {key: str(path) for key, path in DEFAULT_CACHE.items()},
            "golds": gold_rows,
            "wall_seconds": time.perf_counter() - started,
        }
    finally:
        db.close()
    return CoverageV3Report(payload=payload)


def _ranking_snapshot(ranked, gold, units) -> dict[str, float]:
    relevant, negatives, absent = judge_units(units, gold)
    metrics = evaluate_strategy(
        mode="coverage",
        k=50,
        gold=gold,
        hits=ranked,
        exhaustive=ranked,
        relevant_keys=relevant,
        negative_keys=negatives,
        absent=absent,
    )
    return {
        "recall_at_50": metrics.recall,
        "document_coverage_at_50": metrics.document_coverage,
    }
