"""Compare never / always / dense-sparse disagreement at the same k. Retrieval only."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from overgraph_ingest.config import RetrievalConfig
from overgraph_ingest.coverage.run import _golds
from overgraph_ingest.graph.writer import GraphWriter, open_database, resolve_dimension
from overgraph_ingest.retrieval.decide import ALWAYS, DECISION_VARIANTS, NEVER, should_expand
from overgraph_ingest.retrieval.encode import LexicalSparseEncoder
from overgraph_ingest.retrieval.evaluate import evaluate_strategy, judge_units, metrics_payload
from overgraph_ingest.retrieval.expand import APPEND, BASELINE, expansion_for, load_expansions
from overgraph_ingest.retrieval.expand_run import _timed_rankings
from overgraph_ingest.retrieval.gold import RetrievalGold
from overgraph_ingest.retrieval.index import load_published_units
from overgraph_ingest.retrieval.run import _dense_encoder
from overgraph_ingest.retrieval.search import SearchHit
from overgraph_ingest.retrieval.stages import PIPELINE_STAGES

DEFAULT_K = 50
RESERVED_SPLITS = frozenset({"decision_held_out"})


@dataclass
class DecisionReport:
    payload: dict[str, object]


def run_expansion_decision(
    config: RetrievalConfig,
    *,
    gold_dir: Path | None = None,
    expansions_path: Path | None = None,
    k: int = DEFAULT_K,
) -> DecisionReport:
    golds = _golds(config.gold_path, gold_dir, include_held_out=True)
    expansions = load_expansions(expansions_path)
    dimension = resolve_dimension(config.db_path, config.dense_dimension)
    dense = _dense_encoder(config, dimension)
    sparse = LexicalSparseEncoder()
    started = time.perf_counter()
    db = open_database(config.db_path, dimension)
    try:
        writer = GraphWriter(db, batch_size=config.write_batch_size)
        units = load_published_units(writer)
        if any(unit.dense is None or unit.sparse is None for unit in units):
            raise RuntimeError("TextUnits are missing vectors; rerun with --embed")
        sparse.fit([unit.text for unit in units])
        gold_rows = []
        for gold in golds:
            expansion = expansion_for(gold, expansions)
            relevant, negatives, absent = judge_units(units, gold)
            queries = {
                BASELINE: gold.query,
                APPEND: expansion.append(gold.query),
            }
            timed = {
                name: _timed_rankings(text, units=units, dense=dense, sparse=sparse)
                for name, text in queries.items()
            }
            baseline_rankings = timed[BASELINE]["rankings"]
            append_rankings = timed[APPEND]["rankings"]
            expand = should_expand(
                "dense_sparse_disagree",
                baseline_rankings["dense"],
                baseline_rankings["sparse"],
            )
            chosen = append_rankings["hybrid"] if expand else baseline_rankings["hybrid"]
            policies = {
                NEVER: _policy_metrics(
                    baseline_rankings["hybrid"],
                    gold=gold,
                    relevant=relevant,
                    negatives=negatives,
                    absent=absent,
                    k=k,
                    expanded=False,
                ),
                ALWAYS: _policy_metrics(
                    append_rankings["hybrid"],
                    gold=gold,
                    relevant=relevant,
                    negatives=negatives,
                    absent=absent,
                    k=k,
                    expanded=True,
                ),
                "dense_sparse_disagree": _policy_metrics(
                    chosen,
                    gold=gold,
                    relevant=relevant,
                    negatives=negatives,
                    absent=absent,
                    k=k,
                    expanded=expand,
                ),
            }
            gold_rows.append(
                {
                    "gold_id": gold.id,
                    "split": gold.split,
                    "evaluation": (
                        "reserved" if gold.split in RESERVED_SPLITS else "diagnostic"
                    ),
                    "query": gold.query,
                    "expanded_query": queries[APPEND],
                    "rule_expanded": expand,
                    "relevant_units": len(relevant),
                    "relevant_documents": gold.relevant_documents,
                    "policies": policies,
                }
            )
        payload = {
            "operation": "representation",
            "experiment": "expansion_decision_v1",
            "pipeline_stages": list(PIPELINE_STAGES),
            "classify_unchanged": True,
            "default_retriever_unchanged": True,
            "rule": "dense_sparse_disagree",
            "rule_is_hypothesis": True,
            "verdict": "rejected",
            "do_not_tune_threshold_on_existing_golds": True,
            "decision_variants": list(DECISION_VARIANTS),
            "k": k,
            "dense_model": dense.model,
            "golds": gold_rows,
            "reserved": [row for row in gold_rows if row["evaluation"] == "reserved"],
            "diagnostic": [row["gold_id"] for row in gold_rows if row["evaluation"] == "diagnostic"],
            "wall_seconds": time.perf_counter() - started,
        }
    finally:
        db.close()
    return DecisionReport(payload=payload)


def _policy_metrics(
    ranked: list[SearchHit],
    *,
    gold: RetrievalGold,
    relevant: set[str],
    negatives: set[str],
    absent,
    k: int,
    expanded: bool,
) -> dict[str, object]:
    metrics = metrics_payload(
        evaluate_strategy(
            mode="expand",
            k=k,
            gold=gold,
            hits=ranked,
            exhaustive=ranked,
            relevant_keys=relevant,
            negative_keys=negatives,
            absent=absent,
        )
    )
    return {
        "expanded": expanded,
        "recall_at_k": metrics.get("recall"),
        "document_coverage_at_k": metrics.get("document_coverage"),
        "hard_negatives_in_topk": metrics.get("hard_negatives_in_topk"),
        "documents_found": metrics.get("documents_found"),
    }
