"""Synchronous Tabular Review. One cell at a time. No Coverage v3."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from overgraph_ingest.cerebras.client import CerebrasClient, Completer
from overgraph_ingest.cerebras.pricing import cost_usd
from overgraph_ingest.config import RetrievalConfig
from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE
from overgraph_ingest.graph.writer import GraphWriter, open_database, resolve_dimension
from overgraph_ingest.jev.candidates import GraphContext, context_from_units, load_graph_context
from overgraph_ingest.jev.client import HttpJevClient, JevClient
from overgraph_ingest.retrieval.encode import LexicalSparseEncoder
from overgraph_ingest.retrieval.gold import RetrievalGold
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.run import _dense_encoder
from overgraph_ingest.retrieval.search import encode_query
from overgraph_ingest.tabular.cells import VARIANT_A, VARIANT_B, VARIANT_C, VARIANT_D, VARIANT_K, run_cell
from overgraph_ingest.tabular.contract import CellResult
from overgraph_ingest.tabular.evaluate import (
    compare_variants,
    error_examples,
    headline,
    score_cell,
)
from overgraph_ingest.tabular.gold import (
    QUESTION_IDS,
    SELECTED_DOCUMENTS,
    USER_QUESTIONS,
    cell_relevant_keys,
    load_tabular_golds,
)
from overgraph_ingest.tabular.jev_io import CountingJev
from overgraph_ingest.tabular.reuse import NEW, NOT_REUSED, REUSED
from overgraph_ingest.tabular.search import DEFAULT_K
from overgraph_ingest.tabular.serialize import cell_payload

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "extra-overgraph-phase2"
DEFAULT_GOLD_DIR = ROOT / "retrieval_gold"
VARIANTS = (VARIANT_A, VARIANT_B, VARIANT_C)
DEFAULT_MODEL = "gpt-oss-120b"
DEFAULT_BASE_URL = "https://api.cerebras.ai/v1"


def run_tabular_review(
    *,
    db_path: Path | None = None,
    gold_dir: Path | None = None,
    dense_dimension: int = 3072,
    openai_api_key: str | None = None,
    openai_base_url: str | None = None,
    dense_model: str = "text-embedding-3-large",
    typesafe_api_key: str | None = None,
    typesafe_base_url: str = "https://api.typesafe.ai",
    jev_model: str = "jev-latest",
    jev_timeout_seconds: float = 8.0,
    cerebras_api_key: str | None = None,
    cerebras_base_url: str = DEFAULT_BASE_URL,
    cerebras_model: str = DEFAULT_MODEL,
    documents: tuple[str, ...] = SELECTED_DOCUMENTS,
    variants: tuple[str, ...] = VARIANTS,
    top_k: int = DEFAULT_K,
    units: list[StoredUnit] | None = None,
    structures: dict[str, dict[str, object]] | None = None,
    queries: dict[str, tuple[list[float], list[tuple[int, float]]]] | None = None,
    golds: list[RetrievalGold] | None = None,
    jev: JevClient | None = None,
    cerebras: Completer | None = None,
    context: GraphContext | None = None,
) -> dict[str, object]:
    gold_rows = golds or load_tabular_golds(gold_dir or DEFAULT_GOLD_DIR)
    by_id = {gold.id: gold for gold in gold_rows}
    if any(question_id not in by_id for question_id in QUESTION_IDS):
        raise ValueError("tabular gold set is incomplete")
    graph = context or _load_context(
        db_path=db_path,
        dense_dimension=dense_dimension,
        units=units,
        structures=structures,
    )
    encoded = queries or _encode_questions(
        db_path=db_path or DEFAULT_DB,
        dense_dimension=dense_dimension,
        openai_api_key=openai_api_key,
        openai_base_url=openai_base_url,
        dense_model=dense_model,
        units=graph.units,
    )
    jev_client = _jev_client(
        jev,
        typesafe_api_key=typesafe_api_key,
        typesafe_base_url=typesafe_base_url,
        variants=variants,
    )
    cerebras_client = _cerebras_client(
        cerebras,
        cerebras_api_key=cerebras_api_key,
        cerebras_base_url=cerebras_base_url,
        cerebras_model=cerebras_model,
        variants=variants,
    )
    started = time.perf_counter()
    cells = []
    scored = []
    for relative_path in documents:
        for question_id in QUESTION_IDS:
            gold = by_id[question_id]
            relevant = cell_relevant_keys(graph.units, gold, relative_path)
            dense_query, sparse_query = encoded[question_id]
            for variant in variants:
                result = run_cell(
                    variant=variant,
                    relative_path=relative_path,
                    question_id=question_id,
                    user_question=USER_QUESTIONS[question_id],
                    classify_question=gold.classify_question,
                    units=graph.units,
                    context=graph,
                    dense_query=dense_query,
                    sparse_query=sparse_query,
                    relevant_keys=relevant,
                    jev=jev_client,
                    cerebras=cerebras_client,
                    jev_model=jev_model,
                    timeout_seconds=jev_timeout_seconds,
                    top_k=top_k,
                )
                cells.append(result)
                scored.append(score_cell(result, relevant))
                print(
                    f"{variant} {result.document_id} {question_id} {result.status}",
                    file=sys.stderr,
                    flush=True,
                )
    comparison = compare_variants(scored)
    cost = _cost(cells, cerebras_model)
    return {
        "operation": "tabular_review",
        "experiment": "tabular_review_v1",
        "task": "document_local_source_grounded_cell",
        "applied_to_v3": False,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "no_coverage_controller": True,
        "no_proof_engine": True,
        "no_second_opinion": True,
        "no_model_router": True,
        "no_qwen": True,
        "no_query_expansion": True,
        "synchronous": True,
        "one_cell_at_a_time": True,
        "same_mapping": GOLD_MAP_VERSION,
        "quality_reference": QUALITY_REFERENCE,
        "not_comparable_to_24_53": True,
        "selection_is_diagnostic": True,
        "selection_is_not_general_quality": True,
        "hundred_document_run_not_started": True,
        "selection": list(documents),
        "questions": [
            {"id": question_id, "text": USER_QUESTIONS[question_id]}
            for question_id in QUESTION_IDS
        ],
        "variants": list(variants),
        "k": top_k,
        "reuse": {"reused": REUSED, "not_reused": NOT_REUSED, "new": NEW},
        "cells": [cell_payload(item) for item in cells],
        "scored": scored,
        "comparison": comparison,
        "headline": headline(comparison, cost),
        "cost": cost,
        "errors": error_examples(cells, scored),
        "wall_seconds": time.perf_counter() - started,
        "table_seconds": time.perf_counter() - started,
    }


def write_tabular_review(payload: dict[str, object], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


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


def _encode_questions(
    *,
    db_path: Path,
    dense_dimension: int,
    openai_api_key: str | None,
    openai_base_url: str | None,
    dense_model: str,
    units: list[StoredUnit],
) -> dict[str, tuple[list[float], list[tuple[int, float]]]]:
    if openai_api_key is None:
        raise ValueError("--openai-api-key is required for tabular review")
    if any(unit.dense is None or unit.sparse is None for unit in units):
        raise RuntimeError("TextUnits are missing vectors; rerun with --embed")
    dimension = resolve_dimension(db_path, dense_dimension)
    config = RetrievalConfig(
        db_path=db_path,
        dense_dimension=dimension,
        dense_model=dense_model,
        openai_api_key=openai_api_key,
        openai_base_url=openai_base_url,
    )
    dense = _dense_encoder(config, dimension)
    sparse = LexicalSparseEncoder()
    sparse.fit([unit.text for unit in units])
    encoded: dict[str, tuple[list[float], list[tuple[int, float]]]] = {}
    for question_id, text in USER_QUESTIONS.items():
        encoded[question_id] = encode_query(text, dense=dense, sparse=sparse)
    return encoded


def _jev_client(
    injected: JevClient | None,
    *,
    typesafe_api_key: str | None,
    typesafe_base_url: str,
    variants: tuple[str, ...],
) -> CountingJev | None:
    if not ({VARIANT_A, VARIANT_B, VARIANT_K, VARIANT_D} & set(variants)):
        return None
    if injected is not None:
        return injected if isinstance(injected, CountingJev) else CountingJev(injected)
    if not typesafe_api_key:
        raise ValueError("--typesafe-api-key is required for tabular variants A and B")
    return CountingJev(HttpJevClient(api_key=typesafe_api_key, base_url=typesafe_base_url))


def _cerebras_client(
    injected: Completer | None,
    *,
    cerebras_api_key: str | None,
    cerebras_base_url: str,
    cerebras_model: str,
    variants: tuple[str, ...],
) -> Completer | None:
    if VARIANT_C not in variants:
        return None
    if injected is not None:
        return injected
    if not cerebras_api_key:
        raise ValueError("--cerebras-api-key is required for tabular variant C")
    return CerebrasClient(
        api_key=cerebras_api_key,
        base_url=cerebras_base_url,
        model=cerebras_model,
        reasoning_effort="medium",
    )


def _cost(cells: list[CellResult], model: str) -> dict[str, object]:
    jev_calls = sum(item.jev_calls for item in cells)
    cerebras_calls = sum(item.cerebras_calls for item in cells)
    prompt = sum(item.prompt_tokens or 0 for item in cells)
    completion = sum(item.completion_tokens or 0 for item in cells)
    cerebras_prompt = sum(
        item.prompt_tokens or 0 for item in cells if item.variant == VARIANT_C
    )
    cerebras_completion = sum(
        item.completion_tokens or 0 for item in cells if item.variant == VARIANT_C
    )
    usd = (
        cost_usd(model, cerebras_prompt, cerebras_completion)
        if cerebras_prompt or cerebras_completion
        else 0.0
    )
    n = len(cells)
    correct = sum(
        1
        for item in cells
        if item.status == "ANSWERED" and any(source.validated for source in item.sources)
    )
    return {
        "jev_calls": jev_calls,
        "cerebras_calls": cerebras_calls,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "cerebras_usd": usd,
        "jev_usd": None,
        "per_cell_usd": (usd / n) if n else 0.0,
        "per_100_cells_usd": (usd / n * 100) if n else 0.0,
        "per_correct_cited_usd": (usd / correct) if correct else None,
        "jev_cost_unknown": True,
    }
