"""Freeze: 1x50 is the fast naive baseline. 2x50 is the scale mode. No routing."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.cerebras.pricing import RATE_CARD_DATE, cost_usd
from overgraph_ingest.cerebras.prompt import TASK
from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE
from overgraph_ingest.retrieval.conclusions import (
    load_cerebras_output_baseline,
    load_cerebras_rerank_baseline,
    load_cerebras_split50_baseline,
)

ROOT = Path(__file__).resolve().parents[2]
MODES_ID = "phase2-cerebras-modes-v1"
MODES_PATH = ROOT / "baselines" / f"{MODES_ID}.json"
FAST_ID = "phase2-cerebras-output-v1"
SCALE_ID = "phase2-cerebras-split50-v1"
MODEL = "gpt-oss-120b"


def freeze_cerebras_modes() -> dict[str, object]:
    output = load_cerebras_output_baseline()
    split = load_cerebras_split50_baseline()
    fast = (output.get("headline") or {}).get("summary") or {}
    scale = (split.get("headline") or {}).get("summary") or {}
    fast_true = _k50_true_matches((output.get("headline") or {}).get("golds") or [])
    fast_cost = cost_usd(
        MODEL,
        int(fast["total_prompt_tokens"]),
        int(fast["total_completion_tokens"]),
    )
    return {
        "id": MODES_ID,
        "label": (
            "Frozen decision: 1x50 GPT-OSS medium plus minimal JSON remains "
            "the fast naive baseline. 2x50 is a successful scale mode with "
            "more gold clauses and lower precision. Do not add automatic "
            "routing between them. Do not start k=200. Next isolated "
            "measurement is a Jev versus GPT-OSS second-opinion replay."
        ),
        "do_not_overwrite": True,
        "verdict": "keep_1x50_fast_baseline",
        "fast_mode": FAST_ID,
        "scale_mode": SCALE_ID,
        "no_automatic_k_routing": True,
        "k200_not_started": True,
        "next_isolated_experiment": "second_opinion",
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_replace_cerebras_output": True,
        "does_not_replace_cerebras_split50": True,
        "applied_to_v3": False,
        "task": TASK,
        "headline": {
            "quality_reference": QUALITY_REFERENCE,
            "model": MODEL,
            "rate_card_date": RATE_CARD_DATE,
            "fast": {
                "k": 50,
                "calls_per_question": 1,
                "true_matches": fast_true,
                "mean_precision": fast.get("mean_precision"),
                "mean_candidate_recall": fast.get("mean_candidate_recall"),
                "mean_model_seconds": fast.get("mean_model_seconds"),
                "cost_usd": fast_cost,
                "cost_per_true_match_usd": fast_cost / fast_true,
            },
            "scale": {
                "k": 100,
                "calls_per_question": 2,
                "true_matches": scale.get("total_true_matches"),
                "mean_precision": scale.get("mean_precision"),
                "mean_candidate_recall": scale.get("mean_candidate_recall"),
                "mean_model_seconds": scale.get("mean_model_seconds"),
                "cost_usd": scale.get("cost_usd"),
                "cost_per_true_match_usd": scale.get("cost_per_true_match_usd"),
                "lost_from_k50_true_matches": scale.get("total_lost_from_k50_true_matches"),
                "model_caught_gain": scale.get("total_model_caught_gain"),
            },
        },
    }


def write_cerebras_modes(path: Path | None = None) -> Path:
    target = path or MODES_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_cerebras_modes(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _k50_true_matches(output_golds: list[dict[str, object]]) -> int:
    relevant = {
        str(row["gold_id"]): int(row["relevant_in_candidates"])
        for row in (load_cerebras_rerank_baseline().get("headline") or {}).get("golds")
        or []
    }
    total = 0
    for row in output_golds:
        total += int(round(float(row["candidate_recall"]) * relevant[str(row["gold_id"])]))
    return total
