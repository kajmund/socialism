"""Freeze candidate-presentation protocol. Same five units. No Jev yet."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.tabular.enrich_dev import DEV_DOCUMENTS, RESERVED_DOCUMENTS
from overgraph_ingest.tabular.jev_io import P0_STATUS_INSTRUCTIONS
from overgraph_ingest.tabular.prompts import PROMPT_P0, instruction_for
from overgraph_ingest.tabular.search import DEFAULT_K

ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = ROOT / "eval"
PRESENT_ID = "tabular-present-v1"
PRESENT_EVAL_ID = "phase2-tabular-present-v1"
PRESENT_EVAL_PATH = ROOT / "baselines" / f"{PRESENT_EVAL_ID}.json"


def review_present_protocol() -> dict[str, object]:
    if instruction_for(PROMPT_P0) != P0_STATUS_INSTRUCTIONS:
        raise ValueError("present must leave P0 unchanged")
    if DEFAULT_K != 5:
        raise ValueError("tabular default k must stay 5")
    return {
        "operation": "tabular_present_protocol",
        "experiment": PRESENT_EVAL_ID,
        "gold_id": PRESENT_ID,
        "does_not_run_jev": True,
        "does_not_run_cerebras": True,
        "does_not_change_ingest": True,
        "does_not_change_embeddings": True,
        "does_not_change_retrieval": True,
        "does_not_change_default_prompt": True,
        "does_not_change_default_k": True,
        "does_not_add_jev_calls": True,
        "search_is_not_evidence": True,
        "headings_are_not_excerpts": True,
        "original_embeddings_stay": True,
        "do_not_run_c": True,
        "default_remains_d": True,
        "e_is_next_candidate": True,
        "same_five_units": True,
        "one_jev_call": True,
        "models_not_run": True,
        "development_documents": list(DEV_DOCUMENTS),
        "reserved_documents": list(RESERVED_DOCUMENTS),
        "baseline": "answer_cell text only",
        "treatment": "answer_cell plus stored heading metadata",
        "headline": {
            "same_five_units": True,
            "one_jev_call": True,
            "jev_not_run": True,
            "c_not_run": True,
            "b_rejected": True,
        },
    }


def freeze_present_protocol(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": PRESENT_EVAL_ID,
        "label": (
            "Present stored headings to Jev on the same five TextUnits. "
            "Retrieval, embeddings, and P0 stay. No Jev yet."
        ),
        "do_not_overwrite": True,
        "does_not_run_jev": True,
        "does_not_change_retrieval": True,
        "does_not_change_embeddings": True,
        "same_five_units": True,
        "one_jev_call": True,
        "original_embeddings_stay": True,
        "do_not_run_c": True,
        "default_remains_d": True,
        "models_not_run": True,
        "development_documents": payload.get("development_documents"),
        "reserved_documents": payload.get("reserved_documents"),
        "baseline": payload.get("baseline"),
        "treatment": payload.get("treatment"),
        "headline": payload.get("headline"),
    }


def write_present_protocol_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or PRESENT_EVAL_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_present_protocol(payload), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return target


def write_present_protocol_table(
    payload: dict[str, object],
    directory: Path | None = None,
) -> Path:
    target = (directory or EVAL_DIR) / "present-v1.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "\n".join(
            [
                "# Candidate presentation protocol",
                "",
                "Same five TextUnits. One `answer_cell`. P0 unchanged.",
                "Headings come from stored Structure. Evidence text stays.",
                "Excerpts stay original sentences. No Jev yet.",
                "",
                f"Baseline: {payload['baseline']}.",
                f"Treatment: {payload['treatment']}.",
                "",
                "B is rejected. C is not run. Default stays D.",
                "Reserved holdout stays unused.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return target


def refuse_present_model_run() -> None:
    raise RuntimeError(
        "candidate presentation is frozen; Jev is not run yet. "
        "Do not change retrieval or embeddings."
    )
