"""Freeze: GPT-OSS is rejected as a general second opinion on Jev."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.cerebras.prompt import TASK
from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE
from overgraph_ingest.retrieval.conclusions import load_cerebras_second_opinion_baseline

ROOT = Path(__file__).resolve().parents[2]
ESCALATION_ID = "phase2-cerebras-second-opinion-rejected-v1"
ESCALATION_PATH = ROOT / "baselines" / f"{ESCALATION_ID}.json"
MEASUREMENT_ID = "phase2-cerebras-second-opinion-v1"
CLASSIFY_REFERENCE = "phase2-jev-classify-c8"


def freeze_second_opinion_rejected() -> dict[str, object]:
    measured = load_cerebras_second_opinion_baseline()
    summary = (measured.get("headline") or {}).get("summary") or {}
    return {
        "id": ESCALATION_ID,
        "label": (
            "Negative experiment: GPT-OSS is rejected as a general second "
            "opinion on Jev. Net +1 on 233 overlapping keys. 19 of 27 Jev "
            "errors are shared. UNCERTAIN is not an escalation signal. "
            "Do not build a model router. Jev C@8 remains the classify "
            "reference. Does not replace C@8 or output v1. 24/53 remains "
            "the quality reference."
        ),
        "do_not_overwrite": True,
        "verdict": "rejected_for_general_escalation",
        "do_not_deploy": True,
        "do_not_build_model_router": True,
        "disagreement_is_not_uncertainty": True,
        "uncertain_does_not_steer_escalation": True,
        "classify_reference": CLASSIFY_REFERENCE,
        "measurement": MEASUREMENT_ID,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_replace_cerebras_output": True,
        "applied_to_v3": False,
        "k200_not_started": True,
        "task": TASK,
        "headline": {
            "quality_reference": QUALITY_REFERENCE,
            "summary": {
                "overlap": summary.get("total_overlap"),
                "jev_errors": summary.get("total_jev_errors"),
                "corrected": summary.get("total_corrected"),
                "worsened": summary.get("total_worsened"),
                "same_error": summary.get("total_same_error"),
                "net": int(summary.get("total_corrected") or 0)
                - int(summary.get("total_worsened") or 0),
                "jev_uncertain": summary.get("total_jev_uncertain"),
                "uncertain_resolved_correct": summary.get(
                    "total_uncertain_resolved_correct"
                ),
                "uncertain_resolved_wrong": summary.get(
                    "total_uncertain_resolved_wrong"
                ),
                "mean_jev_precision": summary.get("mean_jev_precision"),
                "mean_cerebras_precision": summary.get("mean_cerebras_precision"),
            },
        },
    }


def write_second_opinion_rejected(path: Path | None = None) -> Path:
    target = path or ESCALATION_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_second_opinion_rejected(), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return target
