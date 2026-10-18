from overgraph_ingest.coverage.link_baseline import (
    LINK_COVERAGE_BASELINE_ID,
    freeze_link_carveout_baseline,
    load_link_carveout_baseline,
)
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_link_coverage_baseline,
)


def test_link_coverage_baseline_keeps_seven_and_zero_false() -> None:
    frozen = load_link_coverage_baseline()
    assert frozen["id"] == LINK_COVERAGE_BASELINE_ID
    assert frozen["ready_for_default_controller"] is False
    assert frozen["does_not_replace_coverage_v3"] is True
    assert frozen["discovery_unchanged"] is True
    assert frozen["zero_false_complete"] is True
    headline = frozen["headline"]
    assert headline["document_recall_b1"] == 1.0
    assert headline["leftover_at_b1"] == []
    assert headline["first_complete_classified"] == 39
    assert headline["baseline_first_complete_classified"] == 150
    assert headline["classified_b5"] == 477
    assert headline["baseline_classified_b5"] == 482
    assert headline["false_complete_count"] == 0
    assert RETRIEVAL_CONCLUSIONS["proof_link_applied_to_v3"] is False
    assert RETRIEVAL_CONCLUSIONS["proof_link_live_zero_false"] is True
    assert RETRIEVAL_CONCLUSIONS["next_open_cost"] == "evidence_found_must_answer_dependencies"
    assert load_link_carveout_baseline()["id"] == LINK_COVERAGE_BASELINE_ID


def test_freeze_link_carveout_reads_live_shape() -> None:
    payload = {
        "wall_seconds": 1.0,
        "golds": [
            {
                "gold_id": "liability-secrecy-carveout",
                "budgets": [
                    {
                        "budget": 1,
                        "classified": 100,
                        "document_recall": 1.0,
                        "unresolved_relevant_documents": [],
                        "first_complete_classified": 39,
                        "evidence_found_nonrelevant": [],
                    },
                    {
                        "budget": 5,
                        "classified": 477,
                        "jev_calls": 186,
                        "hop_fetches": 5,
                        "document_recall": 1.0,
                        "first_complete_classified": 50,
                        "evidence_found_nonrelevant": [],
                    },
                ],
            }
        ],
        "versus_baseline_v3": {
            "first_complete_evidence": {
                "baseline": {
                    "budget": 3,
                    "first_complete_classified": 150,
                    "work_after_complete": 148,
                },
                "treatment": {
                    "budget": 1,
                    "first_complete_classified": 39,
                    "work_after_complete": 61,
                },
            },
            "budgets": [
                {"budget": 1, "baseline": {"classified": 100}},
                {"budget": 5, "baseline": {"classified": 482}},
            ],
        },
    }
    frozen = freeze_link_carveout_baseline(payload)
    assert frozen["zero_false_complete"] is True
    assert frozen["headline"]["first_complete_classified"] == 39
    assert frozen["ready_for_default_controller"] is False
