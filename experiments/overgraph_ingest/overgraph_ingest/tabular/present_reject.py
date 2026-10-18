"""Reject heading metadata on the simple Tabular answer path."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_tabular_present_run_baseline,
)
from overgraph_ingest.tabular.cells import VARIANT_D, VARIANT_E
from overgraph_ingest.tabular.jev_io import P0_STATUS_INSTRUCTIONS
from overgraph_ingest.tabular.present_run import PRESENT, TEXT
from overgraph_ingest.tabular.prompts import PROMPT_P0, instruction_for
from overgraph_ingest.tabular.search import DEFAULT_K

ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = ROOT / "eval"
PRESENT_REJECT_ID = "phase2-tabular-present-reject-v1"
PRESENT_REJECT_PATH = ROOT / "baselines" / f"{PRESENT_REJECT_ID}.json"


def review_present_reject(run: dict[str, object] | None = None) -> dict[str, object]:
    if instruction_for(PROMPT_P0) != P0_STATUS_INSTRUCTIONS:
        raise ValueError("rejecting present must leave P0 unchanged")
    if DEFAULT_K != 5:
        raise ValueError("tabular default k must stay 5")
    payload = run or load_tabular_present_run_baseline()
    decision = payload["decision"]
    if decision["fewer_silent_false_and_kept_positives"]:
        raise ValueError("present rejection expects a negative quality result")
    text = payload["headline"][TEXT]["polarity"]
    present = payload["headline"][PRESENT]["polarity"]
    paired = payload["paired"]
    if present["negative_false_answer"] != text["negative_false_answer"]:
        raise ValueError("present rejection expects unchanged silent false answers")
    if present["positive_correct"] > text["positive_correct"]:
        raise ValueError("present rejection expects no gain in correct positives")
    return {
        "operation": "tabular_present_reject",
        "experiment": PRESENT_REJECT_ID,
        "verdict": "rejected",
        "rejected": PRESENT,
        "kept": TEXT,
        "does_not_change_retrieval": True,
        "does_not_change_embeddings": True,
        "does_not_change_ingest": True,
        "does_not_change_default_prompt": True,
        "does_not_run_c": True,
        "does_not_run_reserved_holdout": True,
        "do_not_add_more_metadata_fields": True,
        "do_not_start_hypothesis_2_because_cheaper_failed": True,
        "hypothesis_2_not_built": True,
        "pause_micro_optimization": True,
        "next_quality_needs_new_capability": True,
        "do_not_compare_development_to_holdout": True,
        "original_embeddings_stay": True,
        "headings_are_not_excerpts": True,
        "same_five_units": True,
        "one_jev_call": True,
        "default_remains_d": True,
        "e_is_strongest_measured_candidate": True,
        "performance_reference": VARIANT_E,
        "default": VARIANT_D,
        "headline": {
            "text_full_success": payload["headline"][TEXT]["full_success_rate"],
            "present_full_success": payload["headline"][PRESENT]["full_success_rate"],
            "text_positive_correct": text["positive_correct"],
            "present_positive_correct": present["positive_correct"],
            "silent_false": text["negative_false_answer"],
            "changed": paired["changed"],
            "lost_positive": paired["lost_positive"],
            "new_false_positive": paired["new_false_positive"],
            "heading_cited": payload["heading_cited"],
            "enrich_hit@5": 81,
            "holdout_e_full_success": RETRIEVAL_CONCLUSIONS["tabular_holdout_e_full_success"],
        },
        "reason": (
            "PRESENT did not reduce silent false answers and lost one "
            "previously correct positive. Headings in embeddings did not "
            "raise hit@5. Do not send more structure to Jev on this "
            "answer path. Do not start ingest labeling because the "
            "cheaper representations failed. Pause micro-optimization "
            "of the same five TextUnits."
        ),
    }


def freeze_present_reject(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": PRESENT_REJECT_ID,
        "label": (
            "Negative experiment: stored headings in Jev context are not "
            "part of the simple Tabular answer path. Text-only answer_cell "
            "stays. Default stays D. Dense k=5 remains the strongest "
            "measured candidate."
        ),
        "do_not_overwrite": True,
        "verdict": "rejected",
        "rejected": PRESENT,
        "kept": TEXT,
        "does_not_run_c": True,
        "does_not_run_reserved_holdout": True,
        "do_not_add_more_metadata_fields": True,
        "do_not_start_hypothesis_2_because_cheaper_failed": True,
        "pause_micro_optimization": True,
        "next_quality_needs_new_capability": True,
        "do_not_compare_development_to_holdout": True,
        "default_remains_d": True,
        "e_is_strongest_measured_candidate": True,
        "headline": payload.get("headline"),
        "reason": payload.get("reason"),
    }


def write_present_reject_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or PRESENT_REJECT_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_present_reject(payload), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return target


def write_present_reject_table(
    payload: dict[str, object],
    directory: Path | None = None,
) -> Path:
    target = (directory or EVAL_DIR) / "present-reject-v1.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    h = payload["headline"]
    target.write_text(
        "\n".join(
            [
                "# Heading metadata to Jev rejected",
                "",
                "PRESENT is not part of the simple Tabular answer path.",
                "Text-only `answer_cell` stays. Default stays D.",
                "Dense k=5 remains the strongest measured candidate.",
                "",
                (
                    f"Development TEXT {h['text_full_success']:.1%} "
                    f"({h['text_positive_correct']} correct positives) "
                    f"against PRESENT {h['present_full_success']:.0%} "
                    f"({h['present_positive_correct']}). "
                    f"Silent false stayed {h['silent_false']}. "
                    f"Changed cells {h['changed']}/200. "
                    f"Lost positives {h['lost_positive']}."
                ),
                "",
                (
                    f"Headings in embeddings left hit@5 at "
                    f"{h['enrich_hit@5']}/84. "
                    "Do not compare the development 89.5% with the "
                    f"separate Dense k=5 holdout {h['holdout_e_full_success']:.0%}."
                ),
                "",
                payload["reason"],
                "",
                "Structure stays for navigation and citations.",
                "It is not sent to Jev on this answer path.",
                "Next quality needs a new capability, not another",
                "variation of the same five TextUnits.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return target


def refuse_more_metadata() -> None:
    raise RuntimeError(
        "heading metadata to Jev is rejected. Do not add more metadata fields."
    )


def refuse_reserved_present_holdout() -> None:
    raise RuntimeError(
        "do not run the reserved holdout on rejected heading metadata."
    )


def refuse_hypothesis_2_from_this_line() -> None:
    raise RuntimeError(
        "do not start ingest labeling because cheaper representations failed."
    )
