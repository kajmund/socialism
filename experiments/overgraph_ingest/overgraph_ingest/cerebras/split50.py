"""100 hybrid candidates as two sequential Medium calls of 50. Not one-shot k=100."""

from __future__ import annotations

import json
import time
from pathlib import Path

from overgraph_ingest.cerebras.client import CerebrasClient, Completer, EmptyCompletionError
from overgraph_ingest.cerebras.evaluate import (
    relevant_documents,
    relevant_keys,
    score_rerank,
)
from overgraph_ingest.cerebras.k100 import (
    _frozen_relevant,
    _reference_cost,
    _reference_true_matches,
    _split_effects,
)
from overgraph_ingest.cerebras.output import DEFAULT_FROZEN, _visible_json_chars
from overgraph_ingest.cerebras.pricing import RATE_CARD_DATE, RATE_CARD_SOURCE, cost_usd
from overgraph_ingest.cerebras.prompt import (
    MATCH,
    MINIMAL,
    TASK,
    Candidate,
    ParsedJudgment,
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
from overgraph_ingest.retrieval.conclusions import load_cerebras_output_baseline
from overgraph_ingest.retrieval.encode import LexicalSparseEncoder
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION
from overgraph_ingest.retrieval.run import _dense_encoder
from overgraph_ingest.retrieval.search import SearchHit, encode_query

ROOT = Path(__file__).resolve().parents[2]
SPLIT50_ID = "phase2-cerebras-split50-v1"
SPLIT50_PATH = ROOT / "baselines" / f"{SPLIT50_ID}.json"
REFERENCE_ID = "phase2-cerebras-output-v1"
DEFAULT_OUTPUT_LIVE = ROOT / "data" / "cerebras-output-v1.json"
K = 100
BATCH_SIZE = 50
BATCH_COUNT = 2
REASONING_EFFORT = "medium"
# Working k=50 cap. The 40k figure on k=100 was a later diagnostic raise
# after 8192 also exhausted on reasoning. This experiment does not use 40k.
SPLIT50_MAX_COMPLETION_TOKENS = 8192
K100_DIAGNOSTIC_CAP = 40_000


def run_cerebras_split50(
    *,
    frozen_path: Path | None = None,
    output_live_path: Path | None = None,
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
    previous_match_by_gold: dict[str, set[str]] | None = None,
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
    previous_matches = previous_match_by_gold or _load_previous_match_keys(
        output_live_path or DEFAULT_OUTPUT_LIVE
    )
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
        timeout_seconds=120.0,
        max_completion_tokens=SPLIT50_MAX_COMPLETION_TOKENS,
        reasoning_effort=REASONING_EFFORT,
    )
    started = time.perf_counter()
    rows: list[dict[str, object]] = []
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
        previous_keys = frozen_keys[gold.id]
        if len(previous_keys) != BATCH_SIZE:
            raise ValueError(f"{gold.id} frozen list is not k={BATCH_SIZE}")
        first = candidates_from_hits(ranked[:BATCH_SIZE])
        second = candidates_from_hits(ranked[BATCH_SIZE:])
        candidates = _merge_candidates(first, second)
        corpus_keys = relevant_keys(units, gold)
        corpus_docs = relevant_documents(units, gold, corpus_keys)
        split = _split_effects(
            previous_keys=previous_keys,
            new_keys=[item.key for item in candidates],
            corpus_keys=corpus_keys,
            match_keys=set(),
        )
        baseline = reference[gold.id]
        first_result = _judge_batch(completer, gold.query, first)
        second_result = _judge_batch(completer, gold.query, second)
        batches = [_batch_row(0, first, first_result), _batch_row(1, second, second_result)]
        metrics: dict[str, object] = {
            "gold_id": gold.id,
            "query": gold.query,
            "variant": MINIMAL,
            "setting": REASONING_EFFORT,
            "k": K,
            "batch_size": BATCH_SIZE,
            "calls": BATCH_COUNT,
            "candidates": len(candidates),
            "relevant_in_candidates": split["relevant_in_100"],
            "relevant_in_corpus": len(corpus_keys),
            "retrieval_corpus_recall": (
                (split["relevant_in_100"] / len(corpus_keys)) if corpus_keys else 0.0
            ),
            "retrieval_seconds": retrieval_seconds,
            "effects": split,
            "top50_overlap": split["top50_overlap"],
            "retrieval_gain": split["retrieval_gain"],
            "batches": batches,
            "reference": {
                "experiment": REFERENCE_ID,
                "k": BATCH_SIZE,
                "precision": baseline.get("precision"),
                "candidate_recall": baseline.get("candidate_recall"),
                "completion_tokens": baseline.get("completion_tokens"),
                "model_seconds": baseline.get("model_seconds"),
            },
        }
        if first_result["status"] != "ok" or second_result["status"] != "ok":
            metrics["model_status"] = "incomplete"
            metrics["model_seconds"] = _optional_sum(
                first_result.get("model_seconds"), second_result.get("model_seconds")
            )
            metrics["prompt_tokens"] = _optional_sum(
                first_result.get("prompt_tokens"), second_result.get("prompt_tokens")
            )
            metrics["completion_tokens"] = _optional_sum(
                first_result.get("completion_tokens"), second_result.get("completion_tokens")
            )
            metrics["reasoning_tokens"] = _optional_sum(
                first_result.get("reasoning_tokens"), second_result.get("reasoning_tokens")
            )
            metrics["cost_usd"] = _optional_sum(
                first_result.get("cost_usd"), second_result.get("cost_usd")
            )
            if first_result["status"] == "ok":
                groups = group_effects(
                    previous_match_keys=previous_matches[gold.id],
                    batch_match_keys={
                        row.key for row in first_result["judgments"] if row.label == MATCH
                    },
                    corpus_keys=corpus_keys,
                    first50_keys={item.key for item in first},
                )
                metrics["group_effects"] = groups
                metrics["lost_from_k50_true_matches"] = groups["lost_from_k50_true_matches"]
            metrics["wall_seconds"] = time.perf_counter() - gold_started
            rows.append(metrics)
            continue
        judgments = first_result["judgments"] + second_result["judgments"]
        scored = score_rerank(
            gold=gold,
            candidates=candidates,
            judgments=judgments,
            corpus_relevant_keys=corpus_keys,
            corpus_relevant_docs=corpus_docs,
        )
        match_keys = {row.key for row in judgments if row.label == MATCH}
        split = _split_effects(
            previous_keys=previous_keys,
            new_keys=[item.key for item in candidates],
            corpus_keys=corpus_keys,
            match_keys=match_keys,
        )
        first_score = _batch_quality(first, first_result["judgments"], corpus_keys)
        second_score = _batch_quality(second, second_result["judgments"], corpus_keys)
        groups = group_effects(
            previous_match_keys=previous_matches[gold.id],
            batch_match_keys={
                row.key for row in first_result["judgments"] if row.label == MATCH
            },
            corpus_keys=corpus_keys,
            first50_keys={item.key for item in first},
        )
        true_matches = len(scored["true_match_keys"])
        prompt_tokens = int(first_result["prompt_tokens"]) + int(second_result["prompt_tokens"])
        completion_tokens = int(first_result["completion_tokens"]) + int(
            second_result["completion_tokens"]
        )
        reasoning_tokens = _optional_sum(
            first_result.get("reasoning_tokens"), second_result.get("reasoning_tokens")
        )
        spent = cost_usd(DEFAULT_MODEL, prompt_tokens, completion_tokens)
        invented = first_result["errors"]["invented"] + second_result["errors"]["invented"]
        duplicates = first_result["errors"]["duplicates"] + second_result["errors"]["duplicates"]
        metrics.update(scored)
        metrics["model_status"] = "ok"
        metrics["effects"] = split
        metrics["top50_overlap"] = split["top50_overlap"]
        metrics["retrieval_gain"] = split["retrieval_gain"]
        metrics["group_effects"] = groups
        metrics["lost_from_k50_true_matches"] = groups["lost_from_k50_true_matches"]
        metrics["model_caught_gain"] = split["model_caught_gain"]
        metrics["model_missed_from_k50"] = split["model_missed_from_k50"]
        metrics["batch_quality"] = {"first50": first_score, "second50": second_score}
        metrics["ttft_seconds"] = first_result.get("ttft_seconds")
        metrics["model_seconds"] = float(first_result["model_seconds"]) + float(
            second_result["model_seconds"]
        )
        metrics["prompt_tokens"] = prompt_tokens
        metrics["completion_tokens"] = completion_tokens
        metrics["reasoning_tokens"] = reasoning_tokens
        metrics["cost_usd"] = spent
        metrics["true_matches"] = true_matches
        metrics["cost_per_true_match_usd"] = None if true_matches == 0 else spent / true_matches
        metrics["invented_ids"] = invented
        metrics["duplicate_ids"] = duplicates
        metrics["id_errors"] = len(invented) + len(duplicates)
        metrics["delta"] = {
            "precision": metrics["precision"] - float(baseline["precision"]),
            "candidate_recall": metrics["candidate_recall"]
            - float(baseline["candidate_recall"]),
            "true_matches": true_matches - _reference_true_matches_for(gold.id),
            "completion_tokens": completion_tokens - int(baseline["completion_tokens"]),
            "model_seconds": metrics["model_seconds"] - float(baseline["model_seconds"]),
        }
        metrics["judgments"] = [
            {
                "batch": 0 if index < BATCH_SIZE else 1,
                "id": row.short_id,
                "key": row.key,
                "label": row.label,
            }
            for index, row in enumerate(judgments)
        ]
        metrics["wall_seconds"] = time.perf_counter() - gold_started
        rows.append(metrics)
    completed = [row for row in rows if row.get("model_status") == "ok"]
    reference_true = _reference_true_matches()
    reference_cost = _reference_cost()
    total_true = _sum(completed, "true_matches")
    total_cost = None
    if rows and all(
        row.get("prompt_tokens") is not None and row.get("completion_tokens") is not None
        for row in rows
    ):
        total_cost = cost_usd(
            DEFAULT_MODEL,
            _sum(rows, "prompt_tokens") or 0,
            _sum(rows, "completion_tokens") or 0,
        )
    return {
        "operation": "rerank",
        "experiment": "cerebras_split50_v1",
        "task": TASK,
        "variant": MINIMAL,
        "setting": REASONING_EFFORT,
        "reference_experiment": REFERENCE_ID,
        "same_retrieval_strategy": "hybrid",
        "k": K,
        "batch_size": BATCH_SIZE,
        "calls_per_question": BATCH_COUNT,
        "sequential_calls": True,
        "parallel_calls": False,
        "this_is_not_jev_batching": True,
        "one_shot_k100_not_retried": True,
        "does_not_change_reasoning": True,
        "max_completion_tokens": SPLIT50_MAX_COMPLETION_TOKENS,
        "k100_diagnostic_cap": K100_DIAGNOSTIC_CAP,
        "model": DEFAULT_MODEL,
        "applied_to_v3": False,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_replace_cerebras_output": True,
        "does_not_replace_cerebras_k100": True,
        "k200_not_started": True,
        "second_opinion_not_started": True,
        "no_coverage_controller": True,
        "no_proof_evaluator": True,
        "uncertain_is_not_match": True,
        "same_mapping": GOLD_MAP_VERSION,
        "quality_reference": QUALITY_REFERENCE,
        "rate_card_date": RATE_CARD_DATE,
        "rate_card_source": RATE_CARD_SOURCE,
        "model_completes": all(row.get("model_status") == "ok" for row in rows),
        "golds": rows,
        "wall_seconds": time.perf_counter() - started,
        "summary": {
            **_summary(completed),
            "total_id_errors": _sum(completed, "id_errors") or 0,
            "total_reasoning_tokens": _sum(rows, "reasoning_tokens"),
            "total_true_matches": total_true,
            "total_visible_json_chars": sum(_visible_json_chars(row) for row in completed),
            "total_lost_from_k50_true_matches": _sum(completed, "lost_from_k50_true_matches"),
            "total_model_caught_gain": _sum(completed, "model_caught_gain"),
            "total_model_missed_from_k50": _sum(completed, "model_missed_from_k50"),
            "cost_usd": total_cost,
            "cost_per_true_match_usd": (
                None if total_cost is None or not total_true else total_cost / total_true
            ),
            "reference_true_matches": reference_true,
            "reference_cost_usd": reference_cost,
            "reference_cost_per_true_match_usd": reference_cost / reference_true,
            "mean_top50_overlap": _mean(rows, "top50_overlap"),
            "total_retrieval_gain": _sum(rows, "retrieval_gain"),
            "mean_retrieval_corpus_recall": _mean(rows, "retrieval_corpus_recall"),
            "mean_precision_delta": _mean([row.get("delta") or {} for row in completed], "precision"),
            "mean_candidate_recall_delta": _mean(
                [row.get("delta") or {} for row in completed], "candidate_recall"
            ),
        },
    }


def group_effects(
    *,
    previous_match_keys: set[str],
    batch_match_keys: set[str],
    corpus_keys: set[str],
    first50_keys: set[str],
) -> dict[str, object]:
    previous = previous_match_keys & first50_keys
    current = batch_match_keys & first50_keys
    lost = previous - current
    gained = current - previous
    lost_true = lost & corpus_keys
    return {
        "first50_previous_match": len(previous),
        "first50_batch_match": len(current),
        "lost_from_k50_matches": len(lost),
        "lost_from_k50_true_matches": len(lost_true),
        "new_on_k50_matches": len(gained),
        "lost_from_k50_true_match_keys": sorted(lost_true),
    }


def freeze_cerebras_split50(payload: dict[str, object] | None = None) -> dict[str, object]:
    body = payload or run_cerebras_split50()
    return {
        "id": SPLIT50_ID,
        "label": (
            "Frozen: hybrid top-100 judged as two sequential GPT-OSS medium "
            "calls of 50 with minimal JSON and the working 8192 cap. "
            "Measures whether the naive rerank scales without one-shot k=100. "
            "Does not replace C@8, output v1, or the k=100 retrieval freeze. "
            "k=200 and second opinion are not started. 24/53 remains the "
            "quality reference."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_replace_cerebras_output": True,
        "does_not_replace_cerebras_k100": True,
        "k200_not_started": True,
        "second_opinion_not_started": True,
        "one_shot_k100_not_retried": True,
        "does_not_change_reasoning": True,
        "applied_to_v3": False,
        "same_retrieval_strategy": "hybrid",
        "task": TASK,
        "headline": {
            "quality_reference": body.get("quality_reference"),
            "k": body.get("k"),
            "batch_size": body.get("batch_size"),
            "calls_per_question": body.get("calls_per_question"),
            "model": body.get("model"),
            "setting": body.get("setting"),
            "variant": body.get("variant"),
            "max_completion_tokens": body.get("max_completion_tokens"),
            "rate_card_date": body.get("rate_card_date"),
            "model_completes": body.get("model_completes"),
            "summary": body.get("summary"),
            "golds": [
                {
                    "gold_id": row.get("gold_id"),
                    "precision": row.get("precision"),
                    "candidate_recall": row.get("candidate_recall"),
                    "corpus_recall": row.get("corpus_recall"),
                    "retrieval_corpus_recall": row.get("retrieval_corpus_recall"),
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
                    "model_seconds": row.get("model_seconds"),
                    "effects": row.get("effects"),
                    "group_effects": row.get("group_effects"),
                    "batch_quality": row.get("batch_quality"),
                    "delta": row.get("delta"),
                }
                for row in body.get("golds") or []
            ],
        },
    }


def write_cerebras_split50(
    payload: dict[str, object] | None = None,
    path: Path | None = None,
) -> Path:
    target = path or SPLIT50_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    body = payload or run_cerebras_split50()
    target.write_text(
        json.dumps(freeze_cerebras_split50(body), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _judge_batch(
    completer: Completer,
    query: str,
    candidates: list[Candidate],
) -> dict[str, object]:
    if len(candidates) != BATCH_SIZE:
        raise ValueError(f"batch is not {BATCH_SIZE} candidates")
    messages = build_messages(query, candidates, variant=MINIMAL)
    try:
        reply = completer.complete(messages)
    except EmptyCompletionError as exc:
        spent = (
            None
            if exc.prompt_tokens is None or exc.completion_tokens is None
            else cost_usd(DEFAULT_MODEL, exc.prompt_tokens, exc.completion_tokens)
        )
        return {
            "status": "empty_completion",
            "judgments": None,
            "errors": {"invented": [], "duplicates": []},
            "finish_reason": exc.finish_reason,
            "reasoning_tokens": exc.reasoning_tokens,
            "prompt_tokens": exc.prompt_tokens,
            "completion_tokens": exc.completion_tokens,
            "model_seconds": exc.completion_seconds,
            "ttft_seconds": None,
            "cost_usd": spent,
        }
    parsed, errors = parse_minimal(json.loads(reply.text), candidates)
    if reply.prompt_tokens is None or reply.completion_tokens is None:
        raise ValueError("Cerebras reply is missing token counts")
    return {
        "status": "ok",
        "judgments": parsed,
        "errors": errors,
        "finish_reason": reply.finish_reason,
        "reasoning_tokens": reply.reasoning_tokens,
        "prompt_tokens": reply.prompt_tokens,
        "completion_tokens": reply.completion_tokens,
        "model_seconds": reply.completion_seconds,
        "ttft_seconds": reply.ttft_seconds,
        "cost_usd": cost_usd(DEFAULT_MODEL, reply.prompt_tokens, reply.completion_tokens),
    }


def _batch_row(
    index: int,
    candidates: list[Candidate],
    result: dict[str, object],
) -> dict[str, object]:
    return {
        "batch": index,
        "candidates": len(candidates),
        "first_id": candidates[0].short_id,
        "last_id": candidates[-1].short_id,
        "status": result["status"],
        "prompt_tokens": result.get("prompt_tokens"),
        "completion_tokens": result.get("completion_tokens"),
        "reasoning_tokens": result.get("reasoning_tokens"),
        "model_seconds": result.get("model_seconds"),
        "ttft_seconds": result.get("ttft_seconds"),
        "cost_usd": result.get("cost_usd"),
        "finish_reason": result.get("finish_reason"),
    }


def _batch_quality(
    candidates: list[Candidate],
    judgments: list[ParsedJudgment],
    corpus_keys: set[str],
) -> dict[str, object]:
    relevant = {item.key for item in candidates} & corpus_keys
    match_keys = {row.key for row in judgments if row.label == MATCH}
    true_match = match_keys & corpus_keys
    return {
        "relevant": len(relevant),
        "match": len(match_keys),
        "true_matches": len(true_match),
        "precision": (len(true_match) / len(match_keys)) if match_keys else 0.0,
        "candidate_recall": (len(true_match) / len(relevant)) if relevant else 0.0,
    }


def _merge_candidates(first: list[Candidate], second: list[Candidate]) -> list[Candidate]:
    return [*first, *second]


def _load_previous_match_keys(path: Path) -> dict[str, set[str]]:
    body = json.loads(path.read_text(encoding="utf-8"))
    loaded: dict[str, set[str]] = {}
    for row in body.get("golds") or []:
        matches = {
            str(item["key"])
            for item in row.get("judgments") or []
            if isinstance(item, dict) and item.get("label") == MATCH
        }
        if not matches:
            matches = set(row.get("true_match_keys") or []) | set(row.get("false_match_keys") or [])
        loaded[str(row["gold_id"])] = matches
    return loaded


def _optional_sum(left: object, right: object) -> float | int | None:
    if left is None and right is None:
        return None
    if left is None:
        return right if isinstance(right, (int, float)) else None
    if right is None:
        return left if isinstance(left, (int, float)) else None
    if isinstance(left, int) and isinstance(right, int):
        return left + right
    return float(left) + float(right)


def _reference_true_matches_for(gold_id: str) -> int:
    golds = (load_cerebras_output_baseline().get("headline") or {}).get("golds") or []
    for row in golds:
        if row.get("gold_id") == gold_id:
            return int(round(float(row["candidate_recall"]) * _frozen_relevant(gold_id)))
    raise ValueError(f"missing output v1 row for {gold_id}")
