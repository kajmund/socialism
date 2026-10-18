"""Reject heading-enriched embeddings as the Tabular default representation."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.retrieval.conclusions import load_tabular_enrich_run_baseline
from overgraph_ingest.tabular.enrich import LOCAL, ORIGINAL, STRUCTURE
from overgraph_ingest.tabular.jev_io import P0_STATUS_INSTRUCTIONS
from overgraph_ingest.tabular.prompts import PROMPT_P0, instruction_for
from overgraph_ingest.tabular.search import DEFAULT_K

ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = ROOT / "eval"
ENRICH_REJECT_ID = "phase2-tabular-enrich-reject-v1"
ENRICH_REJECT_PATH = ROOT / "baselines" / f"{ENRICH_REJECT_ID}.json"


def review_enrich_reject(run: dict[str, object] | None = None) -> dict[str, object]:
    if instruction_for(PROMPT_P0) != P0_STATUS_INSTRUCTIONS:
        raise ValueError("rejecting B must leave P0 unchanged")
    if DEFAULT_K != 5:
        raise ValueError("tabular default k must stay 5")
    payload = run or load_tabular_enrich_run_baseline()
    headline = payload["headline"]
    a = headline[ORIGINAL]
    b = headline[STRUCTURE]
    if a["gold_hits_at_5"] != b["gold_hits_at_5"]:
        raise ValueError("B rejection expects a tied hit@5")
    return {
        "operation": "tabular_enrich_reject",
        "experiment": ENRICH_REJECT_ID,
        "verdict": "rejected",
        "rejected": STRUCTURE,
        "kept": ORIGINAL,
        "does_not_run_c": True,
        "does_not_run_jev": True,
        "does_not_change_ingest": True,
        "does_not_change_embeddings": True,
        "original_embeddings_stay": True,
        "search_is_not_evidence": True,
        "hypothesis_2_not_built": True,
        "do_not_run_c_automatically": True,
        "default_remains_d": True,
        "next_is_candidate_presentation": True,
        "headline": {
            "hit@5": a["hit@5"],
            "gold_hits_at_5": a["gold_hits_at_5"],
            "a_hit@3": a["hit@3"],
            "b_hit@3": b["hit@3"],
            "a_hit@10": a["hit@10"],
            "b_hit@10": b["hit@10"],
            "a_mrr": a["mrr"],
            "b_mrr": b["mrr"],
            "a_hard_negative@5": a["hard_negative@5"],
            "b_hard_negative@5": b["hard_negative@5"],
            "a_tokens": payload["variants"][ORIGINAL]["prompt_tokens"],
            "b_tokens": payload["variants"][STRUCTURE]["prompt_tokens"],
        },
        "reason": (
            "B did not add gold to the k=5 budget. It nearly doubled "
            "embedding tokens. Nearby-clause errors remain a Jev problem."
        ),
        "specified_not_run": [LOCAL],
    }


def freeze_enrich_reject(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": ENRICH_REJECT_ID,
        "label": (
            "Negative experiment: heading-enriched embeddings are not "
            "the Tabular Review search representation. Original TextUnit "
            "embeddings stay. C is not run."
        ),
        "do_not_overwrite": True,
        "verdict": "rejected",
        "rejected": STRUCTURE,
        "kept": ORIGINAL,
        "does_not_run_c": True,
        "does_not_run_jev": True,
        "original_embeddings_stay": True,
        "next_is_candidate_presentation": True,
        "default_remains_d": True,
        "headline": payload.get("headline"),
        "reason": payload.get("reason"),
    }


def write_enrich_reject_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or ENRICH_REJECT_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_enrich_reject(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def write_enrich_reject_table(
    payload: dict[str, object],
    directory: Path | None = None,
) -> Path:
    target = (directory or EVAL_DIR) / "enrich-reject-v1.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    h = payload["headline"]
    target.write_text(
        "\n".join(
            [
                "# Heading-enriched embeddings rejected",
                "",
                "B is not the Tabular Review search representation.",
                "Original embeddings stay. C is not run.",
                "",
                f"hit@5 stayed {h['gold_hits_at_5']}/84. "
                f"B used {h['b_tokens']} embedding tokens against "
                f"A {h['a_tokens']}.",
                "",
                payload["reason"],
                "",
                "Next: present stored headings to Jev on the same five units.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return target
