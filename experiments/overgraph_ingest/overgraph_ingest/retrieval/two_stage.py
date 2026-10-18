"""Two-stage retrieval at a fixed candidate budget. No Jev. No controller."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.coverage.chain_run import _gold
from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE, summarize as leftover_summary
from overgraph_ingest.coverage.leftover_discovery import (
    DEFAULT_DB,
    GLOBAL_K,
    discovery_documents,
    gold_unit_keys,
    load_units,
    rank_units,
    short_id,
)
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.search import SearchHit

ROOT = Path(__file__).resolve().parents[2]
TWO_STAGE_ID = "phase2-two-stage-retrieval-v1"
TWO_STAGE_PATH = ROOT / "baselines" / f"{TWO_STAGE_ID}.json"
TOTAL_BUDGET = GLOBAL_K
ALLOCATIONS = ((50, 1), (25, 2), (10, 5), (5, 10))
STAGE1_MARKS = (10, 25, 50, 100)
GLOBAL_NAME = "global_top_50"
UNLOCKS = tuple(leftover_summary()["unlocks_if_examined_with_current_abilities"])


def identify_documents(ranked: list[SearchHit], limit: int) -> list[str]:
    seen: list[str] = []
    found: set[str] = set()
    for hit in ranked:
        path = short_id(hit.relative_path)
        if path in found:
            continue
        found.add(path)
        seen.append(path)
        if len(seen) >= limit:
            break
    return seen


def identification_ranks(ranked: list[SearchHit]) -> dict[str, int]:
    return {path: index for index, path in enumerate(identify_documents(ranked, 10**9), start=1)}


def local_hits(ranked: list[SearchHit], path: str, limit: int | None = None) -> list[SearchHit]:
    hits = [hit for hit in ranked if short_id(hit.relative_path) == path]
    return hits if limit is None else hits[:limit]


def two_stage_hits(ranked: list[SearchHit], documents: int, per_document: int) -> list[SearchHit]:
    chosen: list[SearchHit] = []
    for path in identify_documents(ranked, documents):
        chosen.extend(local_hits(ranked, path, per_document))
    return chosen


def same_intra_document_order(ranked: list[SearchHit], path: str) -> bool:
    filtered = local_hits(ranked, path)
    resorted = sorted(filtered, key=lambda hit: (-hit.score, hit.key))
    return [hit.key for hit in filtered] == [hit.key for hit in resorted]


def diagnose_document(
    path: str,
    *,
    ranked: list[SearchHit],
    gold_keys: list[str],
    units: list[StoredUnit],
) -> dict[str, object]:
    doc_hits = local_hits(ranked, path)
    gold_hits = [hit for hit in doc_hits if hit.key in set(gold_keys)]
    identified = identification_ranks(ranked)
    first_document_rank = None if not doc_hits else doc_hits[0].rank
    first_passage_rank = None if not gold_hits else gold_hits[0].rank
    local_passage_rank = None if not gold_hits else doc_hits.index(gold_hits[0]) + 1
    return {
        "relative_path": path,
        "first_document_rank": first_document_rank,
        "first_relevant_passage_rank": first_passage_rank,
        "local_passage_rank": local_passage_rank,
        "document_identification_rank": identified.get(path),
        "document_text_units": sum(1 for unit in units if short_id(unit.relative_path) == path),
        "same_intra_document_order": same_intra_document_order(ranked, path),
        "min_two_stage_budget": (
            None
            if identified.get(path) is None or local_passage_rank is None
            else identified[path] * local_passage_rank
        ),
        "would_admit_if_found": path in UNLOCKS,
    }


def score_candidates(
    hits: list[SearchHit],
    *,
    leftover: list[str],
    gold_keys: dict[str, list[str]],
) -> dict[str, object]:
    paths = {short_id(hit.relative_path) for hit in hits}
    documents = sorted(path for path in leftover if path in paths)
    passages = sorted(
        path
        for path in leftover
        if any(
            short_id(hit.relative_path) == path and hit.key in set(gold_keys.get(path) or [])
            for hit in hits
        )
    )
    unlock_docs = [path for path in UNLOCKS if path in documents]
    unlock_passages = [path for path in UNLOCKS if path in passages]
    return {
        "candidates": len(hits),
        "unique_documents": len(paths),
        "leftover_document_recall": len(documents) / len(leftover) if leftover else 0.0,
        "leftover_passage_recall": len(passages) / len(leftover) if leftover else 0.0,
        "leftover_documents": documents,
        "leftover_passages": passages,
        "unlocks_documents": unlock_docs,
        "unlocks_passages": unlock_passages,
    }


def stage1_curve(identified: dict[str, int], leftover: list[str]) -> list[dict[str, object]]:
    rows = []
    for mark in STAGE1_MARKS:
        found = sorted(
            path for path in leftover if (identified.get(path) or 10**9) <= mark
        )
        rows.append(
            {
                "documents_selected": mark,
                "leftover_documents": found,
                "leftover_document_recall": len(found) / len(leftover) if leftover else 0.0,
                "unlocks": [path for path in UNLOCKS if path in found],
            }
        )
    return rows


def score_allocation(
    ranked: list[SearchHit],
    leftover: list[str],
    gold_keys: dict[str, list[str]],
    documents: int,
    per_document: int,
) -> dict[str, object]:
    hits = two_stage_hits(ranked, documents, per_document)
    return {
        "name": f"two_stage_{documents}x{per_document}",
        "documents_selected": documents,
        "passages_per_document": per_document,
        "total_budget": documents * per_document,
        "examines_all_documents": False,
        "improvement_is_budget_allocation": True,
        **score_candidates(hits, leftover=leftover, gold_keys=gold_keys),
    }


def run_two_stage_retrieval(
    *,
    db_path: Path | None = None,
    dense_dimension: int = 3072,
    units: list[StoredUnit] | None = None,
    ranked: list[SearchHit] | None = None,
    openai_api_key: str | None = None,
    dense_model: str = "text-embedding-3-large",
    openai_base_url: str | None = None,
) -> dict[str, object]:
    leftover = discovery_documents()
    catalog = units if units is not None else load_units(
        db_path=db_path or DEFAULT_DB, dense_dimension=dense_dimension
    )
    gold, _classes, _traps = _gold()
    spans = {short_id(span.relative_path): span for span in gold.relevant_units}
    keys = {path: gold_unit_keys(catalog, spans.get(path)) for path in leftover}
    hits = ranked
    if hits is None and catalog and openai_api_key:
        hits = rank_units(
            catalog,
            gold.query,
            openai_api_key=openai_api_key,
            dense_model=dense_model,
            dense_dimension=dense_dimension,
            openai_base_url=openai_base_url,
        )
    hits = hits or []
    rows = [
        diagnose_document(path, ranked=hits, gold_keys=keys[path], units=catalog)
        for path in leftover
    ]
    identified = identification_ranks(hits)
    global_hits = hits[:TOTAL_BUDGET]
    allocations = [
        score_allocation(hits, leftover, keys, documents, per_document)
        for documents, per_document in ALLOCATIONS
    ]
    same_order = all(row["same_intra_document_order"] for row in rows) if rows else True
    return {
        "operation": "retrieval",
        "experiment": "two_stage_retrieval_v1",
        "applied_to_v3": False,
        "no_new_jev": True,
        "no_new_controller": True,
        "does_not_change_proof": True,
        "does_not_repeat_coverage_budget": True,
        "structure_guided_local_not_started": True,
        "same_mapping": GOLD_MAP_VERSION,
        "same_embeddings": True,
        "same_score_function": True,
        "improvement_is_budget_allocation": same_order,
        "quality_reference": QUALITY_REFERENCE,
        "total_budget": TOTAL_BUDGET,
        "ranking_computed": bool(hits),
        "rows": {row["relative_path"]: row for row in rows},
        "stage1_document_discovery": stage1_curve(identified, leftover),
        "strategies": {
            GLOBAL_NAME: {
                "name": GLOBAL_NAME,
                "documents_selected": None,
                "passages_per_document": None,
                "total_budget": TOTAL_BUDGET,
                "examines_all_documents": False,
                "improvement_is_budget_allocation": False,
                **score_candidates(global_hits, leftover=leftover, gold_keys=keys),
            },
            **{row["name"]: row for row in allocations},
        },
    }


def freeze_two_stage_retrieval(payload: dict[str, object] | None = None) -> dict[str, object]:
    body = payload or run_two_stage_retrieval()
    return {
        "id": TWO_STAGE_ID,
        "label": (
            "Frozen: two-stage document-then-local retrieval at a fixed "
            "candidate budget of 50. Same scores, so any gain is budget "
            "allocation. No Jev, no controller, no proof change. "
            "24/53 remains the quality reference."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "applied_to_v3": False,
        "no_new_jev": True,
        "no_new_controller": True,
        "does_not_change_proof": True,
        "does_not_repeat_coverage_budget": True,
        "structure_guided_local_not_started": True,
        "improvement_is_budget_allocation": body.get("improvement_is_budget_allocation"),
        "headline": {
            "quality_reference": body.get("quality_reference"),
            "total_budget": body.get("total_budget"),
            "improvement_is_budget_allocation": body.get("improvement_is_budget_allocation"),
            "stage1_document_discovery": body.get("stage1_document_discovery"),
            "strategies": body.get("strategies"),
            "rows": body.get("rows"),
        },
    }


def write_two_stage_retrieval(
    payload: dict[str, object] | None = None,
    path: Path | None = None,
) -> Path:
    target = path or TWO_STAGE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    body = payload or run_two_stage_retrieval()
    target.write_text(
        json.dumps(freeze_two_stage_retrieval(body), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target
