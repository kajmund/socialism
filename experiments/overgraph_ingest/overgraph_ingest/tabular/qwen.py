"""Qwen Low on the frozen Tabular 100 cells. No new retrieval. No navigation."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from overgraph_ingest.cerebras.client import CerebrasClient, Completer
from overgraph_ingest.cerebras.pricing import cost_usd
from overgraph_ingest.cerebras.qwen import QWEN_MAX_COMPLETION_TOKENS, QWEN_MODEL, QWEN_REASONING_EFFORT
from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE
from overgraph_ingest.graph.writer import GraphWriter, open_database, resolve_dimension
from overgraph_ingest.jev.candidates import GraphContext, context_from_units, load_graph_context
from overgraph_ingest.retrieval.conclusions import load_tabular_review_baseline
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.search import SearchHit
from overgraph_ingest.tabular.cerebras_io import answer_with_cerebras
from overgraph_ingest.tabular.contract import ANSWERED, UNCERTAIN, CellResult, SourceRef, require_status, source_ref
from overgraph_ingest.tabular.evaluate import compare_variants, error_examples, headline, score_cell, summarize
from overgraph_ingest.tabular.gold import USER_QUESTIONS, cell_relevant_keys, document_short_id, load_tabular_golds
from overgraph_ingest.tabular.serialize import cell_payload

ROOT = Path(__file__).resolve().parents[2]
TABULAR_QWEN_ID = "phase2-tabular-qwen-v1"
TABULAR_QWEN_PATH = ROOT / "baselines" / f"{TABULAR_QWEN_ID}.json"
DEFAULT_DB = ROOT / "data" / "extra-overgraph-phase2"
DEFAULT_GOLD_DIR = ROOT / "retrieval_gold"
VARIANT_Q = "Q"
SOURCE_VARIANT = "C"


def frozen_c_cells(
    payload: dict[str, object],
    *,
    expected: int = 100,
) -> list[dict[str, object]]:
    cells = [
        row
        for row in payload.get("cells") or []
        if isinstance(row, dict) and row.get("variant") == SOURCE_VARIANT
    ]
    if len(cells) != expected:
        raise ValueError(f"frozen tabular C cells must be {expected}, got {len(cells)}")
    return cells


def run_tabular_qwen(
    *,
    frozen_path: Path | None = None,
    db_path: Path | None = None,
    gold_dir: Path | None = None,
    dense_dimension: int = 3072,
    cerebras_api_key: str | None = None,
    cerebras_base_url: str = "https://api.cerebras.ai/v1",
    client: Completer | None = None,
    units: list[StoredUnit] | None = None,
    structures: dict[str, dict[str, object]] | None = None,
    frozen: dict[str, object] | None = None,
    expected_cells: int = 100,
) -> dict[str, object]:
    source = frozen or _load_frozen(frozen_path)
    cells = frozen_c_cells(source, expected=expected_cells)
    golds = {gold.id: gold for gold in load_tabular_golds(gold_dir or DEFAULT_GOLD_DIR)}
    graph = _load_context(
        db_path=db_path,
        dense_dimension=dense_dimension,
        units=units,
        structures=structures,
    )
    by_key = graph.by_key()
    completer = client or CerebrasClient(
        api_key=cerebras_api_key or "",
        base_url=cerebras_base_url,
        model=QWEN_MODEL,
        timeout_seconds=180.0,
        max_completion_tokens=QWEN_MAX_COMPLETION_TOKENS,
        reasoning_effort=QWEN_REASONING_EFFORT,
    )
    if QWEN_REASONING_EFFORT != "low":
        raise ValueError("tabular Qwen uses reasoning low")
    started = time.perf_counter()
    results: list[CellResult] = []
    scored: list[dict[str, object]] = []
    for row in cells:
        question_id = str(row["question_id"])
        relative_path = str(row["relative_path"])
        gold = golds[question_id]
        relevant = cell_relevant_keys(graph.units, gold, relative_path)
        hits = _hits(row, by_key)
        result = _answer_cell(
            row=row,
            hits=hits,
            units=graph.units,
            structures=graph.structures,
            completer=completer,
        )
        results.append(result)
        scored.append(score_cell(result, relevant))
        print(
            f"{VARIANT_Q} {result.document_id} {question_id} {result.status}",
            file=sys.stderr,
            flush=True,
        )
    qwen_summary = summarize(scored)
    frozen_scored = [
        row
        for row in source.get("scored") or []
        if isinstance(row, dict) and row.get("variant") in {"B", "C"}
    ]
    compared = compare_variants(frozen_scored + scored)
    cost = _cost(results)
    return {
        "operation": "tabular_qwen",
        "experiment": "tabular_qwen_v1",
        "task": "document_local_source_grounded_cell",
        "replay_of": "phase2-tabular-review-v1",
        "same_100_cells": True,
        "same_candidate_keys": True,
        "no_new_retrieval": True,
        "no_navigation": True,
        "no_jev": True,
        "applied_to_v3": False,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_replace_tabular_v1": True,
        "navigation_not_changed": True,
        "model": QWEN_MODEL,
        "reasoning_effort": QWEN_REASONING_EFFORT,
        "max_completion_tokens": QWEN_MAX_COMPLETION_TOKENS,
        "same_mapping": GOLD_MAP_VERSION,
        "quality_reference": QUALITY_REFERENCE,
        "selection_is_diagnostic": True,
        "selection_is_not_general_quality": True,
        "synchronous": True,
        "k": 5,
        "cells": [cell_payload(item) for item in results],
        "scored": scored,
        "qwen": qwen_summary,
        "comparison": compared,
        "versus": {
            "q_vs_b_cell_accuracy": _delta(qwen_summary, compared, "B", "cell_accuracy"),
            "q_vs_c_cell_accuracy": _delta(qwen_summary, compared, "C", "cell_accuracy"),
            "q_vs_b_answer_accuracy": _delta(qwen_summary, compared, "B", "answer_accuracy"),
            "q_vs_c_answer_accuracy": _delta(qwen_summary, compared, "C", "answer_accuracy"),
            "q_vs_b_citation_accuracy": _delta(qwen_summary, compared, "B", "citation_accuracy"),
            "q_vs_c_citation_accuracy": _delta(qwen_summary, compared, "C", "citation_accuracy"),
        },
        "headline": {
            **headline(compared, cost),
            "qwen_cell_accuracy": qwen_summary["cell_accuracy"],
            "qwen_answer_accuracy": qwen_summary["answer_accuracy"],
            "qwen_citation_accuracy": qwen_summary["citation_accuracy"],
            "model": QWEN_MODEL,
            "reasoning_effort": QWEN_REASONING_EFFORT,
        },
        "cost": cost,
        "errors": error_examples(results, scored),
        "wall_seconds": time.perf_counter() - started,
    }


def freeze_tabular_qwen(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": TABULAR_QWEN_ID,
        "label": (
            "Frozen: Qwen 3.8 27B reasoning low on the same 100 Tabular "
            "Review cells as phase2-tabular-review-v1. Same candidate "
            "keys. No new retrieval and no navigation. Does not replace "
            "C@8, Coverage v3, or tabular v1."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_replace_tabular_v1": True,
        "navigation_not_changed": True,
        "same_100_cells": True,
        "same_candidate_keys": True,
        "no_new_retrieval": True,
        "model": QWEN_MODEL,
        "reasoning_effort": QWEN_REASONING_EFFORT,
        "same_mapping": GOLD_MAP_VERSION,
        "selection_is_diagnostic": True,
        "headline": payload.get("headline"),
        "versus": payload.get("versus"),
        "qwen": payload.get("qwen"),
        "cost": payload.get("cost"),
        "errors": payload.get("errors"),
        "cells": payload.get("cells"),
        "scored": payload.get("scored"),
        "wall_seconds": payload.get("wall_seconds"),
    }


def write_tabular_qwen_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or TABULAR_QWEN_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_tabular_qwen(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _load_frozen(path: Path | None) -> dict[str, object]:
    if path is None:
        return load_tabular_review_baseline()
    return json.loads(path.read_text(encoding="utf-8"))


def _load_context(
    *,
    db_path: Path | None,
    dense_dimension: int,
    units: list[StoredUnit] | None,
    structures: dict[str, dict[str, object]] | None,
) -> GraphContext:
    if units is not None:
        return context_from_units(units, structures or {})
    target = db_path or DEFAULT_DB
    dimension = resolve_dimension(target, dense_dimension)
    db = open_database(target, dimension)
    try:
        return load_graph_context(GraphWriter(db, batch_size=500))
    finally:
        db.close()


def _hits(row: dict[str, object], by_key: dict[str, StoredUnit]) -> list[SearchHit]:
    retrieval = row.get("retrieval") or {}
    keys = [str(key) for key in (retrieval.get("candidate_keys") or [])]
    if not keys:
        raise ValueError(f"frozen cell {row.get('question_id')} is missing candidate keys")
    hits: list[SearchHit] = []
    for rank, key in enumerate(keys, start=1):
        unit = by_key.get(key)
        if unit is None:
            raise KeyError(f"frozen candidate {key} is missing from the database")
        if unit.relative_path != row["relative_path"]:
            raise ValueError(f"frozen candidate {key} leaked another document")
        hits.append(
            SearchHit(
                node_id=unit.node_id,
                key=unit.key,
                score=0.0,
                rank=rank,
                document_id=unit.document_id,
                relative_path=unit.relative_path,
                text=unit.text,
            )
        )
    return hits


def _answer_cell(
    *,
    row: dict[str, object],
    hits: list[SearchHit],
    units: list[StoredUnit],
    structures: dict[str, dict[str, object]],
    completer: Completer,
) -> CellResult:
    relative_path = str(row["relative_path"])
    question_id = str(row["question_id"])
    question = str(row.get("question") or USER_QUESTIONS[question_id])
    retrieval = dict(row.get("retrieval") or {})
    by_key = {unit.key: unit for unit in units}
    parsed = answer_with_cerebras(completer, user_question=question, hits=hits)
    status = require_status(parsed["status"])
    sources: list[SourceRef] = []
    notes = ""
    answer = parsed["answer"]
    source_ids: list[str] = []
    if status == ANSWERED:
        unit = by_key.get(parsed["source_unit_id"])
        if unit is None or unit.key not in {hit.key for hit in hits}:
            status = UNCERTAIN
            notes = "citation_failed"
            answer = ""
        else:
            ref = source_ref(
                unit,
                parsed["excerpt"],
                clause_number=str(structures.get(unit.structure_id, {}).get("clause_number") or ""),
            )
            if not ref.validated:
                status = UNCERTAIN
                notes = "citation_failed"
                answer = ""
            else:
                sources = [ref]
                source_ids = [unit.key]
    return CellResult(
        document_id=document_short_id(relative_path),
        relative_path=relative_path,
        question_id=question_id,
        question=question,
        variant=VARIANT_Q,
        status=status,
        answer=answer,
        source_unit_ids=source_ids,
        sources=sources,
        units_examined=len(hits),
        cerebras_calls=1,
        prompt_tokens=None if parsed.get("prompt_tokens") in {None, ""} else int(parsed["prompt_tokens"]),
        completion_tokens=None
        if parsed.get("completion_tokens") in {None, ""}
        else int(parsed["completion_tokens"]),
        retrieve_seconds=0.0,
        answer_seconds=float(parsed.get("seconds") or 0.0),
        cell_seconds=float(parsed.get("seconds") or 0.0),
        retrieval=retrieval,
        notes=notes,
    )


def _cost(cells: list[CellResult]) -> dict[str, object]:
    prompt = sum(item.prompt_tokens or 0 for item in cells)
    completion = sum(item.completion_tokens or 0 for item in cells)
    usd = cost_usd(QWEN_MODEL, prompt, completion) if prompt or completion else 0.0
    n = len(cells)
    return {
        "model": QWEN_MODEL,
        "reasoning_effort": QWEN_REASONING_EFFORT,
        "qwen_calls": n,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "qwen_usd": usd,
        "per_cell_usd": (usd / n) if n else 0.0,
        "per_100_cells_usd": (usd / n * 100) if n else 0.0,
        "jev_usd": None,
        "jev_cost_unknown": True,
    }


def _delta(
    qwen: dict[str, object],
    compared: dict[str, object],
    other: str,
    field: str,
) -> float | None:
    variants = compared.get("variants") or {}
    if other not in variants:
        return None
    return float(qwen[field]) - float(variants[other][field])
