"""Qwen on the frozen top-50 and minimal JSON. No new retrieval. No proof."""

from __future__ import annotations

import json
import time
from pathlib import Path

from overgraph_ingest.cerebras.client import CerebrasClient, Completer
from overgraph_ingest.cerebras.evaluate import relevant_documents, relevant_keys, score_rerank
from overgraph_ingest.cerebras.output import (
    DEFAULT_FROZEN,
    hydrate_candidates,
    _delta_float,
    _delta_int,
    _visible_json_chars,
)
from overgraph_ingest.cerebras.pricing import (
    RATE_CARD_DATE,
    RATE_CARD_SOURCE,
    cost_usd,
)
from overgraph_ingest.cerebras.prompt import MINIMAL, TASK, build_messages, parse_minimal
from overgraph_ingest.cerebras.run import (
    DEFAULT_BASE_URL,
    DEFAULT_DB,
    DEFAULT_GOLD_DIR,
    _mean,
    _sum,
    _summary,
)
from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE
from overgraph_ingest.coverage.run import _golds
from overgraph_ingest.graph.writer import GraphWriter, open_database, resolve_dimension
from overgraph_ingest.jev.candidates import load_graph_context
from overgraph_ingest.retrieval.conclusions import load_cerebras_output_baseline
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION

ROOT = Path(__file__).resolve().parents[2]
QWEN_ID = "phase2-cerebras-qwen-v1"
QWEN_PATH = ROOT / "baselines" / f"{QWEN_ID}.json"
QWEN_MODEL = "qwen-3.8-27b"
QWEN_REASONING_EFFORT = "low"
QWEN_MAX_COMPLETION_TOKENS = 8192
REFERENCE_ID = "phase2-cerebras-output-v1"
REFERENCE_MODEL = "gpt-oss-120b"


def run_cerebras_qwen(
    *,
    frozen_path: Path | None = None,
    reference_path: Path | None = None,
    db_path: Path | None = None,
    gold_dir: Path | None = None,
    dense_dimension: int = 3072,
    cerebras_api_key: str | None = None,
    cerebras_base_url: str = DEFAULT_BASE_URL,
    client: Completer | None = None,
) -> dict[str, object]:
    source = frozen_path or DEFAULT_FROZEN
    frozen = json.loads(source.read_text(encoding="utf-8"))
    reference = _reference_rows(reference_path)
    golds = {gold.id: gold for gold in _golds(None, gold_dir or DEFAULT_GOLD_DIR)}
    target = db_path or DEFAULT_DB
    dimension = resolve_dimension(target, dense_dimension)
    db = open_database(target, dimension)
    try:
        units = load_graph_context(GraphWriter(db, batch_size=500)).units
    finally:
        db.close()
    units_by_key = {unit.key: unit for unit in units}
    completer = client or CerebrasClient(
        api_key=cerebras_api_key or "",
        base_url=cerebras_base_url,
        model=QWEN_MODEL,
        timeout_seconds=180.0,
        max_completion_tokens=QWEN_MAX_COMPLETION_TOKENS,
        reasoning_effort=QWEN_REASONING_EFFORT,
    )
    started = time.perf_counter()
    rows: list[dict[str, object]] = []
    for candidate_row in frozen.get("golds") or []:
        gold = golds[str(candidate_row["gold_id"])]
        baseline = reference[gold.id]
        candidates = hydrate_candidates(list(candidate_row["judgments"]), units_by_key)
        if len(candidates) != int(frozen.get("k") or len(candidates)):
            raise ValueError(f"{gold.id} frozen list is not k={frozen.get('k')}")
        messages = build_messages(gold.query, candidates, variant=MINIMAL)
        reply = completer.complete(messages)
        parsed, errors = parse_minimal(json.loads(reply.text), candidates)
        if reply.prompt_tokens is None or reply.completion_tokens is None:
            raise ValueError(f"{gold.id} is missing token counts")
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
        metrics["variant"] = MINIMAL
        metrics["model"] = QWEN_MODEL
        metrics["retrieval_seconds"] = 0.0
        metrics["ttft_seconds"] = reply.ttft_seconds
        metrics["model_seconds"] = reply.completion_seconds
        metrics["prompt_tokens"] = reply.prompt_tokens
        metrics["completion_tokens"] = reply.completion_tokens
        metrics["reasoning_tokens"] = reply.reasoning_tokens
        metrics["finish_reason"] = reply.finish_reason
        metrics["cost_usd"] = cost_usd(QWEN_MODEL, reply.prompt_tokens, reply.completion_tokens)
        metrics["invented_ids"] = errors["invented"]
        metrics["duplicate_ids"] = errors["duplicates"]
        metrics["id_errors"] = len(errors["invented"]) + len(errors["duplicates"])
        metrics["judgments"] = [
            {
                "id": row.short_id,
                "key": row.key,
                "label": row.label,
            }
            for row in parsed
        ]
        metrics["reference"] = {
            "experiment": REFERENCE_ID,
            "model": REFERENCE_MODEL,
            "precision": baseline.get("precision"),
            "candidate_recall": baseline.get("candidate_recall"),
            "completion_tokens": baseline.get("completion_tokens"),
            "ttft_seconds": baseline.get("ttft_seconds"),
            "model_seconds": baseline.get("model_seconds"),
            "match": baseline.get("match"),
            "uncertain": baseline.get("uncertain"),
        }
        metrics["delta"] = {
            "precision": metrics["precision"] - float(baseline["precision"]),
            "candidate_recall": metrics["candidate_recall"]
            - float(baseline["candidate_recall"]),
            "completion_tokens": _delta_int(
                metrics["completion_tokens"], baseline.get("completion_tokens")
            ),
            "ttft_seconds": _delta_float(metrics["ttft_seconds"], baseline.get("ttft_seconds")),
            "model_seconds": _delta_float(
                metrics["model_seconds"], baseline.get("model_seconds")
            ),
        }
        rows.append(metrics)
    prompt_total = _sum(rows, "prompt_tokens") or 0
    completion_total = _sum(rows, "completion_tokens") or 0
    return {
        "operation": "rerank",
        "experiment": "cerebras_qwen_v1",
        "task": TASK,
        "variant": MINIMAL,
        "reference_experiment": REFERENCE_ID,
        "reference_model": REFERENCE_MODEL,
        "candidate_source": str(source),
        "same_frozen_top50": True,
        "same_minimal_json": True,
        "no_new_retrieval": True,
        "one_call_per_question": True,
        "applied_to_v3": False,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_replace_cerebras_rerank": True,
        "does_not_replace_cerebras_output": True,
        "no_coverage_controller": True,
        "no_proof_evaluator": True,
        "uncertain_is_not_match": True,
        "same_mapping": GOLD_MAP_VERSION,
        "quality_reference": QUALITY_REFERENCE,
        "k": frozen.get("k"),
        "model": QWEN_MODEL,
        "reasoning_effort": QWEN_REASONING_EFFORT,
        "max_completion_tokens": QWEN_MAX_COMPLETION_TOKENS,
        "default_reasoning_emits_no_json": True,
        "rate_card_date": RATE_CARD_DATE,
        "rate_card_source": RATE_CARD_SOURCE,
        "golds": rows,
        "wall_seconds": time.perf_counter() - started,
        "summary": {
            **_summary(rows),
            "total_id_errors": _sum(rows, "id_errors") or 0,
            "total_reasoning_tokens": _sum(rows, "reasoning_tokens"),
            "cost_usd": cost_usd(QWEN_MODEL, prompt_total, completion_total),
            "reference_cost_usd": _reference_cost(reference_path),
            "mean_precision_delta": _mean([row["delta"] for row in rows], "precision"),
            "mean_candidate_recall_delta": _mean(
                [row["delta"] for row in rows], "candidate_recall"
            ),
            "total_completion_token_delta": _sum(
                [row["delta"] for row in rows], "completion_tokens"
            ),
        },
    }


