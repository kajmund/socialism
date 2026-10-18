"""Stop: reallocating 50 candidates is not workspace inventory. No new ranking."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE, summarize
from overgraph_ingest.retrieval.two_stage import STAGE1_MARKS, TWO_STAGE_ID, UNLOCKS

ROOT = Path(__file__).resolve().parents[2]
INVENTORY_ID = "phase2-workspace-inventory-v1"
INVENTORY_PATH = ROOT / "baselines" / f"{INVENTORY_ID}.json"

TASKS = {
    "which_documents_may_contain_the_answer": "document_identification",
    "where_in_each_document_is_the_answer": "local_passage_rank",
    "current_score": "same_passage_score_for_both",
}

EXAMPLES = {
    "avtal_155.docx": {
        "document_identification_rank": 16,
        "local_passage_rank": 10,
        "first_relevant_passage_rank": 728,
        "constraint": "local_passage",
    },
    "avtal_135.docx": {
        "document_identification_rank": 88,
        "local_passage_rank": 2,
        "first_relevant_passage_rank": 301,
        "constraint": "document_identification",
    },
}

LIMITS = {
    "discovery": {
        "kind": "information_selection",
        "unexamined": 14,
        "all_fourteen_only_when_portfolio_included": True,
        "unlocks_blocked_by_identification": list(UNLOCKS),
    },
    "proof_evaluation": {
        "kind": "legal_understanding",
        "true_support": 24,
        "expected_yes": 53,
        "examined_undecided": 15,
    },
}

REJECTED = {
    "reallocating_the_same_fifty_candidates": True,
    "another_two_stage_experiment": True,
    "new_document_ranking_on_the_same_100": True,
}

FUTURE_NOT_STARTED = {
    "ingest_property_extraction": (
        "Unmeasured. A later workspace question could start from "
        "source-grounded ingest properties. Not assumed right for "
        "composite legal relations such as secrecy carve-outs."
    ),
}


def inventory_payload() -> dict[str, object]:
    leftover = summarize()
    return {
        "operation": "verdict",
        "experiment": "workspace_inventory_v1",
        "applied_to_v3": False,
        "no_new_jev": True,
        "no_new_controller": True,
        "does_not_change_proof": True,
        "does_not_start_next_ability": True,
        "does_not_build_document_ranking": True,
        "does_not_start_another_two_stage": True,
        "does_not_tune_ranking_on_same_100": True,
        "does_not_start_ingest_enrichment": True,
        "two_stage_is_negative": True,
        "two_stage_measurement": TWO_STAGE_ID,
        "quality_reference": QUALITY_REFERENCE,
        "tasks": TASKS,
        "examples": EXAMPLES,
        "limits": {
            **LIMITS,
            "discovery": {
                **LIMITS["discovery"],
                "unexamined": leftover["unexamined"],
                "documents": leftover["tracks"]["discovery"]["documents"],
            },
            "proof_evaluation": {
                **LIMITS["proof_evaluation"],
                "examined_undecided": leftover["examined"],
            },
        },
        "rejected": REJECTED,
        "future_not_started": FUTURE_NOT_STARTED,
        "stage1_marks_needed_for_all_fourteen": STAGE1_MARKS[-1],
        "top50_is_not_completeness": True,
        "does_not_require_jev_on_every_document": True,
        "needs_separate_handling_when_no_relevant_hit": True,
    }


def freeze_workspace_inventory(payload: dict[str, object] | None = None) -> dict[str, object]:
    body = payload or inventory_payload()
    return {
        "id": INVENTORY_ID,
        "label": (
            "Frozen: reallocating the same 50 candidates is not workspace "
            "inventory. Two-stage is a negative experiment. Do not start "
            "another two-stage run or a new document ranking on the same 100. "
            "24/53 remains the quality reference."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "applied_to_v3": False,
        "verdict": "rejected_as_completeness",
        "two_stage_is_negative": True,
        "does_not_start_another_two_stage": True,
        "does_not_build_document_ranking": True,
        "does_not_tune_ranking_on_same_100": True,
        "does_not_start_ingest_enrichment": True,
        "top50_is_not_completeness": True,
        "headline": {
            "quality_reference": body.get("quality_reference"),
            "tasks": body.get("tasks"),
            "limits": body.get("limits"),
            "rejected": body.get("rejected"),
            "future_not_started": body.get("future_not_started"),
            "examples": body.get("examples"),
            "top50_is_not_completeness": True,
            "does_not_require_jev_on_every_document": True,
            "needs_separate_handling_when_no_relevant_hit": True,
        },
    }


def write_workspace_inventory(path: Path | None = None) -> Path:
    target = path or INVENTORY_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_workspace_inventory(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target
