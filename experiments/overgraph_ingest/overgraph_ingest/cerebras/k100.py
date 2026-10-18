"""GPT-OSS medium, minimal JSON, hybrid top-100. Retrieval gain versus model selection."""

from __future__ import annotations

import json
import time
from pathlib import Path

from overgraph_ingest.cerebras.client import CerebrasClient, Completer, EmptyCompletionError
from overgraph_ingest.cerebras.evaluate import (
    relevant_documents,
    relevant_keys,
    score_negations,
    score_rerank,
    span_keys,
)
from overgraph_ingest.cerebras.output import DEFAULT_FROZEN, _visible_json_chars
from overgraph_ingest.cerebras.pricing import RATE_CARD_DATE, RATE_CARD_SOURCE, cost_usd
from overgraph_ingest.cerebras.prompt import (
    MATCH,
    MINIMAL,
    TASK,
    build_messages,
    candidates_from_hits,
    parse_minimal,
)
from overgraph_ingest.cerebras.run import (
    DEFAULT_BASE_URL,
    DEFAULT_DB,
    DEFAULT_GOLD_DIR,
    DEFAULT_MODEL,
    _mean,
    _sum,
    _summary,
)
from overgraph_ingest.config import RetrievalConfig
from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE
from overgraph_ingest.coverage.run import _golds, _ranked_hits
from overgraph_ingest.graph.writer import GraphWriter, open_database, resolve_dimension
from overgraph_ingest.jev.candidates import load_graph_context
from overgraph_ingest.retrieval.conclusions import (
    load_cerebras_output_baseline,
    load_cerebras_rerank_baseline,
)
from overgraph_ingest.retrieval.encode import LexicalSparseEncoder
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION
from overgraph_ingest.retrieval.run import _dense_encoder
from overgraph_ingest.retrieval.search import SearchHit, encode_query

ROOT = Path(__file__).resolve().parents[2]
K100_ID = "phase2-cerebras-k100-v1"
K100_PATH = ROOT / "baselines" / f"{K100_ID}.json"
REFERENCE_ID = "phase2-cerebras-output-v1"
K = 100
REFERENCE_K = 50
REASONING_EFFORT = "medium"
# Working k=50 cap is 8192. The first one-shot k=100 Medium call
# exhausted that cap on reasoning and returned no JSON. 40000 was a
# diagnostic raise to see if more room produced JSON. It did not.
K100_MAX_COMPLETION_TOKENS = 40_000
K50_CAP = 8192


