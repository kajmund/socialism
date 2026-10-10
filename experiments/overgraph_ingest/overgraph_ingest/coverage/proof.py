"""Proof kinds for coverage stop rules. Not a Jev router."""

from __future__ import annotations

from overgraph_ingest.retrieval.gold import RetrievalGold

EXISTS = "EXISTS"
COMPOSITE = "COMPOSITE"
ABSENCE = "ABSENCE"

V2_BEST_JEV_YES = {
    "auto-renewal": 0.95,
    "notice-period": 1.0,
    "liability-cap": 1.0,
    "confidentiality": 1.0,
    "liability-secrecy-carveout": 1.0,
}


def required_parts(gold: RetrievalGold, relative_path: str) -> tuple[str, ...]:
    for group in gold.coverage_groups:
        if group.relative_path == relative_path:
            return group.contains
    return ()
