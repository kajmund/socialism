"""Diagnose the 34 leftover gold YES. No new Jev. No next ability."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.coverage.anaphor_run import run_anaphor_resolve
from overgraph_ingest.coverage.chain_run import load_blind_traces
from overgraph_ingest.coverage.leftover_diagnosis import (
    QUALITY_REFERENCE,
    ROWS,
    public_rows,
    summarize,
)
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION

ROOT = Path(__file__).resolve().parents[2]
LEFTOVER_BASELINE_ID = "phase2-leftover-diagnosis-v1"
LEFTOVER_BASELINE_PATH = ROOT / "baselines" / f"{LEFTOVER_BASELINE_ID}.json"


def run_leftover_diagnosis(
    *,
    path: Path | None = None,
    db_path: Path | None = None,
    dense_dimension: int = 3072,
) -> dict[str, object]:
    traces = load_blind_traces(path)
    observed_why: dict[str, str | None] = {}
    live_leftover: list[str] | None = None
    if traces:
        payload = run_anaphor_resolve(
            path=path, db_path=db_path, dense_dimension=dense_dimension
        )
        if payload["decisions"]:
            live_leftover = list(payload["treatment"]["leftover_genuine"])
            if set(live_leftover) != set(ROWS):
                raise ValueError(
                    "live leftover does not match leftover diagnosis table: "
                    f"missing={sorted(set(live_leftover) - set(ROWS))} "
                    f"extra={sorted(set(ROWS) - set(live_leftover))}"
                )
            by_id = {str(row["document_id"]): row for row in payload["decisions"]}
            for document_id in ROWS:
                judged = by_id.get(document_id)
                observed_why[document_id] = None if judged is None else judged.get("why")
    return {
        "operation": "diagnosis",
        "experiment": "leftover_diagnosis_v1",
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_rewrite_history": True,
        "applied_to_v3": False,
        "no_new_jev": True,
        "no_new_controller": True,
        "does_not_start_next_ability": True,
        "quality_reference_frozen": True,
        "same_mapping": GOLD_MAP_VERSION,
        "quality_reference": QUALITY_REFERENCE,
        "rows": public_rows(observed_why),
        "summary": summarize(),
        "live_leftover": live_leftover,
        "live_leftover_matches_table": live_leftover is None or set(live_leftover) == set(ROWS),
    }


def freeze_leftover_baseline(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": LEFTOVER_BASELINE_ID,
        "label": (
            "Frozen: diagnostic distribution of the 34 leftover genuine YES after "
            "anaphor-list. No new Jev. Does not start the next ability. "
            "19/53 remains the quality reference."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "applied_to_v3": False,
        "no_new_jev": True,
        "does_not_start_next_ability": True,
        "quality_reference_frozen": True,
        "same_mapping": GOLD_MAP_VERSION,
        "headline": {
            "quality_reference": payload.get("quality_reference"),
            "summary": payload.get("summary"),
            "rows": payload.get("rows"),
        },
    }


def write_leftover_baseline(payload: dict[str, object], path: Path | None = None) -> Path:
    target = path or LEFTOVER_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_leftover_baseline(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target