def run_cerebras_k100(
    *,
    frozen_path: Path | None = None,
    db_path: Path | None = None,
    gold_dir: Path | None = None,
    dense_dimension: int = 3072,
    openai_api_key: str | None = None,
    openai_base_url: str | None = None,
    dense_model: str = "text-embedding-3-large",
    cerebras_api_key: str | None = None,
    cerebras_base_url: str = DEFAULT_BASE_URL,
    client: Completer | None = None,
    hits_by_gold: dict[str, list[SearchHit]] | None = None,
) -> dict[str, object]:
    source = frozen_path or DEFAULT_FROZEN
    frozen = json.loads(source.read_text(encoding="utf-8"))
    frozen_keys = {
        str(row["gold_id"]): [str(item["key"]) for item in row["judgments"]]
        for row in frozen.get("golds") or []
    }
    reference = {
        str(row["gold_id"]): row
        for row in (load_cerebras_output_baseline().get("headline") or {}).get("golds")
        or []
    }
    golds = _golds(None, gold_dir or DEFAULT_GOLD_DIR)
    if not golds:
        raise ValueError("no seen golds")
    target = db_path or DEFAULT_DB
    dimension = resolve_dimension(target, dense_dimension)
    db = open_database(target, dimension)
    try:
        units = load_graph_context(GraphWriter(db, batch_size=500)).units
    finally:
        db.close()
    if hits_by_gold is None and any(unit.dense is None or unit.sparse is None for unit in units):
        raise RuntimeError("TextUnits are missing vectors; rerun with --embed")
    dense = None
    sparse = None
    if hits_by_gold is None:
        config = RetrievalConfig(
            db_path=target,
            dense_dimension=dimension,
            dense_model=dense_model,
            openai_api_key=openai_api_key,
            openai_base_url=openai_base_url,
        )
        dense = _dense_encoder(config, dimension)
        sparse = LexicalSparseEncoder()
        sparse.fit([unit.text for unit in units])
    completer = client or CerebrasClient(
        api_key=cerebras_api_key or "",
        base_url=cerebras_base_url,
        model=DEFAULT_MODEL,
        timeout_seconds=180.0,
        max_completion_tokens=K100_MAX_COMPLETION_TOKENS,
        reasoning_effort=REASONING_EFFORT,
    )
    started = time.perf_counter()
    rows: list[dict[str, object]] = []
    model_failure: dict[str, object] | None = None
    model_attempted = 0
    for gold in golds:
        gold_started = time.perf_counter()
        if hits_by_gold is not None:
            ranked = hits_by_gold[gold.id][:K]
            retrieval_seconds = 0.0
        else:
            dense_query, sparse_query = encode_query(gold.query, dense=dense, sparse=sparse)
            ranked = _ranked_hits(units, "hybrid", dense_query, sparse_query)[:K]
            retrieval_seconds = time.perf_counter() - gold_started
        if len(ranked) != K:
            raise ValueError(f"{gold.id} ranked list is not k={K}")
        candidates = candidates_from_hits(ranked)
        corpus_keys = relevant_keys(units, gold)
        corpus_docs = relevant_documents(units, gold, corpus_keys)
        previous_keys = frozen_keys[gold.id]
        if len(previous_keys) != REFERENCE_K:
            raise ValueError(f"{gold.id} frozen list is not k={REFERENCE_K}")
        new_keys = [item.key for item in candidates]
        split = _split_effects(
            previous_keys=previous_keys,
            new_keys=new_keys,
            corpus_keys=corpus_keys,
            match_keys=set(),
        )
        split["model_missed_from_k50"] = None
        split["model_caught_gain"] = None
        split["model_missed_from_k50_keys"] = []
        baseline = reference[gold.id]
        metrics = {
            "gold_id": gold.id,
            "query": gold.query,
            "variant": MINIMAL,
            "setting": REASONING_EFFORT,
            "k": K,
            "candidates": len(candidates),
            "relevant_in_candidates": split["relevant_in_100"],
            "relevant_in_corpus": len(corpus_keys),
            "corpus_recall": (
                (split["relevant_in_100"] / len(corpus_keys)) if corpus_keys else 0.0
            ),
            "retrieval_document_coverage": (
                (
                    len({item.relative_path for item in candidates} & corpus_docs)
                    / len(corpus_docs)
                )
                if corpus_docs
                else 0.0
            ),
            "model_status": "not_attempted",
            "retrieval_seconds": retrieval_seconds,
            "effects": split,
            "top50_overlap": split["top50_overlap"],
            "retrieval_gain": split["retrieval_gain"],
            "reference": {
                "experiment": REFERENCE_ID,
                "k": REFERENCE_K,
                "precision": baseline.get("precision"),
                "candidate_recall": baseline.get("candidate_recall"),
                "completion_tokens": baseline.get("completion_tokens"),
                "model_seconds": baseline.get("model_seconds"),
            },
            "delta": {
                "relevant_in_candidates": split["relevant_in_100"]
                - split["relevant_in_frozen_50"],
            },
        }
        if model_failure is None:
            model_attempted += 1
            messages = build_messages(gold.query, candidates, variant=MINIMAL)
            try:
                reply = completer.complete(messages)
            except EmptyCompletionError as exc:
                spent = (
                    None
                    if exc.prompt_tokens is None or exc.completion_tokens is None
                    else cost_usd(DEFAULT_MODEL, exc.prompt_tokens, exc.completion_tokens)
                )
                model_failure = {
                    "gold_id": gold.id,
                    "finish_reason": exc.finish_reason,
                    "reasoning_tokens": exc.reasoning_tokens,
                    "prompt_tokens": exc.prompt_tokens,
                    "completion_tokens": exc.completion_tokens,
                    "model_seconds": exc.completion_seconds,
                    "cost_usd": spent,
                    "max_completion_tokens": K100_MAX_COMPLETION_TOKENS,
                }
                metrics["model_status"] = "empty_completion"
                metrics["prompt_tokens"] = exc.prompt_tokens
                metrics["completion_tokens"] = exc.completion_tokens
                metrics["reasoning_tokens"] = exc.reasoning_tokens
                metrics["model_seconds"] = exc.completion_seconds
                metrics["cost_usd"] = spent
            else:
                parsed, errors = parse_minimal(json.loads(reply.text), candidates)
                if reply.prompt_tokens is None or reply.completion_tokens is None:
                    raise ValueError(f"{gold.id} is missing token counts")
                scored = score_rerank(
                    gold=gold,
                    candidates=candidates,
                    judgments=parsed,
                    corpus_relevant_keys=corpus_keys,
                    corpus_relevant_docs=corpus_docs,
                )
                scored.update(
                    score_negations(
                        candidates=candidates,
                        judgments=parsed,
                        hard_keys=span_keys(units, gold.hard_negatives),
                        watch_keys=span_keys(units, gold.watch_negatives),
                    )
                )
                match_keys = {row.key for row in parsed if row.label == MATCH}
                split = _split_effects(
                    previous_keys=previous_keys,
                    new_keys=new_keys,
                    corpus_keys=corpus_keys,
                    match_keys=match_keys,
                )
                true_matches = len(scored["true_match_keys"])
                spent = cost_usd(DEFAULT_MODEL, reply.prompt_tokens, reply.completion_tokens)
                metrics.update(scored)
                metrics["model_status"] = "ok"
                metrics["ttft_seconds"] = reply.ttft_seconds
                metrics["model_seconds"] = reply.completion_seconds
                metrics["prompt_tokens"] = reply.prompt_tokens
                metrics["completion_tokens"] = reply.completion_tokens
                metrics["reasoning_tokens"] = reply.reasoning_tokens
                metrics["cost_usd"] = spent
                metrics["true_matches"] = true_matches
                metrics["cost_per_true_match_usd"] = (
                    None if true_matches == 0 else spent / true_matches
                )
                metrics["invented_ids"] = errors["invented"]
                metrics["duplicate_ids"] = errors["duplicates"]
                metrics["id_errors"] = len(errors["invented"]) + len(errors["duplicates"])
                metrics["effects"] = split
                metrics["top50_overlap"] = split["top50_overlap"]
                metrics["retrieval_gain"] = split["retrieval_gain"]
                metrics["model_missed_from_k50"] = split["model_missed_from_k50"]
                metrics["model_caught_gain"] = split["model_caught_gain"]
                metrics["delta"] = {
                    "precision": metrics["precision"] - float(baseline["precision"]),
                    "candidate_recall": metrics["candidate_recall"]
                    - float(baseline["candidate_recall"]),
                    "relevant_in_candidates": split["relevant_in_100"]
                    - split["relevant_in_frozen_50"],
                    "completion_tokens": reply.completion_tokens
                    - int(baseline["completion_tokens"]),
                }
                metrics["judgments"] = [
                    {"id": row.short_id, "key": row.key, "label": row.label} for row in parsed
                ]
        metrics["wall_seconds"] = time.perf_counter() - gold_started
        rows.append(metrics)
    reference_true = _reference_true_matches()
    reference_cost = _reference_cost()
    return {
        "operation": "rerank",
        "experiment": "cerebras_k100_v1",
        "task": TASK,
        "variant": MINIMAL,
        "setting": REASONING_EFFORT,
        "reference_experiment": REFERENCE_ID,
        "same_retrieval_strategy": "hybrid",
        "k": K,
        "reference_k": REFERENCE_K,
        "max_completion_tokens": K100_MAX_COMPLETION_TOKENS,
        "k50_cap_exhausted_reasoning": True,
        "model": DEFAULT_MODEL,
        "applied_to_v3": False,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_replace_cerebras_output": True,
        "k200_not_started": True,
        "second_opinion_not_started": True,
        "no_coverage_controller": True,
        "no_proof_evaluator": True,
        "one_call_per_question": True,
        "uncertain_is_not_match": True,
        "same_mapping": GOLD_MAP_VERSION,
        "quality_reference": QUALITY_REFERENCE,
        "rate_card_date": RATE_CARD_DATE,
        "rate_card_source": RATE_CARD_SOURCE,
        "model_completes": model_failure is None,
        "model_attempted": model_attempted,
        "model_failure": model_failure,
        "golds": rows,
        "wall_seconds": time.perf_counter() - started,
        "summary": {
            **_summary(rows),
            "total_id_errors": _sum(rows, "id_errors") or 0,
            "total_reasoning_tokens": _sum(rows, "reasoning_tokens"),
            "total_true_matches": _sum(rows, "true_matches"),
            "total_visible_json_chars": sum(_visible_json_chars(row) for row in rows),
            "cost_usd": None
            if model_failure is None
            else model_failure.get("cost_usd")
            if not any(row.get("model_status") == "ok" for row in rows)
            else cost_usd(
                DEFAULT_MODEL,
                _sum(rows, "prompt_tokens") or 0,
                _sum(rows, "completion_tokens") or 0,
            ),
            "cost_per_true_match_usd": None,
            "reference_true_matches": reference_true,
            "reference_cost_usd": reference_cost,
            "reference_cost_per_true_match_usd": reference_cost / reference_true,
            "mean_top50_overlap": _mean(rows, "top50_overlap"),
            "total_retrieval_gain": _sum(rows, "retrieval_gain"),
            "total_model_missed_from_k50": _sum(rows, "model_missed_from_k50"),
            "total_model_caught_gain": _sum(rows, "model_caught_gain"),
            "mean_corpus_recall": _mean(rows, "corpus_recall"),
            "mean_precision_delta": _mean([row["delta"] for row in rows], "precision"),
            "mean_candidate_recall_delta": _mean(
                [row["delta"] for row in rows], "candidate_recall"
            ),
        },
    }


