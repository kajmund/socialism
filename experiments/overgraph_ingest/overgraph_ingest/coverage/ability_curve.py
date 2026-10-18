"""Measured ability curve. Hop-always counts gold outcomes, not verified proofs."""

from __future__ import annotations

from overgraph_ingest.retrieval.conclusions import (
    load_anaphor_list_baseline,
    load_clause_resolve_baseline,
    load_decision_contract_baseline,
)

HOP_ALWAYS_NOTE = "gold_document_outcomes_not_verified_proofs"


def ability_curve(
    *,
    anaphor_true: int | None = None,
    anaphor_false: int | None = None,
    citation_true: int | None = None,
    citation_false: int | None = None,
) -> list[dict[str, object]]:
    contract = load_decision_contract_baseline()
    clause = load_clause_resolve_baseline()
    hop = contract["headline"]["reference_counts"]
    chain = contract["headline"]["treatment_counts"]
    resolved = clause["headline"]["treatment_counts"]
    rows = [
        {
            "experiment": "hop-always",
            "true_support": hop["true_support"],
            "false_approvals": hop["false_approvals"],
            "repaired_uncertain": hop["repaired_uncertain"],
            "note": HOP_ALWAYS_NOTE,
        },
        {
            "experiment": "grounded-chain",
            "true_support": chain["true_support"],
            "false_approvals": chain["false_approvals"],
            "repaired_uncertain": chain["repaired_uncertain"],
        },
        {
            "experiment": "clause-resolve",
            "true_support": resolved["true_support"],
            "false_approvals": resolved["false_approvals"],
            "repaired_uncertain": resolved["repaired_uncertain"],
        },
    ]
    if anaphor_true is not None:
        rows.append(
            {
                "experiment": "anaphor-list",
                "true_support": anaphor_true,
                "false_approvals": anaphor_false if anaphor_false is not None else 0,
                "repaired_uncertain": 0,
            }
        )
    elif citation_true is not None:
        frozen = load_anaphor_list_baseline()["headline"]["treatment_counts"]
        rows.append(
            {
                "experiment": "anaphor-list",
                "true_support": frozen["true_support"],
                "false_approvals": frozen["false_approvals"],
                "repaired_uncertain": frozen["repaired_uncertain"],
            }
        )
    if citation_true is not None:
        rows.append(
            {
                "experiment": "citation-label",
                "true_support": citation_true,
                "false_approvals": citation_false if citation_false is not None else 0,
                "repaired_uncertain": 0,
            }
        )
    return rows
