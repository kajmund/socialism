"""Corrected gold-map evaluation. No new Jev. Default contains unchanged."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.coverage.blind_carveout import GOLD_ZIP
from overgraph_ingest.coverage.blind_gold import load_blind_property
from overgraph_ingest.graph.writer import GraphWriter, open_database
from overgraph_ingest.retrieval.gold import GoldSpan
from overgraph_ingest.retrieval.gold_map import (
    GOLD_MAP_VERSION,
    locate_contains,
    map_span,
    rematch_gold,
)
from overgraph_ingest.retrieval.index import StoredUnit, load_published_units

ROOT = Path(__file__).resolve().parents[2]
GOLD_MAP_BASELINE_ID = "phase2-gold-map-v2"
GOLD_MAP_BASELINE_PATH = ROOT / "baselines" / f"{GOLD_MAP_BASELINE_ID}.json"
DEFAULT_DB = ROOT / "data" / "blind-overgraph"
AVTAL_160_GOLD = (
    "Alternativ A ☒ Begränsningen i § 6 första stycket gäller inte vid brott mot § 5."
)
AVTAL_160_SOURCE = (
    "Alternativ A ☒  Begränsningen i § 6 första stycket gäller inte vid brott mot § 5."
)

EXAMINED_SUPPORT = "supported_by_examined_material"
EXHAUSTIVE_ABSENCE = "entire_document_examined_no_further_provisions"
FAILURE_KINDS = (
    "wrong_decision_contract",
    "lacking_semantic_understanding",
    "gold_mapping_miss",
)


def avtal_160_case() -> dict[str, object]:
    unit = StoredUnit(
        1,
        "avtal-160-fixture",
        "doc-160",
        "avtal_160.docx",
        AVTAL_160_SOURCE,
        None,
        None,
    )
    span = GoldSpan(relative_path="avtal_160.docx", contains=AVTAL_160_GOLD)
    mapped = map_span([unit], span)
    hits = locate_contains(AVTAL_160_SOURCE, AVTAL_160_GOLD)
    grounded = mapped["hits"][0] if mapped["hits"] else {}
    return {
        "relative_path": "avtal_160.docx",
        "v1_exact": False,
        "v2_status": mapped["status"],
        "how": hits[0][3] if hits else None,
        "exact_quote": hits[0][2] if hits else None,
        "unit_start": grounded.get("unit_start") if isinstance(grounded, dict) else None,
        "unit_end": grounded.get("unit_end") if isinstance(grounded, dict) else None,
        "source_char_start": grounded.get("source_char_start") if isinstance(grounded, dict) else None,
        "source_char_end": grounded.get("source_char_end") if isinstance(grounded, dict) else None,
        "preserves_ballot": "☒" in (hits[0][2] if hits else ""),
        "preserves_negation": "gäller inte" in (hits[0][2] if hits else ""),
        "preserves_two_spaces_after_ballot": "☒  " in (hits[0][2] if hits else ""),
        "is_ranking_miss": False,
        "is_ingest_information_loss": False,
        "source_text_unchanged": True,
    }


def run_gold_map(*, db_path: Path | None = None, dense_dimension: int = 3072) -> dict[str, object]:
    rematch = None
    target = db_path or DEFAULT_DB
    if GOLD_ZIP.is_file() and target.is_dir():
        gold, _classes, _traps = load_blind_property(
            "E_sekretessundantag_fran_ansvarsbegransning"
        )
        db = open_database(target, dense_dimension)
        try:
            units = load_published_units(GraphWriter(db, batch_size=500))
        finally:
            db.close()
        if any(unit.relative_path == "avtal_160.docx" for unit in units):
            rematch = rematch_gold(units, gold)
    return {
        "operation": "retrieval",
        "experiment": "gold_map_v2",
        "version": GOLD_MAP_VERSION,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_change_default_contains": True,
        "does_not_rewrite_history": True,
        "no_new_jev": True,
        "no_new_controller": True,
        "no_looser_verified_rule": True,
        "avtal_160": avtal_160_case(),
        "rematch": rematch,
        "answer_contract": {
            "gold_tests": "prevailing_terms",
            "examined_support": EXAMINED_SUPPORT,
            "exhaustive_absence": EXHAUSTIVE_ABSENCE,
            "examined_support_is_not_exhaustive_absence": True,
            "unseen_amendment_is_not_proof_of_absence": True,
        },
        "next_completion_replaces_yes_plus_hop": True,
        "do_not_add_another_gate": True,
        "do_not_loosen_verified": True,
        "failure_kinds_must_not_share_a_fix": list(FAILURE_KINDS),
    }


def freeze_gold_map_baseline(payload: dict[str, object]) -> dict[str, object]:
    rematch = payload.get("rematch") or {}
    mapped = rematch.get("mapped") if isinstance(rematch, dict) else None
    live_160 = None
    if isinstance(mapped, list):
        live_160 = next(
            (row for row in mapped if row.get("relative_path") == "avtal_160.docx"),
            None,
        )
    return {
        "id": GOLD_MAP_BASELINE_ID,
        "label": (
            "Frozen: gold-map v2 space-run locate, original offsets. "
            "Historical measurements unchanged. Not a new controller."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_change_default_contains": True,
        "does_not_rewrite_history": True,
        "headline": {
            "version": payload.get("version"),
            "avtal_160": payload.get("avtal_160"),
            "avtal_160_in_graph": live_160,
            "rematch_counts": rematch.get("counts") if isinstance(rematch, dict) else None,
            "answer_contract": payload.get("answer_contract"),
            "next_completion_replaces_yes_plus_hop": True,
            "failure_kinds_must_not_share_a_fix": payload.get(
                "failure_kinds_must_not_share_a_fix"
            ),
        },
    }


def write_gold_map_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or GOLD_MAP_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_gold_map_baseline(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target