def freeze_cerebras_k100(payload: dict[str, object] | None = None) -> dict[str, object]:
    body = payload or run_cerebras_k100()
    return {
        "id": K100_ID,
        "label": (
            "Frozen: hybrid top-100 retrieval versus GPT-OSS medium one-shot. "
            "Medium exhausted 40k reasoning tokens without JSON. Retrieval "
            "gain is measured; model selection at k=100 did not complete. "
            "Does not replace C@8 or output v1. k=200 and second opinion "
            "are not started. 24/53 remains the quality reference."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_replace_cerebras_output": True,
        "k200_not_started": True,
        "second_opinion_not_started": True,
        "applied_to_v3": False,
        "same_retrieval_strategy": "hybrid",
        "task": TASK,
        "headline": {
            "quality_reference": body.get("quality_reference"),
            "k": body.get("k"),
            "reference_k": body.get("reference_k"),
            "model": body.get("model"),
            "setting": body.get("setting"),
            "variant": body.get("variant"),
            "rate_card_date": body.get("rate_card_date"),
            "model_completes": body.get("model_completes"),
            "model_failure": body.get("model_failure"),
            "summary": body.get("summary"),
            "golds": [
                {
                    "gold_id": row.get("gold_id"),
                    "precision": row.get("precision"),
                    "candidate_recall": row.get("candidate_recall"),
                    "corpus_recall": row.get("corpus_recall"),
                    "relevant_in_candidates": row.get("relevant_in_candidates"),
                    "relevant_in_corpus": row.get("relevant_in_corpus"),
                    "true_matches": row.get("true_matches"),
                    "match": row.get("match"),
                    "uncertain": row.get("uncertain"),
                    "id_errors": row.get("id_errors"),
                    "prompt_tokens": row.get("prompt_tokens"),
                    "completion_tokens": row.get("completion_tokens"),
                    "reasoning_tokens": row.get("reasoning_tokens"),
                    "cost_usd": row.get("cost_usd"),
                    "cost_per_true_match_usd": row.get("cost_per_true_match_usd"),
                    "ttft_seconds": row.get("ttft_seconds"),
                    "model_seconds": row.get("model_seconds"),
                    "effects": row.get("effects"),
                    "delta": row.get("delta"),
                }
                for row in body.get("golds") or []
            ],
        },
    }


def write_cerebras_k100(
    payload: dict[str, object] | None = None,
    path: Path | None = None,
) -> Path:
    target = path or K100_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    body = payload or run_cerebras_k100()
    target.write_text(
        json.dumps(freeze_cerebras_k100(body), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _split_effects(
    *,
    previous_keys: list[str],
    new_keys: list[str],
    corpus_keys: set[str],
    match_keys: set[str],
) -> dict[str, object]:
    frozen_50 = previous_keys[:REFERENCE_K]
    new_50 = new_keys[:REFERENCE_K]
    new_100 = new_keys[:K]
    relevant_frozen = set(frozen_50) & corpus_keys
    relevant_new_50 = set(new_50) & corpus_keys
    relevant_100 = set(new_100) & corpus_keys
    retrieval_gain = relevant_100 - relevant_frozen
    still_missing = corpus_keys - relevant_100
    missed_from_k50 = relevant_frozen - match_keys
    caught_gain = retrieval_gain & match_keys
    return {
        "top50_overlap": len(set(frozen_50) & set(new_50)),
        "relevant_in_frozen_50": len(relevant_frozen),
        "relevant_in_new_50": len(relevant_new_50),
        "relevant_in_100": len(relevant_100),
        "retrieval_gain": len(retrieval_gain),
        "still_missing": len(still_missing),
        "model_missed_from_k50": len(missed_from_k50),
        "model_caught_gain": len(caught_gain),
        "retrieval_gain_keys": sorted(retrieval_gain),
        "model_missed_from_k50_keys": sorted(missed_from_k50),
    }


def _reference_true_matches() -> int:
    golds = (load_cerebras_output_baseline().get("headline") or {}).get("golds") or []
    total = 0
    for row in golds:
        recall = float(row["candidate_recall"])
        relevant = _frozen_relevant(str(row["gold_id"]))
        total += int(round(recall * relevant))
    return total


def _frozen_relevant(gold_id: str) -> int:
    golds = (load_cerebras_rerank_baseline().get("headline") or {}).get("golds") or []
    for row in golds:
        if row.get("gold_id") == gold_id:
            return int(row["relevant_in_candidates"])
    raise ValueError(f"missing frozen relevant_in_candidates for {gold_id}")


def _reference_cost() -> float:
    summary = (load_cerebras_output_baseline().get("headline") or {}).get("summary") or {}
    return cost_usd(
        DEFAULT_MODEL,
        int(summary["total_prompt_tokens"]),
        int(summary["total_completion_tokens"]),
    )
