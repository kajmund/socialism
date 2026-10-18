"""Compare clause-resolve with anaphor and list anchoring. Same gold-map v2."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.coverage.ability_curve import ability_curve
from overgraph_ingest.coverage.anaphor_resolve import ANAPHOR_CONTRACT, assess_with_anaphors
from overgraph_ingest.coverage.chain_run import _gold, load_blind_traces, score_variant
from overgraph_ingest.coverage.clause_resolve import CLAUSE_CONTRACT, assess_with_clauses
from overgraph_ingest.coverage.clause_run import load_catalog
from overgraph_ingest.coverage.stop_replay import INVESTIGATION_PARTIAL
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION

ROOT = Path(__file__).resolve().parents[2]
ANAPHOR_BASELINE_ID = "phase2-anaphor-list-v1"
ANAPHOR_BASELINE_PATH = ROOT / "baselines" / f"{ANAPHOR_BASELINE_ID}.json"
CURVE_BASELINE_ID = "phase2-ability-curve-v1"
CURVE_BASELINE_PATH = ROOT / "baselines" / f"{CURVE_BASELINE_ID}.json"
KNOWN_CASES = (
    "avtal_106.docx",
    "avtal_107.docx",
    "avtal_140.docx",
    "avtal_171.docx",
    "avtal_175.docx",
    "avtal_176.docx",
    "avtal_118.docx",
    "avtal_138.docx",
    "avtal_103.docx",
)


def run_anaphor_resolve(
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
    reference = [assess_with_clauses(trace, units) for trace in traces]
    treatment = [assess_with_anaphors(trace, units) for trace in traces]
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
    extra = sum(int(row.get("extra_units_fetched") or 0) for row in treatment) - sum(
        int(row.get("extra_units_fetched") or 0) for row in reference
    )
    by_id = {str(row["document_id"]): row for row in treatment}
    ref_true = set(ref_score["true_support"])
    treat_true = set(treat_score["true_support"])
    curve = ability_curve(
        anaphor_true=treat_score["counts"]["true_support"],
        anaphor_false=treat_score["counts"]["false_approvals"],
    )
    return {
        "operation": "coverage",
        "experiment": "anaphor_list_v1",
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_rewrite_history": True,
        "applied_to_v3": False,
        "no_new_jev": True,
        "no_new_controller": True,
        "does_not_concatenate_units": True,
        "same_mapping_for_both_variants": GOLD_MAP_VERSION,
        "known_cases_are_regression_tests": True,
        "finding_antecedent_is_not_admission": True,
        "approved_chain_does_not_upgrade_investigation": True,
        "zero_false_must_be_read_with_abstention": True,
        "reference": {"contract": CLAUSE_CONTRACT, **ref_score},
        "treatment": {"contract": ANAPHOR_CONTRACT, **treat_score},
        "delta": {
            "true_support": len(treat_true) - len(ref_true),
            "new_true_support": sorted(treat_true - ref_true),
            "lost_true_support": sorted(ref_true - treat_true),
            "false_approvals": treat_score["counts"]["false_approvals"]
            - ref_score["counts"]["false_approvals"],
            "leftover_genuine": treat_score["counts"]["leftover_genuine"]
            - ref_score["counts"]["leftover_genuine"],
            "extra_units_fetched": extra,
        },
        "ability_curve": curve,
        "cases": {
            path: {
                "examined_support": (by_id.get(path) or {}).get("examined_support"),
                "why": (by_id.get(path) or {}).get("why"),
                "discourse_link": (by_id.get(path) or {}).get("discourse_link"),
                "investigation": INVESTIGATION_PARTIAL,
            }
            for path in KNOWN_CASES
        },
        "decisions": treatment,
    }


def freeze_anaphor_baseline(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": ANAPHOR_BASELINE_ID,
        "label": (
            "Frozen: anaphor and list anchoring on the clause-resolve contract. "
            "Does not concatenate units. Known cases are regression tests."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "applied_to_v3": False,
        "same_mapping_for_both_variants": GOLD_MAP_VERSION,
        "known_cases_are_regression_tests": True,
        "headline": {
            "mapping": GOLD_MAP_VERSION,
            "does_not_concatenate_units": True,
            "finding_antecedent_is_not_admission": True,
            "approved_chain_does_not_upgrade_investigation": True,
            "reference_counts": (payload.get("reference") or {}).get("counts"),
            "treatment_counts": (payload.get("treatment") or {}).get("counts"),
            "delta": payload.get("delta"),
            "ability_curve": payload.get("ability_curve"),
            "cases": {
                path: {
                    "examined_support": row.get("examined_support"),
                    "why": row.get("why"),
                    "how": ((row.get("discourse_link") or {}) or {}).get("how"),
                }
                for path, row in (payload.get("cases") or {}).items()
            },
        },
    }


def freeze_ability_curve_baseline(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": CURVE_BASELINE_ID,
        "label": (
            "Frozen: ability curve. Hop-always is gold outcomes, not verified proofs. "
            "Same gold-map v2 after the chain contract."
        ),
        "do_not_overwrite": True,
        "headline": {"curve": payload.get("ability_curve")},
    }


def write_anaphor_baseline(payload: dict[str, object], path: Path | None = None) -> Path:
    target = path or ANAPHOR_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_anaphor_baseline(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def write_ability_curve_baseline(payload: dict[str, object], path: Path | None = None) -> Path:
    target = path or CURVE_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_ability_curve_baseline(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target
