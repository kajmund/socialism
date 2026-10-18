"""Encode A and B search texts. Rank dense. Do not call Jev."""

from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path

from overgraph_ingest.jev.candidates import GraphContext
from overgraph_ingest.retrieval.encode import (
    DENSE_DIMENSION,
    DENSE_MODEL,
    HashedDenseEncoder,
    build_dense_encoder,
)
from overgraph_ingest.retrieval.gold import RetrievalGold, matching_spans
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.search import exhaustive_rank
from overgraph_ingest.tabular.enrich import FIRST_RUN, ORIGINAL, STRUCTURE, search_texts
from overgraph_ingest.tabular.enrich_dev import (
    DEV_DOCUMENTS,
    DO_NOT_TUNE_CELLS,
    ENRICH_ID,
    development_cells,
)
from overgraph_ingest.tabular.gold import QUESTION_IDS, USER_QUESTIONS, load_tabular_golds
from overgraph_ingest.tabular.jev_io import P0_STATUS_INSTRUCTIONS
from overgraph_ingest.tabular.prompts import PROMPT_P0, instruction_for
from overgraph_ingest.tabular.run import DEFAULT_GOLD_DIR, _load_context
from overgraph_ingest.tabular.search import DEFAULT_K
from overgraph_ingest.tabular.user_eval import normalize
from overgraph_ingest.tabular.user_gold import UserCellGold

ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = ROOT / "eval"
ENRICH_RUN_ID = "phase2-tabular-enrich-run-v1"
ENRICH_RUN_PATH = ROOT / "baselines" / f"{ENRICH_RUN_ID}.json"
DENSE_BYTES = DENSE_DIMENSION * 4


def run_tabular_enrich(
    *,
    db_path: Path | None = None,
    gold_dir: Path | None = None,
    dense_dimension: int = DENSE_DIMENSION,
    openai_api_key: str | None = None,
    openai_base_url: str | None = None,
    dense_model: str = DENSE_MODEL,
    units: list[StoredUnit] | None = None,
    structures: dict[str, dict[str, object]] | None = None,
    context: GraphContext | None = None,
    dense=None,
    documents: tuple[str, ...] = DEV_DOCUMENTS,
    representations: tuple[str, ...] = FIRST_RUN,
    cells: tuple[UserCellGold, ...] | None = None,
    retrieval_golds: dict[str, RetrievalGold] | None = None,
) -> dict[str, object]:
    if instruction_for(PROMPT_P0) != P0_STATUS_INSTRUCTIONS:
        raise ValueError("enrich must leave P0 unchanged")
    if DEFAULT_K != 5:
        raise ValueError("tabular default k must stay 5")
    graph = context or _load_context(
        db_path=db_path,
        dense_dimension=dense_dimension,
        units=units,
        structures=structures,
    )
    local = [unit for unit in graph.units if unit.relative_path in set(documents)]
    if not local:
        raise ValueError("development documents missing from current ingest")
    encoder = dense or _dense_encoder(
        dense_model=dense_model,
        dense_dimension=dense_dimension,
        openai_api_key=openai_api_key,
        openai_base_url=openai_base_url,
    )
    golds = retrieval_golds or {
        gold.id: gold for gold in load_tabular_golds(gold_dir or DEFAULT_GOLD_DIR)
    }
    selected = [
        cell
        for cell in (cells or development_cells())
        if cell.relative_path in set(documents) and cell.answers
    ]
    started = time.perf_counter()
    query_started = time.perf_counter()
    question_vectors = {
        question_id: encoder.embed([USER_QUESTIONS[question_id]])[0]
        for question_id in QUESTION_IDS
    }
    query_seconds = time.perf_counter() - query_started
    query_tokens = _prompt_tokens(encoder, reset=True)
    variants: dict[str, dict[str, object]] = {}
    scored: dict[str, list[dict[str, object]]] = {}
    for name in representations:
        represent_started = time.perf_counter()
        texts = search_texts(name, local, graph.structures)
        represent_seconds = time.perf_counter() - represent_started
        embed_started = time.perf_counter()
        ordered_units = list(local)
        vectors = encoder.embed([texts[unit.key] for unit in ordered_units])
        embed_seconds = time.perf_counter() - embed_started
        indexed = [
            replace(unit, dense=vector, sparse=None)
            for unit, vector in zip(ordered_units, vectors, strict=True)
        ]
        by_path: dict[str, list[StoredUnit]] = {}
        for unit in indexed:
            by_path.setdefault(unit.relative_path, []).append(unit)
        missing_docs = sorted({cell.relative_path for cell in selected} - set(by_path))
        if missing_docs:
            raise ValueError(f"development documents missing units: {missing_docs}")
        rows = [
            score_enrich_cell(
                cell,
                by_path[cell.relative_path],
                question_vectors[cell.question_id],
                golds[cell.question_id],
            )
            for cell in selected
        ]
        scored[name] = rows
        variants[name] = {
            "representation": name,
            "summary": summarize_enrich(rows),
            "search_chars": sum(len(texts[unit.key]) for unit in ordered_units),
            "evidence_chars": sum(len(unit.text) for unit in ordered_units),
            "units": len(ordered_units),
            "dense_index_bytes": len(ordered_units) * DENSE_BYTES,
            "represent_seconds": represent_seconds,
            "embed_seconds": embed_seconds,
            "prompt_tokens": _prompt_tokens(encoder, reset=True),
        }
    return {
        "operation": "tabular_enrich_run",
        "experiment": ENRICH_RUN_ID,
        "gold_id": ENRICH_ID,
        "same_mapping": GOLD_MAP_VERSION,
        "does_not_run_jev": True,
        "does_not_run_cerebras": True,
        "does_not_change_ingest": True,
        "does_not_write_overgraph": True,
        "does_not_change_default_prompt": True,
        "does_not_change_default_hybrid": True,
        "search_is_not_evidence": True,
        "hypothesis_2_not_built": True,
        "do_not_tune_known_misses": True,
        "default_remains_d": True,
        "e_is_next_candidate": True,
        "strategy": "dense",
        "documents": list(documents),
        "spanned_cells": len(selected),
        "do_not_tune_cells": [
            {"relative_path": path, "question_id": question_id}
            for path, question_id in DO_NOT_TUNE_CELLS
        ],
        "variants": variants,
        "scored": scored,
        "headline": {name: variants[name]["summary"] for name in representations},
        "decision": decide_enrich(variants),
        "query_seconds": query_seconds,
        "query_tokens": query_tokens,
        "wall_seconds": time.perf_counter() - started,
        "prompt_tokens": query_tokens
        + sum(int(item["prompt_tokens"] or 0) for item in variants.values()),
    }


