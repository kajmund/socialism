"""Retrieve top-k, then one Cerebras call per gold. No controller. No Jev."""

from __future__ import annotations

import json
import time
from pathlib import Path

from overgraph_ingest.cerebras.client import CerebrasClient, Completer
from overgraph_ingest.cerebras.evaluate import relevant_documents, relevant_keys, score_rerank
from overgraph_ingest.cerebras.prompt import (
    TASK,
    build_messages,
    candidates_from_hits,
    parse_judgments,
)
from overgraph_ingest.config import RetrievalConfig
from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE
from overgraph_ingest.coverage.run import _golds, _ranked_hits
from overgraph_ingest.graph.writer import GraphWriter, open_database, resolve_dimension
from overgraph_ingest.jev.candidates import load_graph_context
from overgraph_ingest.retrieval.encode import LexicalSparseEncoder
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION
from overgraph_ingest.retrieval.run import _dense_encoder
from overgraph_ingest.retrieval.search import encode_query

ROOT = Path(__file__).resolve().parents[2]
CEREBRAS_ID = "phase2-cerebras-rerank-v1"
CEREBRAS_PATH = ROOT / "baselines" / f"{CEREBRAS_ID}.json"
DEFAULT_DB = ROOT / "data" / "extra-overgraph-phase2"
DEFAULT_GOLD_DIR = ROOT / "retrieval_gold"
DEFAULT_K = 50
DEFAULT_MODEL = "gpt-oss-120b"
DEFAULT_BASE_URL = "https://api.cerebras.ai/v1"


def run_cerebras_rerank(
    *,
    db_path: Path | None = None,
    gold_dir: Path | None = None,
    dense_dimension: int = 3072,
    k: int = DEFAULT_K,
    openai_api_key: str | None = None,
    openai_base_url: str | None = None,
    dense_model: str = "text-embedding-3-large",
    cerebras_api_key: str | None = None,
    cerebras_base_url: str = DEFAULT_BASE_URL,
    cerebras_model: str = DEFAULT_MODEL,
    client: Completer | None = None,
) -> dict[str, object]:
    golds = _golds(None, gold_dir or DEFAULT_GOLD_DIR)
    if not golds:
        raise ValueError("no seen golds")
    target = db_path or DEFAULT_DB
    dimension = resolve_dimension(target, dense_dimension)
    config = RetrievalConfig(
        db_path=target,
        dense_dimension=dimension,
        dense_model=dense_model,
        openai_api_key=openai_api_key,
        openai_base_url=openai_base_url,
    )
    started = time.perf_counter()
    db = open_database(target, dimension)
    try:
        units = load_graph_context(GraphWriter(db, batch_size=500)).units
    finally:
        db.close()
    if any(unit.dense is None or unit.sparse is None for unit in units):
        raise RuntimeError("TextUnits are missing vectors; rerun with --embed")
    dense = _dense_encoder(config, dimension)
    sparse = LexicalSparseEncoder()
    sparse.fit([unit.text for unit in units])
    completer = client or CerebrasClient(
        api_key=cerebras_api_key or "",
        base_url=cerebras_base_url,
        model=cerebras_model,
    )
    rows: list[dict[str, object]] = []
    for gold in golds:
        gold_started = time.perf_counter()
        dense_query, sparse_query = encode_query(gold.query, dense=dense, sparse=sparse)
        ranked = _ranked_hits(units, "hybrid", dense_query, sparse_query)[:k]
        retrieval_seconds = time.perf_counter() - gold_started
        candidates = candidates_from_hits(ranked)
        messages = build_messages(gold.query, candidates)
        reply = completer.complete(messages)
        parsed = parse_judgments(json.loads(reply.text), candidates)
        corpus_keys = relevant_keys(units, gold)
        corpus_docs = relevant_documents(units, gold, corpus_keys)
        metrics = score_rerank(
            gold=gold,
            candidates=candidates,
            judgments=parsed,
            corpus_relevant_keys=corpus_keys,
            corpus_relevant_docs=corpus_docs,
        )
        metrics["query"] = gold.query
        metrics["retrieval_seconds"] = retrieval_seconds
        metrics["ttft_seconds"] = reply.ttft_seconds
        metrics["model_seconds"] = reply.completion_seconds
        metrics["wall_seconds"] = time.perf_counter() - gold_started
        metrics["prompt_tokens"] = reply.prompt_tokens
        metrics["completion_tokens"] = reply.completion_tokens
        metrics["cost_usd"] = None
        metrics["judgments"] = [
            {
                "id": row.short_id,
                "key": row.key,
                "label": row.label,
                "reason": row.reason,
            }
            for row in parsed
        ]
        rows.append(metrics)
    return {
        "operation": "rerank",
        "experiment": "cerebras_rerank_v1",
        "task": TASK,
        "applied_to_v3": False,
        "no_new_jev": True,
        "no_coverage_controller": True,
        "no_proof_evaluator": True,
        "no_graph_traversal": True,
        "no_agent": True,
        "one_call_per_question": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "uncertain_is_not_match": True,
        "same_mapping": GOLD_MAP_VERSION,
        "quality_reference": QUALITY_REFERENCE,
        "scorer": "hybrid",
        "k": k,
        "model": cerebras_model,
        "golds": rows,
        "wall_seconds": time.perf_counter() - started,
        "summary": _summary(rows),
    }


