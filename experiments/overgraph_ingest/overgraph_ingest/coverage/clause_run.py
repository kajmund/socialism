"""Compare grounded-chain with explicit clause resolution. Same gold-map v2."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.coverage.chain_contract import CHAIN_CONTRACT, assess_chain
from overgraph_ingest.coverage.chain_run import (
    SAVED_BLIND_TRACE,
    _gold,
    load_blind_traces,
    score_variant,
)
from overgraph_ingest.coverage.clause_resolve import (
    CLAUSE_CONTRACT,
    assess_with_clauses,
    catalog_from_graph,
)
from overgraph_ingest.coverage.stop_replay import INVESTIGATION_PARTIAL
from overgraph_ingest.graph.writer import GraphWriter, open_database
from overgraph_ingest.jev.candidates import load_graph_context
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION

ROOT = Path(__file__).resolve().parents[2]
CLAUSE_BASELINE_ID = "phase2-clause-resolve-v1"
CLAUSE_BASELINE_PATH = ROOT / "baselines" / f"{CLAUSE_BASELINE_ID}.json"
DEFAULT_DB = ROOT / "data" / "blind-overgraph"
KNOWN_CASES = (
    "avtal_103.docx",
    "avtal_138.docx",
    "avtal_173.docx",
    "avtal_106.docx",
    "avtal_119.docx",
)


def load_catalog(*, db_path: Path | None = None, dense_dimension: int = 3072) -> list:
    target = db_path or DEFAULT_DB
    if not target.is_dir():
        return []
    db = open_database(target, dense_dimension)
    try:
        context = load_graph_context(GraphWriter(db, batch_size=500))
    finally:
        db.close()
    if not any(unit.relative_path == "avtal_103.docx" for unit in context.units):
        return []
    return catalog_from_graph(context.units, context.structures)


def run_clause_resolve(
    *,
    path: Path | None = None,
    db_path: Path | None = None,
    dense_dimension: int = 3072,
    catalog: list | None = None,
) -> dict[str, object]:
    traces = load_blind_traces(path)
    gold, classes, _traps = _gold()
    expected = tuple(gold.relevant_documents)
    units = catalog if catalog is not None else load_catalog(
        db_path=db_path, dense_dimension=dense_dimension
    )
    reference = [assess_chain(trace) for trace in traces]
    treatment = [assess_with_clauses(trace, units) for trace in traces]
    ref_score = score_variant(
        traces,
        reference,
        gold_classes=classes,
        gold_spans=gold.relevant_units,
        expected_yes=expected,
    )
    treat_score = score_variant(
        traces,
        treatment,
        gold_classes=classes,
        gold_spans=gold.relevant_units,
        expected_yes=expected,
    )
    extra = sum(int(row.get("extra_units_fetched") or 0) for row in treatment)
    lookups = sum(len(row.get("lookups") or []) for row in treatment)
    by_id = {str(row["document_id"]): row for row in treatment}
    ref_true = set(ref_score["true_support"])
    treat_true = set(treat_score["true_support"])
    return {
        "operation": "coverage",
        "experiment": "clause_resolve_v1",
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_rewrite_history": True,
        "applied_to_v3": False,
        "no_new_jev": True,
        "no_new_controller": True,
        "no_looser_verified_rule": True,
        "same_mapping_for_both_variants": GOLD_MAP_VERSION,
        "known_cases_are_regression_tests": True,
        "finding_clause_is_not_admission": True,
        "undecided_remains_searchable": True,
        "approved_chain_does_not_upgrade_investigation": True,
        "zero_false_must_be_read_with_abstention": True,
        "reference": {"contract": CHAIN_CONTRACT, **ref_score},
        "treatment": {"contract": CLAUSE_CONTRACT, **treat_score},
        "delta": {
            "true_support": len(treat_true) - len(ref_true),
            "new_true_support": sorted(treat_true - ref_true),
            "lost_true_support": sorted(ref_true - treat_true),
            "false_approvals": treat_score["counts"]["false_approvals"]
            - ref_score["counts"]["false_approvals"],
            "repaired_uncertain": treat_score["counts"]["repaired_uncertain"]
            - ref_score["counts"]["repaired_uncertain"],
            "leftover_genuine": treat_score["counts"]["leftover_genuine"]
            - ref_score["counts"]["leftover_genuine"],
            "extra_units_fetched": extra,
            "citations_looked_up": lookups,
        },
        "cases": {
            path: {
                "examined_support": (by_id.get(path) or {}).get("examined_support"),
                "why": (by_id.get(path) or {}).get("why"),
                "lookups": (by_id.get(path) or {}).get("lookups") or [],
                "investigation": INVESTIGATION_PARTIAL,
                "undecided_remains_searchable": True,
            }
            for path in KNOWN_CASES
        },
        "decisions": treatment,
    }


def freeze_clause_resolve_baseline(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": CLAUSE_BASELINE_ID,
        "label": (
            "Frozen: explicit clause resolution on the grounded-chain contract. "
            "Known cases are regression tests. Not applied to v3."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_rewrite_history": True,
        "applied_to_v3": False,
        "same_mapping_for_both_variants": GOLD_MAP_VERSION,
        "known_cases_are_regression_tests": True,
        "headline": {
            "mapping": GOLD_MAP_VERSION,
            "finding_clause_is_not_admission": True,
            "undecided_remains_searchable": True,
            "approved_chain_does_not_upgrade_investigation": True,
            "zero_false_must_be_read_with_abstention": True,
            "reference_counts": (payload.get("reference") or {}).get("counts"),
            "treatment_counts": (payload.get("treatment") or {}).get("counts"),
            "delta": payload.get("delta"),
            "cases": payload.get("cases"),
        },
    }


def write_clause_resolve_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or CLAUSE_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_clause_resolve_baseline(payload), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return target