def freeze_cerebras_qwen(payload: dict[str, object] | None = None) -> dict[str, object]:
    body = payload or run_cerebras_qwen()
    return {
        "id": QWEN_ID,
        "label": (
            "Negative experiment: Cerebras Qwen 3.8 27B is rejected for naive "
            "rerank. Same quality as gpt-oss output v1, slower and three times "
            "the cost. Unset Qwen reasoning spent 40k tokens without JSON. "
            "Does not replace C@8 or output v1. 24/53 remains the quality reference."
        ),
        "do_not_overwrite": True,
        "verdict": "rejected_for_naive_rerank",
        "do_not_deploy": True,
        "best_naive_rerank": REFERENCE_ID,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_replace_cerebras_rerank": True,
        "does_not_replace_cerebras_output": True,
        "applied_to_v3": False,
        "same_frozen_top50": True,
        "same_minimal_json": True,
        "no_new_retrieval": True,
        "task": TASK,
        "headline": {
            "quality_reference": body.get("quality_reference"),
            "k": body.get("k"),
            "model": body.get("model"),
            "reasoning_effort": body.get("reasoning_effort"),
            "reference_model": body.get("reference_model"),
            "rate_card_date": body.get("rate_card_date"),
            "summary": {
                **(body.get("summary") or {}),
                "total_visible_json_chars": sum(
                    _visible_json_chars(row) for row in body.get("golds") or []
                ),
            },
            "golds": [
                {
                    "gold_id": row.get("gold_id"),
                    "precision": row.get("precision"),
                    "candidate_recall": row.get("candidate_recall"),
                    "match": row.get("match"),
                    "uncertain": row.get("uncertain"),
                    "id_errors": row.get("id_errors"),
                    "visible_json_chars": _visible_json_chars(row),
                    "prompt_tokens": row.get("prompt_tokens"),
                    "completion_tokens": row.get("completion_tokens"),
                    "reasoning_tokens": row.get("reasoning_tokens"),
                    "cost_usd": row.get("cost_usd"),
                    "ttft_seconds": row.get("ttft_seconds"),
                    "model_seconds": row.get("model_seconds"),
                    "delta": row.get("delta"),
                }
                for row in body.get("golds") or []
            ],
        },
    }


def write_cerebras_qwen(
    payload: dict[str, object] | None = None,
    path: Path | None = None,
) -> Path:
    target = path or QWEN_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    body = payload or run_cerebras_qwen()
    target.write_text(
        json.dumps(freeze_cerebras_qwen(body), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _reference_rows(path: Path | None) -> dict[str, dict[str, object]]:
    frozen = load_cerebras_output_baseline(path)
    rows = {
        str(row["gold_id"]): row
        for row in (frozen.get("headline") or {}).get("golds") or []
    }
    if not rows:
        raise ValueError("output v1 baseline is missing headline golds")
    return rows


def _reference_cost(path: Path | None) -> float | None:
    frozen = load_cerebras_output_baseline(path)
    summary = (frozen.get("headline") or {}).get("summary") or {}
    prompt = summary.get("total_prompt_tokens")
    completion = summary.get("total_completion_tokens")
    if prompt is None or completion is None:
        return None
    return cost_usd(REFERENCE_MODEL, int(prompt), int(completion))