def score_enrich_cell(
    cell: UserCellGold,
    units: list[StoredUnit],
    dense_query: list[float],
    retrieval_gold,
) -> dict[str, object]:
    gold_keys = {
        unit.key
        for unit in units
        if any(normalize(span.contains) in normalize(unit.text) for span in cell.answers)
    }
    hard_keys = {
        unit.key
        for unit in units
        if matching_spans(unit.text, unit.relative_path, retrieval_gold.hard_negatives)
    }
    ranked = exhaustive_rank(units, mode="dense", dense_query=dense_query)
    ranks = {hit.key: hit.rank for hit in ranked}
    first = min((ranks[key] for key in gold_keys if key in ranks), default=None)
    top = {3: ranked[:3], 5: ranked[:5], 10: ranked[:10]}
    return {
        "relative_path": cell.relative_path,
        "question_id": cell.question_id,
        "polarity": cell.polarity,
        "gold_units": len(gold_keys),
        "first_gold_rank": first,
        "hit@3": bool(gold_keys & {hit.key for hit in top[3]}),
        "hit@5": bool(gold_keys & {hit.key for hit in top[5]}),
        "hit@10": bool(gold_keys & {hit.key for hit in top[10]}),
        "mrr": (1.0 / first) if first else 0.0,
        "hard_negative@5": len(hard_keys & {hit.key for hit in top[5]}),
        "off_gold@5": sum(1 for hit in top[5] if hit.key not in gold_keys),
        "top5_keys": [hit.key for hit in top[5]],
        "top5_evidence": [hit.text for hit in top[5]],
        "do_not_tune": (cell.relative_path, cell.question_id) in DO_NOT_TUNE_CELLS,
    }


def summarize_enrich(rows: list[dict[str, object]]) -> dict[str, object]:
    n = len(rows)
    return {
        "cells": n,
        "hit@3": _mean(rows, "hit@3"),
        "hit@5": _mean(rows, "hit@5"),
        "hit@10": _mean(rows, "hit@10"),
        "mrr": _mean(rows, "mrr"),
        "hard_negative@5": _mean(rows, "hard_negative@5"),
        "off_gold@5": _mean(rows, "off_gold@5"),
        "gold_hits_at_5": sum(1 for row in rows if row["hit@5"]),
        "hard_negative_cells_at_5": sum(1 for row in rows if row["hard_negative@5"]),
    }


