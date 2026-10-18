"""Diagnostic split of the 17 proposed predicates. No new Jev or controller."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.coverage.proposed import (
    AMBIGUOUS,
    CAUSES,
    INCOMPLETE_REFERENCE,
    MISSING_SPAN,
    OTHER_RELATION,
    PARAPHRASE,
    PROPOSED_ROWS,
    classify_proposed,
)

ROOT = Path(__file__).resolve().parents[2]
PROPOSED_BASELINE_ID = "phase2-proof-proposed-v1"
PROPOSED_BASELINE_PATH = ROOT / "baselines" / f"{PROPOSED_BASELINE_ID}.json"


def run_proof_proposed() -> dict[str, object]:
    rows = [classify_proposed(row) for row in PROPOSED_ROWS]
    by_cause = {name: [row["id"] for row in rows if row["cause"] == name] for name in CAUSES}
    return {
        "operation": "coverage",
        "experiment": "proof_proposed_v1",
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_change_evidence_contract": True,
        "no_new_jev": True,
        "no_looser_verified_rule": True,
        "proposed_count": len(rows),
        "more_information_can_verify_count": sum(1 for row in rows if row["more_information_can_verify"]),
        "semantic_paraphrase_count": len(by_cause[PARAPHRASE]),
        "other_relation_count": len(by_cause[OTHER_RELATION]),
        "missing_relation_in_span_count": len(by_cause[MISSING_SPAN]),
        "incomplete_reference_count": len(by_cause[INCOMPLETE_REFERENCE]),
        "ambiguous_count": len(by_cause[AMBIGUOUS]),
        "causes": by_cause,
        "rows": rows,
    }


def freeze_proof_proposed_baseline(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": PROPOSED_BASELINE_ID,
        "label": (
            "Frozen: the 17 proposed predicates are not one problem. "
            "More hops do not verify them. Do not loosen verified."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "no_new_jev": True,
        "no_looser_verified_rule": True,
        "headline": {
            "proposed_count": payload.get("proposed_count"),
            "more_information_can_verify_count": payload.get("more_information_can_verify_count"),
            "semantic_paraphrase_count": payload.get("semantic_paraphrase_count"),
            "other_relation_count": payload.get("other_relation_count"),
            "missing_relation_in_span_count": payload.get("missing_relation_in_span_count"),
            "incomplete_reference_count": payload.get("incomplete_reference_count"),
            "ambiguous_count": payload.get("ambiguous_count"),
        },
        "causes": payload.get("causes"),
        "rows": payload.get("rows"),
    }


def write_proof_proposed_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or PROPOSED_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_proof_proposed_baseline(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def load_proof_proposed_baseline(path: Path | None = None) -> dict[str, object]:
    return json.loads((path or PROPOSED_BASELINE_PATH).read_text(encoding="utf-8"))
