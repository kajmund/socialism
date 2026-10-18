"""Compare COMPOSITE hop-always versus relation-in-text. Does not change v3."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.coverage.cache import load_c8_judgments
from overgraph_ingest.coverage.proof_relation import (
    COMPLETE_IN_UNIT,
    CURRENT_HOP,
    NEEDS_COMPLEMENTARY,
    PROOF_CURRENT,
    PROOF_RELATION,
    RELATION,
    UNRESOLVED_REFERENCE,
    current_status,
    evidence_in_text,
    proposed_status,
    relation_status,
)
from overgraph_ingest.coverage.v2 import DEFAULT_CACHE
from overgraph_ingest.retrieval.gold import RetrievalGold, load_retrieval_gold

ROOT = Path(__file__).resolve().parents[2]
GOLD_PATH = ROOT / "retrieval_gold" / "liability-secrecy-carveout.json"
C8_PATH = DEFAULT_CACHE["liability-secrecy-carveout"]


def evaluate_document(
    *,
    relative_path: str,
    text: str,
    gold: RetrievalGold,
    predicted: str | None = None,
    rank: int | None = None,
    role: str,
) -> dict[str, object]:
    evidence = evidence_in_text(text)
    missing_parts = _missing_group_parts(gold, relative_path, text)
    proposed = proposed_status(evidence, missing_coverage_parts=missing_parts)
    return {
        "relative_path": relative_path,
        "role": role,
        "rank": rank,
        "predicted": predicted,
        "current": current_status(),
        "proposed": proposed,
        "proposed_complete_without_hop": proposed == COMPLETE_IN_UNIT,
        "missing_coverage_parts": list(missing_parts),
        **evidence,
        "jev_yes_is_not_enough": True,
    }


def run_proof_contract(
    *,
    cache_root: Path | None = None,
    gold_path: Path | None = None,
) -> dict[str, object]:
    root = cache_root or ROOT
    gold = load_retrieval_gold(gold_path or GOLD_PATH)
    payload = json.loads((root / C8_PATH).read_text(encoding="utf-8"))
    rows = sorted(
        load_c8_judgments(payload),
        key=lambda row: (int(row.get("rank") or 10**9), str(row.get("key") or "")),
    )
    positives = [
        evaluate_document(
            relative_path=path,
            text=_first_signal_text(rows, path) or _gold_text(gold, path),
            gold=gold,
            predicted=_first_signal(rows, path).get("predicted") if _first_signal(rows, path) else None,
            rank=_first_signal(rows, path).get("rank") if _first_signal(rows, path) else None,
            role="gold_positive",
        )
        for path in gold.relevant_documents
    ]
    controls = []
    for span in gold.hard_negatives + gold.watch_negatives:
        signal = _first_signal(rows, span.relative_path)
        text = (None if signal is None else str(signal.get("text") or "")) or span.contains
        if signal is None or len(str(signal.get("text") or "")) < len(span.contains):
            text = span.contains
        controls.append(
            evaluate_document(
                relative_path=span.relative_path,
                text=text,
                gold=gold,
                predicted=None if signal is None else str(signal.get("predicted")),
                rank=None if signal is None else int(signal.get("rank") or 0),
                role="hard_negative" if span in gold.hard_negatives else "watch_negative",
            )
        )
    complete = [row for row in positives if row["proposed_complete_without_hop"]]
    return {
        "operation": "coverage",
        "experiment": "proof_contract_v1",
        "gold_id": gold.id,
        "coverage_v3_unchanged": True,
        "does_not_replace_c8": True,
        "no_new_controller": True,
        "does_not_claim_saved_classifications": True,
        "jev_yes_is_not_enough": True,
        "relation": list(RELATION),
        "current_rule": "composite_requires_hop",
        "proposed_rule": "hop_only_if_relation_missing_or_reference",
        "positives": positives,
        "controls": controls,
        "current_complete_at_first_signal": 0,
        "proposed_complete_at_first_signal": len(complete),
        "positives_expected": len(positives),
        "needs_complementary": [
            row["relative_path"]
            for row in positives
            if row["proposed"] == NEEDS_COMPLEMENTARY
        ],
        "unresolved_references": [
            row["relative_path"]
            for row in positives + controls
            if row["proposed"] == UNRESOLVED_REFERENCE
        ],
        "control_none_complete": not any(row["proposed_complete_without_hop"] for row in controls),
    }


def _first_signal(rows: list[dict[str, object]], path: str) -> dict[str, object] | None:
    for row in rows:
        if row.get("relative_path") == path and row.get("predicted") in {"YES", "UNCERTAIN"}:
            return row
    return None


def _first_signal_text(rows: list[dict[str, object]], path: str) -> str:
    row = _first_signal(rows, path)
    return "" if row is None else str(row.get("text") or "")


def _gold_text(gold: RetrievalGold, path: str) -> str:
    for span in gold.relevant_units:
        if span.relative_path == path:
            return span.contains
    return ""


def _missing_group_parts(gold: RetrievalGold, path: str, text: str) -> tuple[str, ...]:
    missing = []
    for group in gold.coverage_groups:
        if group.relative_path != path:
            continue
        missing.extend(part for part in group.contains if part not in text)
    return tuple(missing)