def decide_enrich(variants: dict[str, dict[str, object]]) -> dict[str, object]:
    a = variants[ORIGINAL]["summary"]
    b = variants[STRUCTURE]["summary"]
    better_hit = b["hit@5"] > a["hit@5"]
    not_worse_neg = b["hard_negative@5"] <= a["hard_negative@5"]
    not_worse_off = b["off_gold@5"] <= a["off_gold@5"]
    return {
        "b_improves_hit5_without_worse_negatives": better_hit and not_worse_neg and not_worse_off,
        "do_not_run_c_automatically": True,
        "do_not_run_jev": True,
        "do_not_switch_default": True,
        "default_remains_d": True,
        "reason": (
            "Retrieval evidence only. Do not pick a winner on recall alone. "
            "C and Jev wait until B is read."
        ),
    }


def freeze_enrich_run(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": ENRICH_RUN_ID,
        "label": (
            "A vs B dense retrieval on development documents. "
            "Search is not evidence. No Jev. Default stays D."
        ),
        "do_not_overwrite": True,
        "does_not_run_jev": True,
        "does_not_change_ingest": True,
        "search_is_not_evidence": True,
        "hypothesis_2_not_built": True,
        "do_not_tune_known_misses": True,
        "default_remains_d": True,
        "strategy": payload.get("strategy"),
        "documents": payload.get("documents"),
        "spanned_cells": payload.get("spanned_cells"),
        "headline": payload.get("headline"),
        "decision": payload.get("decision"),
        "variants": payload.get("variants"),
        "scored": {
            name: [
                {key: row[key] for key in row if key != "top5_evidence"}
                for row in rows
            ]
            for name, rows in payload["scored"].items()
        },
        "prompt_tokens": payload.get("prompt_tokens"),
        "wall_seconds": payload.get("wall_seconds"),
    }


def write_enrich_run_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or ENRICH_RUN_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_enrich_run(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def write_enrich_run_table(
    payload: dict[str, object],
    directory: Path | None = None,
) -> Path:
    target = (directory or EVAL_DIR) / "enrich-run-v1.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Structure-aware embeddings, A vs B",
        "",
        "Dense document-local ranking. Search is not evidence.",
        "No Jev. No C. Default stays D.",
        "",
        "| Variant | hit@3 | hit@5 | hit@10 | MRR | Hard-neg@5 | Off-gold@5 | Embed tokens |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in FIRST_RUN:
        summary = payload["variants"][name]["summary"]
        variant = payload["variants"][name]
        lines.append(
            "| {name} | {h3:.0%} | {h5:.0%} | {h10:.0%} | {mrr:.3f} | "
            "{hard:.2f} | {off:.2f} | {tokens} |".format(
                name=name,
                h3=summary["hit@3"],
                h5=summary["hit@5"],
                h10=summary["hit@10"],
                mrr=summary["mrr"],
                hard=summary["hard_negative@5"],
                off=summary["off_gold@5"],
                tokens=variant.get("prompt_tokens") or 0,
            )
        )
    lines.extend(
        [
            "",
            payload["decision"]["reason"],
            "",
            "## What this is not",
            "",
            "- Not a Jev run.",
            "- Not representation C.",
            "- Not a default change.",
            "- Not a new OverGraph write.",
        ]
    )
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def _dense_encoder(
    *,
    dense_model: str,
    dense_dimension: int,
    openai_api_key: str | None,
    openai_base_url: str | None,
):
    if dense_model == "hashed-dense-v1":
        return HashedDenseEncoder(dense_dimension)
    return build_dense_encoder(
        model=dense_model,
        dimension=dense_dimension,
        openai_api_key=openai_api_key,
        openai_base_url=openai_base_url,
    )


def _prompt_tokens(encoder, *, reset: bool) -> int:
    tokens = int(getattr(encoder, "prompt_tokens", 0) or 0)
    if reset and hasattr(encoder, "prompt_tokens"):
        encoder.prompt_tokens = 0
    return tokens


def _mean(rows: list[dict[str, object]], key: str) -> float:
    if not rows:
        return 0.0
    return sum(float(row[key]) for row in rows) / len(rows)
