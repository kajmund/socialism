"""Independent review of the live proof stack. Does not start the next ability."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.coverage.leftover_diagnosis import QUALITY_REFERENCE
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION

ROOT = Path(__file__).resolve().parents[2]
REVIEW_BASELINE_ID = "phase2-ability-review-v1"
REVIEW_BASELINE_PATH = ROOT / "baselines" / f"{REVIEW_BASELINE_ID}.json"

LIVE_PATH = (
    "chain_contract.assess_chain",
    "clause_resolve.assess_with_clauses",
    "anaphor_resolve.assess_with_anaphors",
)

HYPOTHESIS_A = {
    "name": "exception_paraphrase",
    "table_count": 7,
    "is_one_construction": False,
    "constructions": {
        "omfattar_inte": [
            "avtal_134.docx",
            "avtal_163.docx",
            "avtal_172.docx",
            "avtal_184.docx",
            "avtal_190.docx",
        ],
        "higher_cap": ["avtal_157.docx"],
        "double_negation": ["avtal_193.docx"],
    },
    "do_not_expand": ("EXCEPTION_RE", "LINK_RE"),
    "predication_model_ready": False,
    "predication_model_why": (
        "proof_logic.classify_predication is stacked on rejected LINK_RE and "
        "proof_gate polarity. split_predications is only sentence splitting."
    ),
}

HYPOTHESIS_B = {
    "name": "citation_label",
    "count": 5,
    "documents": [
        "avtal_118.docx",
        "avtal_125.docx",
        "avtal_141.docx",
        "avtal_153.docx",
        "avtal_179.docx",
    ],
    "is_one_construction": True,
    "source_relation_already_holds": True,
    "blocker": (
        "chain_contract.CITATION_RE and clause_resolve.parse_citations see "
        "only avsnitt|punkt|§ plus arabic digits. artikel, klausul, and roman "
        "numbers never become unresolved_citation, so the clause layer never runs."
    ),
    "constraints": (
        "one_parser_not_a_third_regex",
        "chain_must_recognize_label_or_clause_layer_never_runs",
        "keep_citation_kind_in_lookup",
        "finding_clause_is_not_admission",
        "roman_is_not_arabic_alias",
        "artikel_is_not_section_alias",
    ),
}

DISCOVERY_REGRESSIONS = ("avtal_135.docx", "avtal_159.docx", "avtal_168.docx")

REVIEW = {
    "quality_reference": QUALITY_REFERENCE,
    "same_mapping": GOLD_MAP_VERSION,
    "tracks": {
        "proof_evaluation_examined_undecided": 20,
        "discovery_never_examined": 14,
        "perfect_proof_still_misses_unexamined": True,
    },
    "live_path": LIVE_PATH,
    "live_path_applied_to_v3": False,
    "hypothesis_a": HYPOTHESIS_A,
    "hypothesis_b": HYPOTHESIS_B,
    "discovery_regressions_if_found": DISCOVERY_REGRESSIONS,
    "does_not_start_next_ability": True,
    "does_not_choose_by_intuition": True,
    "bench_must_decide": True,
}


def review_payload() -> dict[str, object]:
    return {
        "operation": "review",
        "experiment": "ability_review_v1",
        "no_new_jev": True,
        "no_new_controller": True,
        "applied_to_v3": False,
        "does_not_start_next_ability": True,
        **REVIEW,
    }


def freeze_review_baseline(payload: dict[str, object] | None = None) -> dict[str, object]:
    body = payload or review_payload()
    return {
        "id": REVIEW_BASELINE_ID,
        "label": (
            "Frozen: independent review of the live proof stack before the next "
            "ability. Hypothesis A is three constructions. Hypothesis B is one "
            "label-recognition gap. Neither is started. 19/53 remains the "
            "quality reference."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "applied_to_v3": False,
        "no_new_jev": True,
        "does_not_start_next_ability": True,
        "headline": {
            "quality_reference": body.get("quality_reference"),
            "tracks": body.get("tracks"),
            "live_path": body.get("live_path"),
            "hypothesis_a": body.get("hypothesis_a"),
            "hypothesis_b": body.get("hypothesis_b"),
            "discovery_regressions_if_found": body.get("discovery_regressions_if_found"),
        },
    }


def write_review_baseline(path: Path | None = None) -> Path:
    target = path or REVIEW_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_review_baseline(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target
