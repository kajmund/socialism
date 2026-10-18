"""Freeze: GPT-OSS medium plus minimal JSON is the naive-rerank quality setting."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.cerebras.pricing import RATE_CARD_DATE, cost_usd
from overgraph_ingest.cerebras.prompt import TASK
from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE
from overgraph_ingest.retrieval.conclusions import (
    load_cerebras_output_baseline,
    load_cerebras_rerank_baseline,
)

ROOT = Path(__file__).resolve().parents[2]
CHOSEN_ID = "phase2-cerebras-medium-chosen-v1"
CHOSEN_PATH = ROOT / "baselines" / f"{CHOSEN_ID}.json"
OUTPUT_ID = "phase2-cerebras-output-v1"
MODEL = "gpt-oss-120b"


def freeze_cerebras_medium_chosen() -> dict[str, object]:
    output = load_cerebras_output_baseline()
    summary = (output.get("headline") or {}).get("summary") or {}
    golds = (output.get("headline") or {}).get("golds") or []
    prompt = int(summary["total_prompt_tokens"])
    completion = int(summary["total_completion_tokens"])
    true_matches = _k50_true_matches(golds)
    spent = cost_usd(MODEL, prompt, completion)
    return {
        "id": CHOSEN_ID,
        "label": (
            "Frozen decision: GPT-OSS-120B medium with minimal JSON is the "
            "best measured quality setting for naive rerank. Stop tuning "
            "model parameters on the same five questions. Low is cheaper, "
            "not quality-equivalent. Qwen is rejected for this task. "
            "Next isolated measurement is k=100, not second opinion."
        ),
        "do_not_overwrite": True,
        "verdict": "keep_medium_minimal",
        "best_naive_rerank": OUTPUT_ID,
        "best_setting": "gpt-oss-120b-medium-minimal-json",
        "do_not_tune_reasoning_on_same_five": True,
        "low_is_not_quality_equivalent": True,
        "qwen_rejected_for_naive_rerank": True,
        "reasoning_off_supported": False,
        "next_isolated_experiment": "k100",
        "k200_not_started": True,
        "second_opinion_not_started": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "applied_to_v3": False,
        "task": TASK,
        "headline": {
            "quality_reference": QUALITY_REFERENCE,
            "k": 50,
            "model": MODEL,
            "reasoning_effort": "medium",
            "variant": "minimal",
            "rate_card_date": RATE_CARD_DATE,
            "summary": {
                "mean_precision": summary.get("mean_precision"),
                "mean_candidate_recall": summary.get("mean_candidate_recall"),
                "mean_model_seconds": summary.get("mean_model_seconds"),
                "total_prompt_tokens": prompt,
                "total_completion_tokens": completion,
                "true_matches": true_matches,
                "cost_usd": spent,
                "cost_per_true_match_usd": spent / true_matches,
            },
            "golds": [
                {
                    "gold_id": row.get("gold_id"),
                    "precision": row.get("precision"),
                    "candidate_recall": row.get("candidate_recall"),
                }
                for row in golds
            ],
        },
    }


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


def write_cerebras_medium_chosen(path: Path | None = None) -> Path:
    target = path or CHOSEN_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_cerebras_medium_chosen(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target
