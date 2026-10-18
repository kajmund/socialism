"""Freeze a completed Tabular Review run. Does not overwrite earlier baselines."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION
from overgraph_ingest.tabular.run import run_tabular_review

ROOT = Path(__file__).resolve().parents[2]
TABULAR_ID = "phase2-tabular-review-v1"
TABULAR_PATH = ROOT / "baselines" / f"{TABULAR_ID}.json"


def freeze_tabular_review(payload: dict[str, object]) -> dict[str, object]:
    comparison = payload.get("comparison") or {}
    return {
        "id": TABULAR_ID,
        "label": (
            "Frozen: Socialism Tabular Review v1. Document-local hybrid "
            "retrieval plus Jev adaptive navigation (A), Jev without "
            "navigation (B), and GPT-OSS Medium without navigation (C). "
            "New cell metrics. Does not replace C@8 or Coverage v3. "
            "24/53 remains the leftover quality reference and is not "
            "compared to cell accuracy. The 20-document set is diagnostic, "
            "not a general Tabular Review quality score."
        ),
        "selection_is_diagnostic": True,
        "selection_is_not_general_quality": True,
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "applied_to_v3": False,
        "no_coverage_controller": True,
        "no_proof_engine": True,
        "no_second_opinion": True,
        "no_model_router": True,
        "no_qwen": True,
        "no_ui": True,
        "no_socialism_integration": True,
        "synchronous": True,
        "same_mapping": GOLD_MAP_VERSION,
        "headline": payload.get("headline")
        or {
            "selection": payload.get("selection"),
            "questions": payload.get("questions"),
            "k": payload.get("k"),
            "comparison": comparison,
            "cost": payload.get("cost"),
            "errors": payload.get("errors"),
            "wall_seconds": payload.get("wall_seconds"),
            "cells": len(payload.get("cells") or []),
        },
        "reuse": payload.get("reuse"),
        "cells": payload.get("cells"),
        "scored": payload.get("scored"),
    }


def write_tabular_review_baseline(
    payload: dict[str, object] | None = None,
    path: Path | None = None,
) -> Path:
    target = path or TABULAR_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    body = payload if payload is not None else run_tabular_review()
    target.write_text(
        json.dumps(freeze_tabular_review(body), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target
