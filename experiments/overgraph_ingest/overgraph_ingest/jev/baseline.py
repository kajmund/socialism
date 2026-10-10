"""Freeze Experiment C@8 as the official classify performance baseline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from overgraph_ingest.jev.classify import CLASSIFY_CANDIDATES_PER_CALL, DEFAULT_CLASSIFY_CONCURRENCY
from overgraph_ingest.jev.evaluate import threshold_stability

BASELINE_ID = "phase2-jev-classify-c8"
BASELINE_LABEL = (
    "Official classify baseline: frozen hybrid top-50, one TextUnit per call, "
    "concurrency 8, no extra context"
)
OFFICIAL_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{BASELINE_ID}.json"
)

ARCHITECTURE = {
    "retrieval": "hybrid",
    "classify": "individual_text_unit",
    "classify_candidates_per_call": CLASSIFY_CANDIDATES_PER_CALL,
    "prompt_batching": "rejected_for_classify",
    "winning_strategy": "C@8",
    "concurrency_cap": DEFAULT_CLASSIFY_CONCURRENCY,
    "concurrency_cap_configurable": True,
    "navigate_is_separate_from_classify": True,
    "neighbor_may_not_relabel_candidate": True,
    "completeness": "unsolved",
    "confidence_is_not_calibrated_probability": True,
    "do_not_optimize_classify_further": True,
    "operations": ["classify", "navigate", "coverage"],
    "operations_are_separate": True,
}


def freeze_classify_baseline(payload: dict[str, Any]) -> dict[str, Any]:
    runs = list(payload.get("runs") or [])
    chosen = _choose_c8(runs)
    if chosen is None:
        raise ValueError("classify baseline requires a C@8 run")
    return {
        "id": BASELINE_ID,
        "label": BASELINE_LABEL,
        "gold_id": payload.get("gold_id"),
        "question": payload.get("question"),
        "candidate_strategy": payload.get("candidate_strategy"),
        "candidate_k": payload.get("candidate_k"),
        "candidates": payload.get("candidates"),
        "jev_model": payload.get("jev_model"),
        "operation": "classify",
        "architecture": dict(ARCHITECTURE),
        "headline": {
            "precision": chosen.get("precision"),
            "recall": chosen.get("recall"),
            "wall_seconds": chosen.get("wall_seconds"),
            "concurrency": chosen.get("concurrency"),
            "batch_size": chosen.get("batch_size"),
            "model_calls": chosen.get("model_calls"),
            "errors": chosen.get("errors"),
            "predicted": chosen.get("predicted"),
            "false_positives": [
                row.get("relative_path") for row in (chosen.get("false_positives") or [])
            ],
            "false_negatives": [
                row.get("relative_path") for row in (chosen.get("false_negatives") or [])
            ],
        },
        "concurrency_sweep": [_sweep_row(run) for run in runs],
        "threshold_stability": threshold_stability(
            [list(run.get("wall_judgments") or []) for run in runs if run.get("wall_judgments")]
        ),
        "runs": [chosen],
    }


def write_official_classify_baseline(
    payload: dict[str, Any],
    path: Path | None = None,
) -> Path:
    target = path or OFFICIAL_BASELINE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(freeze_classify_baseline(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def load_official_classify_baseline(path: Path | None = None) -> dict[str, Any]:
    target = path or OFFICIAL_BASELINE_PATH
    return json.loads(target.read_text(encoding="utf-8"))


def load_baseline_judgments(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    runs = list(payload.get("runs") or [])
    chosen = _choose_c8(runs) or (runs[0] if runs else None)
    if chosen is None:
        return []
    return [dict(row) for row in (chosen.get("wall_judgments") or [])]


def _choose_c8(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    for run in runs:
        if run.get("variant") == "C@8":
            return run
        if run.get("concurrency") == 8 and run.get("batch_size") in {1, None}:
            return run
    return None


def _sweep_row(run: dict[str, Any]) -> dict[str, Any]:
    versus_c1 = run.get("versus_c1") or {}
    return {
        "variant": run.get("variant"),
        "concurrency": run.get("concurrency"),
        "batch_size": run.get("batch_size"),
        "precision": run.get("precision"),
        "recall": run.get("recall"),
        "wall_seconds": run.get("wall_seconds"),
        "speedup_vs_c1": run.get("speedup_vs_c1"),
        "label_changes_vs_c1": len(versus_c1.get("changed") or []),
        "errors": run.get("errors"),
    }
