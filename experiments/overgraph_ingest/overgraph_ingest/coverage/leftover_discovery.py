"""Why the 14 leftover YES never reached proof evaluation. No new Jev."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from overgraph_ingest.config import RetrievalConfig
from overgraph_ingest.coverage.budget import _seed_hits
from overgraph_ingest.coverage.chain_run import SAVED_BLIND_TRACE, _gold
from overgraph_ingest.coverage.leftover_29 import DISCOVERY, QUALITY_REFERENCE, ROWS, summarize
from overgraph_ingest.coverage.run import _ranked_hits
from overgraph_ingest.coverage.state import BUDGET_EXHAUSTED, NEEDS_ANALYSIS, UNEXAMINED
from overgraph_ingest.graph.writer import GraphWriter, open_database
from overgraph_ingest.jev.candidates import load_graph_context
from overgraph_ingest.retrieval.encode import LexicalSparseEncoder
from overgraph_ingest.retrieval.gold import GoldSpan
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION, map_span
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.run import _dense_encoder
from overgraph_ingest.retrieval.search import SearchHit, encode_query

ROOT = Path(__file__).resolve().parents[2]
DISCOVERY_ID = "phase2-discovery-diagnosis-v1"
DISCOVERY_PATH = ROOT / "baselines" / f"{DISCOVERY_ID}.json"
DEFAULT_DB = ROOT / "data" / "blind-overgraph"
CARVEOUT_ID = "liability-secrecy-carveout"
GLOBAL_K = 50
BUDGET = 5

RANKING_TOO_LOW = "ranking_too_low"
WRONG_PASSAGE = "wrong_passage_dominates"
NEVER_SEEDED = "never_seeded"
NAVIGATION_MISS = "navigation_miss"

CAUSE_ORDER = (
    NEVER_SEEDED,
    WRONG_PASSAGE,
    BUDGET_EXHAUSTED,
    NAVIGATION_MISS,
    RANKING_TOO_LOW,
)


def discovery_documents() -> list[str]:
    return list(summarize()["tracks"][DISCOVERY]["documents"])


def short_id(path: str) -> str:
    name = Path(path).name.lower()
    digits = "".join(ch for ch in name if ch.isdigit())
    if name.startswith("avtal_") and digits:
        return f"avtal_{int(digits):03d}.docx"
    return name


def classify_cause(
    *,
    first_document_rank: int | None,
    gold_passage_seeded: bool | None,
    coverage_status: str,
) -> str:
    if first_document_rank is None or first_document_rank > GLOBAL_K:
        return NEVER_SEEDED
    if gold_passage_seeded is False:
        return WRONG_PASSAGE
    if coverage_status == BUDGET_EXHAUSTED:
        return BUDGET_EXHAUSTED
    return NAVIGATION_MISS


def load_b5(path: Path | None = None) -> dict[str, object]:
    target = path or SAVED_BLIND_TRACE
    if target is None or not target.is_file():
        return {
            "unresolved_relevant": [],
            "budget_exhausted_relevant": [],
            "status_counts": {},
            "source": None,
        }
    payload = json.loads(target.read_text(encoding="utf-8"))
    gold = next(row for row in payload["golds"] if row.get("gold_id") == CARVEOUT_ID)
    last = next(row for row in reversed(gold["budgets"]) if row.get("budget") == BUDGET)
    return {
        "unresolved_relevant": [short_id(item) for item in last["unresolved_relevant_documents"]],
        "budget_exhausted_relevant": [
            short_id(item) for item in last["budget_exhausted_relevant"]
        ],
        "status_counts": last.get("status_counts") or {},
        "source": str(target),
        "global_k": payload.get("global_k", GLOBAL_K),
        "scorer": payload.get("scorer"),
    }


def load_units(*, db_path: Path | None = None, dense_dimension: int = 3072) -> list[StoredUnit]:
    target = db_path or DEFAULT_DB
    if not target.is_dir():
        return []
    db = open_database(target, dense_dimension)
    try:
        return load_graph_context(GraphWriter(db, batch_size=500)).units
    finally:
        db.close()


def rank_units(
    units: list[StoredUnit],
    query: str,
    *,
    openai_api_key: str,
    dense_model: str = "text-embedding-3-large",
    dense_dimension: int = 3072,
    openai_base_url: str | None = None,
) -> list[SearchHit]:
    config = RetrievalConfig(
        db_path=DEFAULT_DB,
        dense_dimension=dense_dimension,
        dense_model=dense_model,
        openai_api_key=openai_api_key,
        openai_base_url=openai_base_url,
    )
    dimension = dense_dimension
    dense = _dense_encoder(config, dimension)
    sparse = LexicalSparseEncoder()
    sparse.fit([unit.text for unit in units])
    dense_query, sparse_query = encode_query(query, dense=dense, sparse=sparse)
    return _ranked_hits(units, "hybrid", dense_query, sparse_query)


def gold_unit_keys(units: list[StoredUnit], span: GoldSpan | None) -> list[str]:
    if span is None:
        return []
    mapped = map_span(units, span)
    return [str(hit["unit_key"]) for hit in mapped["hits"]]


def diagnose_row(
    path: str,
    *,
    ranked: list[SearchHit],
    units: list[StoredUnit],
    gold_keys: list[str],
    coverage_status: str,
    would_admit: bool,
) -> dict[str, object]:
    doc_hits = [hit for hit in ranked if short_id(hit.relative_path) == path]
    gold_hits = [hit for hit in doc_hits if hit.key in set(gold_keys)]
    in_k = [hit for hit in doc_hits if hit.rank <= GLOBAL_K]
    seed = _seed_hits(ranked, {}, global_k=GLOBAL_K, budget=BUDGET)
    seeded_keys = {hit.key for hit in seed if short_id(hit.relative_path) == path}
    first_document_rank = None if not doc_hits else doc_hits[0].rank
    first_passage_rank = None if not gold_hits else gold_hits[0].rank
    gold_seeded = None if not ranked else bool(set(gold_keys) & seeded_keys)
    cause = classify_cause(
        first_document_rank=first_document_rank,
        gold_passage_seeded=gold_seeded,
        coverage_status=coverage_status,
    )
    return {
        "relative_path": path,
        "first_document_rank": first_document_rank,
        "first_relevant_passage_rank": first_passage_rank,
        "candidates_in_global_k": len(in_k),
        "seeded": bool(seeded_keys),
        "gold_passage_seeded": gold_seeded,
        "coverage_status": coverage_status,
        "later_round_budget": coverage_status == BUDGET_EXHAUSTED and (
            first_document_rank is None or first_document_rank > GLOBAL_K
        ),
        "document_text_units": sum(1 for unit in units if short_id(unit.relative_path) == path),
        "gold_text_units": len(gold_keys),
        "would_admit_if_found": would_admit,
        "cause": cause,
        "gold_passage_beyond_global_k": first_passage_rank is None or first_passage_rank > GLOBAL_K,
    }


def coverage_status_for(path: str, b5: dict[str, object]) -> str:
    exhausted = set(b5.get("budget_exhausted_relevant") or [])
    unresolved = set(b5.get("unresolved_relevant") or [])
    if path in exhausted:
        return BUDGET_EXHAUSTED
    if path in unresolved:
        return NEEDS_ANALYSIS
    return UNEXAMINED


def summarize_rows(rows: list[dict[str, object]]) -> dict[str, object]:
    causes = Counter(str(row["cause"]) for row in rows)
    return {
        "documents": len(rows),
        "causes": {name: causes.get(name, 0) for name in CAUSE_ORDER},
        "budget_exhausted_relevant": sorted(
            row["relative_path"] for row in rows if row["coverage_status"] == BUDGET_EXHAUSTED
        ),
        "never_seeded": sorted(
            row["relative_path"] for row in rows if row["cause"] == NEVER_SEEDED
        ),
        "wrong_passage_dominates": sorted(
            row["relative_path"] for row in rows if row["cause"] == WRONG_PASSAGE
        ),
        "ranking_problem": sorted(
            row["relative_path"]
            for row in rows
            if row["cause"] in {NEVER_SEEDED, WRONG_PASSAGE}
        ),
        "gold_passage_in_seed": sorted(
            row["relative_path"] for row in rows if row.get("gold_passage_seeded")
        ),
        "later_round_budget_outside_seed": sorted(
            row["relative_path"] for row in rows if row.get("later_round_budget")
        ),
        "unlocks_if_examined_with_current_abilities": sorted(
            row["relative_path"] for row in rows if row["would_admit_if_found"]
        ),
        "quality_reference": QUALITY_REFERENCE,
        "does_not_choose_next_action": True,
        "does_not_change_retrieval": True,
        "does_not_add_omfattar_inte": True,
    }


def run_discovery_diagnosis(
    *,
    path: Path | None = None,
    db_path: Path | None = None,
    dense_dimension: int = 3072,
    units: list[StoredUnit] | None = None,
    ranked: list[SearchHit] | None = None,
    openai_api_key: str | None = None,
    dense_model: str = "text-embedding-3-large",
    openai_base_url: str | None = None,
) -> dict[str, object]:
    documents = discovery_documents()
    b5 = load_b5(path)
    unresolved = set(b5["unresolved_relevant"] or documents)
    if b5["unresolved_relevant"] and set(b5["unresolved_relevant"]) != set(documents):
        raise ValueError(
            "coverage B5 unresolved relevant does not match leftover-29 discovery: "
            f"missing={sorted(set(documents) - set(b5['unresolved_relevant']))} "
            f"extra={sorted(set(b5['unresolved_relevant']) - set(documents))}"
        )
    catalog = units if units is not None else load_units(
        db_path=db_path, dense_dimension=dense_dimension
    )
    gold, _classes, _traps = _gold()
    spans = {short_id(span.relative_path): span for span in gold.relevant_units}
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
        diagnose_row(
            document,
            ranked=hits,
            units=catalog,
            gold_keys=gold_unit_keys(catalog, spans.get(document)),
            coverage_status=coverage_status_for(document, b5),
            would_admit=bool(ROWS[document]["decidable_by_one"]),
        )
        for document in documents
    ]
    return {
        "operation": "diagnosis",
        "experiment": "discovery_diagnosis_v1",
        "applied_to_v3": False,
        "no_new_jev": True,
        "no_new_controller": True,
        "does_not_change_retrieval": True,
        "does_not_start_next_ability": True,
        "does_not_add_omfattar_inte": True,
        "same_mapping": GOLD_MAP_VERSION,
        "quality_reference": QUALITY_REFERENCE,
        "global_k": GLOBAL_K,
        "budget": BUDGET,
        "ranking_computed": bool(hits),
        "coverage_source": b5.get("source"),
        "unresolved_matches_leftover_29": not b5["unresolved_relevant"]
        or set(b5["unresolved_relevant"]) == set(documents),
        "summary": summarize_rows(rows),
        "rows": {row["relative_path"]: row for row in rows},
        "expected_unresolved": sorted(unresolved) if unresolved else documents,
    }


def freeze_discovery_diagnosis(payload: dict[str, object] | None = None) -> dict[str, object]:
    body = payload or run_discovery_diagnosis()
    return {
        "id": DISCOVERY_ID,
        "label": (
            "Frozen: discovery diagnosis of the 14 never-examined leftover YES. "
            "No new controller, retrieval change, or Jev. "
            "24/53 remains the quality reference. Does not choose the next action."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "applied_to_v3": False,
        "no_new_jev": True,
        "no_new_controller": True,
        "does_not_change_retrieval": True,
        "does_not_start_next_ability": True,
        "does_not_add_omfattar_inte": True,
        "headline": {
            "quality_reference": body.get("quality_reference"),
            "ranking_computed": body.get("ranking_computed"),
            "summary": body.get("summary"),
            "rows": body.get("rows"),
        },
    }


def write_discovery_diagnosis(
    payload: dict[str, object] | None = None,
    path: Path | None = None,
) -> Path:
    target = path or DISCOVERY_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    body = payload or run_discovery_diagnosis()
    target.write_text(
        json.dumps(freeze_discovery_diagnosis(body), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target
