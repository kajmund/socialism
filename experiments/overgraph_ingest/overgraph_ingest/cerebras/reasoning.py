"""GPT-OSS reasoning ablation. Same frozen top-50 and minimal JSON. Off is unsupported."""

from __future__ import annotations

import json
import time
from pathlib import Path

from overgraph_ingest.cerebras.client import CerebrasClient, Completer
from overgraph_ingest.cerebras.evaluate import (
    relevant_documents,
    relevant_keys,
    score_negations,
    score_rerank,
    span_keys,
)
from overgraph_ingest.cerebras.output import (
    DEFAULT_FROZEN,
    hydrate_candidates,
    _delta_float,
    _delta_int,
    _visible_json_chars,
)
from overgraph_ingest.cerebras.pricing import RATE_CARD_DATE, RATE_CARD_SOURCE, cost_usd
from overgraph_ingest.cerebras.prompt import (
    MINIMAL,
    TASK,
    Candidate,
    ParsedJudgment,
    build_messages,
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
from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE
from overgraph_ingest.coverage.run import _golds
from overgraph_ingest.graph.writer import GraphWriter, open_database, resolve_dimension
from overgraph_ingest.jev.candidates import load_graph_context
from overgraph_ingest.retrieval.conclusions import load_cerebras_output_baseline
from overgraph_ingest.retrieval.gold import RetrievalGold
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION
from overgraph_ingest.retrieval.index import StoredUnit

ROOT = Path(__file__).resolve().parents[2]
REASONING_ID = "phase2-cerebras-reasoning-v1"
REASONING_PATH = ROOT / "baselines" / f"{REASONING_ID}.json"
CURRENT_ID = "phase2-cerebras-output-v1"
CURRENT_LIVE = ROOT / "data" / "cerebras-output-v1.json"
CURRENT_SETTING = "unset_default_medium"
LOWEST_SUPPORTED = "low"
REASONING_OFF_SUPPORTED = False
GPT_OSS_REASONING = ("low", "medium", "high")


def run_cerebras_reasoning(
    *,
    frozen_path: Path | None = None,
    current_path: Path | None = None,
    db_path: Path | None = None,
    gold_dir: Path | None = None,
    dense_dimension: int = 3072,
    cerebras_api_key: str | None = None,
    cerebras_base_url: str = DEFAULT_BASE_URL,
    client: Completer | None = None,
) -> dict[str, object]:
    source = frozen_path or DEFAULT_FROZEN
    frozen = json.loads(source.read_text(encoding="utf-8"))
    current_live = json.loads((current_path or CURRENT_LIVE).read_text(encoding="utf-8"))
    current_by_id = {str(row["gold_id"]): row for row in current_live.get("golds") or []}
    reference = _current_headline()
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
        model=DEFAULT_MODEL,
        reasoning_effort=LOWEST_SUPPORTED,
    )
    started = time.perf_counter()
    current_rows: list[dict[str, object]] = []
    low_rows: list[dict[str, object]] = []
    for candidate_row in frozen.get("golds") or []:
        gold = golds[str(candidate_row["gold_id"])]
        candidates = hydrate_candidates(list(candidate_row["judgments"]), units_by_key)
        if len(candidates) != int(frozen.get("k") or len(candidates)):
            raise ValueError(f"{gold.id} frozen list is not k={frozen.get('k')}")
        hard_keys = span_keys(units, gold.hard_negatives)
        watch_keys = span_keys(units, gold.watch_negatives)
        saved = current_by_id[gold.id]
        current_rows.append(
            _score_saved(
                gold=gold,
                units=units,
                candidates=candidates,
                saved=saved,
                hard_keys=hard_keys,
                watch_keys=watch_keys,
                headline=reference[gold.id],
            )
        )
        messages = build_messages(gold.query, candidates, variant=MINIMAL)
        reply = completer.complete(messages)
        parsed, errors = parse_minimal(json.loads(reply.text), candidates)
        if reply.prompt_tokens is None or reply.completion_tokens is None:
            raise ValueError(f"{gold.id} is missing token counts")
        low_rows.append(
            _score_live(
                gold=gold,
                units=units,
                candidates=candidates,
                parsed=parsed,
                errors=errors,
                reply=reply,
                hard_keys=hard_keys,
                watch_keys=watch_keys,
                reference=current_rows[-1],
            )
        )
    return {
        "operation": "rerank",
        "experiment": "cerebras_reasoning_v1",
        "task": TASK,
        "variant": MINIMAL,
        "model": DEFAULT_MODEL,
        "current_experiment": CURRENT_ID,
        "current_setting": CURRENT_SETTING,
        "reasoning_off_supported": REASONING_OFF_SUPPORTED,
        "lowest_supported": LOWEST_SUPPORTED,
        "supported_reasoning_effort": list(GPT_OSS_REASONING),
        "same_frozen_top50": True,
        "same_minimal_json": True,
        "no_new_retrieval": True,
        "current_was_not_rerun": True,
        "one_call_per_question": True,
        "applied_to_v3": False,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_replace_cerebras_output": True,
        "no_coverage_controller": True,
        "no_proof_evaluator": True,
        "uncertain_is_not_match": True,
        "same_mapping": GOLD_MAP_VERSION,
        "quality_reference": QUALITY_REFERENCE,
        "k": frozen.get("k"),
        "rate_card_date": RATE_CARD_DATE,
        "rate_card_source": RATE_CARD_SOURCE,
        "best_naive_rerank": CURRENT_ID,
        "variants": {
            CURRENT_SETTING: _variant_block(current_rows, DEFAULT_MODEL),
            LOWEST_SUPPORTED: _variant_block(low_rows, DEFAULT_MODEL),
        },
        "wall_seconds": time.perf_counter() - started,
        "summary": _compare_summary(current_rows, low_rows),
    }


