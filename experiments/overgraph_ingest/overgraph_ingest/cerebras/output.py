"""Reasoned versus minimal Cerebras output. Same frozen top-50. No new retrieval."""

from __future__ import annotations

import json
import time
from pathlib import Path

from overgraph_ingest.cerebras.client import CerebrasClient, Completer
from overgraph_ingest.cerebras.evaluate import relevant_documents, relevant_keys, score_rerank
from overgraph_ingest.cerebras.prompt import (
    MINIMAL,
    REASONED,
    TASK,
    Candidate,
    build_messages,
    parse_minimal,
)
from overgraph_ingest.cerebras.run import (
    CEREBRAS_ID,
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
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION
from overgraph_ingest.retrieval.index import StoredUnit

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ID = "phase2-cerebras-output-v1"
OUTPUT_PATH = ROOT / "baselines" / f"{OUTPUT_ID}.json"
DEFAULT_FROZEN = ROOT / "data" / "cerebras-rerank-v1.json"


def hydrate_candidates(
    judgments: list[dict[str, object]], units_by_key: dict[str, StoredUnit]
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for index, row in enumerate(judgments, start=1):
        key = str(row["key"])
        unit = units_by_key[key]
        candidates.append(
            Candidate(
                short_id=str(row.get("id") or f"c{index:02d}"),
                key=key,
                relative_path=unit.relative_path,
                rank=index,
                text=unit.text,
            )
        )
    return candidates


def run_cerebras_output(
    *,
    frozen_path: Path | None = None,
    db_path: Path | None = None,
    gold_dir: Path | None = None,
    dense_dimension: int = 3072,
    cerebras_api_key: str | None = None,
    cerebras_base_url: str = DEFAULT_BASE_URL,
    cerebras_model: str = DEFAULT_MODEL,
    client: Completer | None = None,
) -> dict[str, object]:
    source = frozen_path or DEFAULT_FROZEN
    frozen = json.loads(source.read_text(encoding="utf-8"))
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
        model=cerebras_model,
    )
    started = time.perf_counter()
    rows: list[dict[str, object]] = []
    for reference in frozen.get("golds") or []:
        gold = golds[str(reference["gold_id"])]
        candidates = hydrate_candidates(list(reference["judgments"]), units_by_key)
        if len(candidates) != int(frozen.get("k") or len(candidates)):
            raise ValueError(f"{gold.id} frozen list is not k={frozen.get('k')}")
        messages = build_messages(gold.query, candidates, variant=MINIMAL)
        reply = completer.complete(messages)
        parsed, errors = parse_minimal(json.loads(reply.text), candidates)
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
        metrics["retrieval_seconds"] = 0.0
        metrics["ttft_seconds"] = reply.ttft_seconds
        metrics["model_seconds"] = reply.completion_seconds
        metrics["prompt_tokens"] = reply.prompt_tokens
        metrics["completion_tokens"] = reply.completion_tokens
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
        metrics["reference"] = _reference_row(reference)
        metrics["delta"] = {
            "precision": metrics["precision"] - float(reference["precision"]),
            "candidate_recall": metrics["candidate_recall"]
            - float(reference["candidate_recall"]),
            "completion_tokens": _delta_int(
                metrics["completion_tokens"], reference.get("completion_tokens")
            ),
            "ttft_seconds": _delta_float(metrics["ttft_seconds"], reference.get("ttft_seconds")),
            "model_seconds": _delta_float(
                metrics["model_seconds"], reference.get("model_seconds")
            ),
        }
        rows.append(metrics)
    return {
        "operation": "rerank",
        "experiment": "cerebras_output_v1",
        "task": TASK,
        "reference_experiment": CEREBRAS_ID,
        "reference_path": str(source),
        "same_frozen_top50": True,
        "no_new_retrieval": True,
        "applied_to_v3": False,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "no_coverage_controller": True,
        "no_proof_evaluator": True,
        "uncertain_is_not_match": True,
        "same_mapping": GOLD_MAP_VERSION,
        "quality_reference": QUALITY_REFERENCE,
        "k": frozen.get("k"),
        "model": cerebras_model,
        "variants": {REASONED: "id_label_reason", MINIMAL: "match_and_uncertain_ids"},
        "golds": rows,
        "wall_seconds": time.perf_counter() - started,
        "summary": {
            **_summary(rows),
            "total_id_errors": _sum(rows, "id_errors") or 0,
            "mean_precision_delta": _mean([row["delta"] for row in rows], "precision"),
            "mean_candidate_recall_delta": _mean(
                [row["delta"] for row in rows], "candidate_recall"
            ),
            "total_completion_token_delta": _sum(
                [row["delta"] for row in rows], "completion_tokens"
            ),
        },
    }


def freeze_cerebras_output(payload: dict[str, object] | None = None) -> dict[str, object]:
    body = payload or run_cerebras_output()
    return {
        "id": OUTPUT_ID,
        "label": (
            "Frozen: Cerebras output ablation on the same hybrid top-50. "
            "Minimal MATCH/UNCERTAIN ids versus reasoned judgments. "
            "Does not replace C@8 or the reasoned rerank freeze. "
            "24/53 remains the quality reference."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_replace_cerebras_rerank": True,
        "applied_to_v3": False,
        "same_frozen_top50": True,
        "no_new_retrieval": True,
        "task": TASK,
        "headline": {
            "quality_reference": body.get("quality_reference"),
            "k": body.get("k"),
            "model": body.get("model"),
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
                    "completion_tokens": row.get("completion_tokens"),
                    "ttft_seconds": row.get("ttft_seconds"),
                    "model_seconds": row.get("model_seconds"),
                    "delta": row.get("delta"),
                }
                for row in body.get("golds") or []
            ],
        },
    }


def write_cerebras_output(
    payload: dict[str, object] | None = None,
    path: Path | None = None,
) -> Path:
    target = path or OUTPUT_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    body = payload or run_cerebras_output()
    target.write_text(
        json.dumps(freeze_cerebras_output(body), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _reference_row(row: dict[str, object]) -> dict[str, object]:
    return {
        "precision": row.get("precision"),
        "candidate_recall": row.get("candidate_recall"),
        "completion_tokens": row.get("completion_tokens"),
        "ttft_seconds": row.get("ttft_seconds"),
        "model_seconds": row.get("model_seconds"),
        "match": row.get("match"),
        "uncertain": row.get("uncertain"),
    }


def _visible_json_chars(row: dict[str, object]) -> int:
    judgments = row.get("judgments") or []
    match_ids = [
        str(item["id"])
        for item in judgments
        if isinstance(item, dict) and item.get("label") == "MATCH"
    ]
    uncertain_ids = [
        str(item["id"])
        for item in judgments
        if isinstance(item, dict) and item.get("label") == "UNCERTAIN"
    ]
    return len(json.dumps({"match": match_ids, "uncertain": uncertain_ids}, separators=(",", ":")))


def _delta_int(left: int | None, right: object) -> int | None:
    if left is None or right is None:
        return None
    return left - int(right)


def _delta_float(left: float | None, right: object) -> float | None:
    if left is None or right is None:
        return None
    return left - float(right)