def freeze_cerebras_rerank(payload: dict[str, object] | None = None) -> dict[str, object]:
    body = payload or run_cerebras_rerank()
    return {
        "id": CEREBRAS_ID,
        "label": (
            "Frozen: naive Cerebras rerank of hybrid top-50. "
            "Formulation presence, not proof. One synchronous call per question. "
            "Does not replace C@8, Coverage v3, or the experimental proof chain. "
            "24/53 remains the quality reference."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "applied_to_v3": False,
        "no_coverage_controller": True,
        "no_proof_evaluator": True,
        "task": TASK,
        "headline": {
            "quality_reference": body.get("quality_reference"),
            "k": body.get("k"),
            "model": body.get("model"),
            "summary": body.get("summary"),
            "golds": [
                {
                    "gold_id": row.get("gold_id"),
                    "precision": row.get("precision"),
                    "candidate_recall": row.get("candidate_recall"),
                    "corpus_recall": row.get("corpus_recall"),
                    "corpus_document_recall": row.get("corpus_document_recall"),
                    "retrieval_document_coverage": row.get("retrieval_document_coverage"),
                    "relevant_in_candidates": row.get("relevant_in_candidates"),
                    "relevant_in_corpus": row.get("relevant_in_corpus"),
                    "match": row.get("match"),
                    "uncertain": row.get("uncertain"),
                    "ttft_seconds": row.get("ttft_seconds"),
                    "model_seconds": row.get("model_seconds"),
                    "prompt_tokens": row.get("prompt_tokens"),
                    "completion_tokens": row.get("completion_tokens"),
                }
                for row in body.get("golds") or []
            ],
        },
    }


def write_cerebras_rerank(
    payload: dict[str, object] | None = None,
    path: Path | None = None,
) -> Path:
    target = path or CEREBRAS_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    body = payload or run_cerebras_rerank()
    target.write_text(
        json.dumps(freeze_cerebras_rerank(body), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _summary(rows: list[dict[str, object]]) -> dict[str, object]:
    if not rows:
        return {}
    return {
        "golds": len(rows),
        "mean_precision": _mean(rows, "precision"),
        "mean_candidate_recall": _mean(rows, "candidate_recall"),
        "mean_corpus_recall": _mean(rows, "corpus_recall"),
        "mean_corpus_document_recall": _mean(rows, "corpus_document_recall"),
        "mean_ttft_seconds": _mean(rows, "ttft_seconds"),
        "mean_model_seconds": _mean(rows, "model_seconds"),
        "total_prompt_tokens": _sum(rows, "prompt_tokens"),
        "total_completion_tokens": _sum(rows, "completion_tokens"),
        "cost_usd": None,
    }


def _mean(rows: list[dict[str, object]], key: str) -> float | None:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    if not values:
        return None
    return sum(values) / len(values)


def _sum(rows: list[dict[str, object]], key: str) -> int | None:
    values = [int(row[key]) for row in rows if row.get(key) is not None]
    if not values:
        return None
    return sum(values)