def freeze_cerebras_reasoning(payload: dict[str, object] | None = None) -> dict[str, object]:
    body = payload or run_cerebras_reasoning()
    return {
        "id": REASONING_ID,
        "label": (
            "Frozen: GPT-OSS-120B reasoning ablation on the same hybrid top-50 "
            "and minimal JSON as output v1. Reasoning cannot be turned off. "
            "Lowest supported effort is low. Current unset/default medium was "
            "not re-run. Formulation presence, not proof. Does not replace C@8 "
            "or output v1. 24/53 remains the quality reference."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_replace_cerebras_output": True,
        "reasoning_off_supported": REASONING_OFF_SUPPORTED,
        "lowest_supported": LOWEST_SUPPORTED,
        "current_was_not_rerun": True,
        "applied_to_v3": False,
        "same_frozen_top50": True,
        "same_minimal_json": True,
        "no_new_retrieval": True,
        "task": TASK,
        "headline": {
            "quality_reference": body.get("quality_reference"),
            "k": body.get("k"),
            "model": body.get("model"),
            "current_setting": body.get("current_setting"),
            "lowest_supported": body.get("lowest_supported"),
            "reasoning_off_supported": body.get("reasoning_off_supported"),
            "rate_card_date": body.get("rate_card_date"),
            "summary": body.get("summary"),
            "variants": {
                name: _variant_headline(block)
                for name, block in (body.get("variants") or {}).items()
            },
        },
    }


def write_cerebras_reasoning(
    payload: dict[str, object] | None = None,
    path: Path | None = None,
) -> Path:
    target = path or REASONING_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    body = payload or run_cerebras_reasoning()
    target.write_text(
        json.dumps(freeze_cerebras_reasoning(body), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _score_saved(
    *,
    gold: RetrievalGold,
    units: list[StoredUnit],
    candidates: list[Candidate],
    saved: dict[str, object],
    hard_keys: set[str],
    watch_keys: set[str],
    headline: dict[str, object],
) -> dict[str, object]:
    parsed = _judgments_from_saved(list(saved.get("judgments") or []), candidates)
    return _metrics(
        gold=gold,
        units=units,
        candidates=candidates,
        parsed=parsed,
        errors={"invented": [], "duplicates": []},
        setting=CURRENT_SETTING,
        retrieval_seconds=0.0,
        ttft_seconds=headline.get("ttft_seconds"),
        model_seconds=headline.get("model_seconds"),
        prompt_tokens=saved.get("prompt_tokens"),
        completion_tokens=headline.get("completion_tokens"),
        reasoning_tokens=saved.get("reasoning_tokens"),
        hard_keys=hard_keys,
        watch_keys=watch_keys,
        reference=None,
    )


def _score_live(
    *,
    gold: RetrievalGold,
    units: list[StoredUnit],
    candidates: list[Candidate],
    parsed: list[ParsedJudgment],
    errors: dict[str, list[str]],
    reply: object,
    hard_keys: set[str],
    watch_keys: set[str],
    reference: dict[str, object],
) -> dict[str, object]:
    return _metrics(
        gold=gold,
        units=units,
        candidates=candidates,
        parsed=parsed,
        errors=errors,
        setting=LOWEST_SUPPORTED,
        retrieval_seconds=0.0,
        ttft_seconds=getattr(reply, "ttft_seconds"),
        model_seconds=getattr(reply, "completion_seconds"),
        prompt_tokens=getattr(reply, "prompt_tokens"),
        completion_tokens=getattr(reply, "completion_tokens"),
        reasoning_tokens=getattr(reply, "reasoning_tokens"),
        hard_keys=hard_keys,
        watch_keys=watch_keys,
        reference=reference,
    )


def _metrics(
    *,
    gold: RetrievalGold,
    units: list[StoredUnit],
    candidates: list[Candidate],
    parsed: list[ParsedJudgment],
    errors: dict[str, list[str]],
    setting: str,
    retrieval_seconds: float,
    ttft_seconds: object,
    model_seconds: object,
    prompt_tokens: object,
    completion_tokens: object,
    reasoning_tokens: object,
    hard_keys: set[str],
    watch_keys: set[str],
    reference: dict[str, object] | None,
) -> dict[str, object]:
    corpus_keys = relevant_keys(units, gold)
    corpus_docs = relevant_documents(units, gold, corpus_keys)
    metrics = score_rerank(
        gold=gold,
        candidates=candidates,
        judgments=parsed,
        corpus_relevant_keys=corpus_keys,
        corpus_relevant_docs=corpus_docs,
    )
    metrics.update(
        score_negations(
            candidates=candidates,
            judgments=parsed,
            hard_keys=hard_keys,
            watch_keys=watch_keys,
        )
    )
    prompt = None if prompt_tokens is None else int(prompt_tokens)
    completion = None if completion_tokens is None else int(completion_tokens)
    metrics["query"] = gold.query
    metrics["variant"] = MINIMAL
    metrics["setting"] = setting
    metrics["retrieval_seconds"] = retrieval_seconds
    metrics["ttft_seconds"] = ttft_seconds
    metrics["model_seconds"] = model_seconds
    metrics["prompt_tokens"] = prompt
    metrics["completion_tokens"] = completion
    metrics["reasoning_tokens"] = reasoning_tokens
    metrics["cost_usd"] = (
        None if prompt is None or completion is None else cost_usd(DEFAULT_MODEL, prompt, completion)
    )
    metrics["invented_ids"] = errors["invented"]
    metrics["duplicate_ids"] = errors["duplicates"]
    metrics["id_errors"] = len(errors["invented"]) + len(errors["duplicates"])
    metrics["judgments"] = [
        {"id": row.short_id, "key": row.key, "label": row.label} for row in parsed
    ]
    if reference is not None:
        metrics["delta"] = {
            "precision": metrics["precision"] - float(reference["precision"]),
            "candidate_recall": metrics["candidate_recall"]
            - float(reference["candidate_recall"]),
            "hard_negatives_matched": int(metrics["hard_negatives_matched"])
            - int(reference["hard_negatives_matched"]),
            "watch_negatives_matched": int(metrics["watch_negatives_matched"])
            - int(reference["watch_negatives_matched"]),
            "completion_tokens": _delta_int(completion, reference.get("completion_tokens")),
            "reasoning_tokens": _delta_int(
                None if reasoning_tokens is None else int(reasoning_tokens),
                reference.get("reasoning_tokens"),
            ),
            "ttft_seconds": _delta_float(
                None if ttft_seconds is None else float(ttft_seconds),
                reference.get("ttft_seconds"),
            ),
            "model_seconds": _delta_float(
                None if model_seconds is None else float(model_seconds),
                reference.get("model_seconds"),
            ),
        }
    return metrics


def _judgments_from_saved(
    rows: list[dict[str, object]], candidates: list[Candidate]
) -> list[ParsedJudgment]:
    by_id = {item.short_id: item for item in candidates}
    parsed: list[ParsedJudgment] = []
    for row in rows:
        short_id = str(row["id"])
        item = by_id[short_id]
        parsed.append(
            ParsedJudgment(
                short_id=short_id,
                key=item.key,
                label=str(row["label"]),
                reason="",
            )
        )
    if len(parsed) != len(candidates):
        raise ValueError("saved judgments do not cover the frozen candidate list")
    return parsed


def _current_headline() -> dict[str, dict[str, object]]:
    frozen = load_cerebras_output_baseline()
    return {
        str(row["gold_id"]): row
        for row in (frozen.get("headline") or {}).get("golds") or []
    }


def _variant_block(rows: list[dict[str, object]], model: str) -> dict[str, object]:
    prompt_total = _sum(rows, "prompt_tokens") or 0
    completion_total = _sum(rows, "completion_tokens") or 0
    return {
        "model": model,
        "golds": rows,
        "summary": {
            **_summary(rows),
            "total_id_errors": _sum(rows, "id_errors") or 0,
            "total_reasoning_tokens": _sum(rows, "reasoning_tokens"),
            "total_hard_negatives_matched": _sum(rows, "hard_negatives_matched") or 0,
            "total_watch_negatives_matched": _sum(rows, "watch_negatives_matched") or 0,
            "total_visible_json_chars": sum(_visible_json_chars(row) for row in rows),
            "cost_usd": cost_usd(model, prompt_total, completion_total),
        },
    }


def _variant_headline(block: dict[str, object]) -> dict[str, object]:
    return {
        "summary": block.get("summary"),
        "golds": [
            {
                "gold_id": row.get("gold_id"),
                "precision": row.get("precision"),
                "candidate_recall": row.get("candidate_recall"),
                "match": row.get("match"),
                "uncertain": row.get("uncertain"),
                "hard_negatives_in_candidates": row.get("hard_negatives_in_candidates"),
                "hard_negatives_matched": row.get("hard_negatives_matched"),
                "watch_negatives_matched": row.get("watch_negatives_matched"),
                "id_errors": row.get("id_errors"),
                "completion_tokens": row.get("completion_tokens"),
                "reasoning_tokens": row.get("reasoning_tokens"),
                "cost_usd": row.get("cost_usd"),
                "ttft_seconds": row.get("ttft_seconds"),
                "model_seconds": row.get("model_seconds"),
                "delta": row.get("delta"),
            }
            for row in block.get("golds") or []
        ],
    }


def _compare_summary(
    current_rows: list[dict[str, object]], low_rows: list[dict[str, object]]
) -> dict[str, object]:
    current = _variant_block(current_rows, DEFAULT_MODEL)["summary"]
    low = _variant_block(low_rows, DEFAULT_MODEL)["summary"]
    return {
        "current": current,
        "low": low,
        "mean_precision_delta": _mean([row["delta"] for row in low_rows], "precision"),
        "mean_candidate_recall_delta": _mean(
            [row["delta"] for row in low_rows], "candidate_recall"
        ),
        "total_hard_negative_delta": _sum(
            [row["delta"] for row in low_rows], "hard_negatives_matched"
        ),
        "total_completion_token_delta": _sum(
            [row["delta"] for row in low_rows], "completion_tokens"
        ),
        "reasoning_off_supported": REASONING_OFF_SUPPORTED,
    }
