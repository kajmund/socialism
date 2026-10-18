from overgraph_ingest.coverage.gate_baseline import (
    GATE_COVERAGE_BASELINE_ID,
    freeze_gate_carveout_baseline,
    load_gate_carveout_baseline,
)
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_gate_coverage_baseline,
)


def test_gate_coverage_baseline_is_not_ready() -> None:
    frozen = load_gate_coverage_baseline()
    assert frozen["id"] == GATE_COVERAGE_BASELINE_ID
    assert frozen["ready_for_default_controller"] is False
    assert frozen["does_not_replace_coverage_v3"] is True
    assert frozen["proof_rule"] == "current"
    assert frozen["proof_gate"] is True
    assert frozen["classify_unchanged"] is True
    assert frozen["discovery_unchanged"] is True
    assert frozen["zero_false_complete"] is False
    headline = frozen["headline"]
    assert headline["classified_b5"] == 482
    assert headline["baseline_classified_b5"] == 482
    assert headline["jev_calls_b5"] == 184
    assert headline["hop_fetches_b5"] == 12
    assert headline["false_complete"] == [
        "Avtal_12_Uppsagningsbesked_overenskommelse_avslut.docx"
    ]
    assert headline["blocked_true_positive"] == ["Avtal_60_Pilotavtal_PoC.docx"]
    assert headline["blocked_false_complete"] == []
    assert headline["undecided_count"] == 1
    assert headline["first_complete_classified"] is None
    assert RETRIEVAL_CONCLUSIONS["proof_gate_applied_to_v3"] is False
    assert RETRIEVAL_CONCLUSIONS["proof_gate_coverage_zero_false"] is False
    assert RETRIEVAL_CONCLUSIONS["proof_gate_blocked_true_positive"] is True
    assert RETRIEVAL_CONCLUSIONS["next_open_cost"] == "evidence_found_must_answer_dependencies"
    assert load_gate_carveout_baseline()["id"] == GATE_COVERAGE_BASELINE_ID


def test_freeze_gate_carveout_reads_live_shape() -> None:
    payload = {
        "wall_seconds": 1.0,
        "proof_gate": True,
        "golds": [
            {
                "gold_id": "liability-secrecy-carveout",
                "budgets": [
                    {
                        "budget": 1,
                        "classified": 100,
                        "document_recall": 0.0,
                        "unresolved_relevant_documents": ["Avtal_46_SaaS_avtal.docx"],
                        "evidence_found_nonrelevant": [],
                    },
                    {
                        "budget": 5,
                        "classified": 482,
                        "jev_calls": 184,
                        "hop_fetches": 12,
                        "document_recall": 0.8571428571428571,
                        "first_complete_classified": None,
                        "evidence_found_nonrelevant": [
                            "Avtal_12_Uppsagningsbesked_overenskommelse_avslut.docx"
                        ],
                        "gate_blocked": {
                            "blocked_false_complete": [],
                            "blocked_true_positive": ["Avtal_60_Pilotavtal_PoC.docx"],
                            "undecided_count": 1,
                        },
                        "budget_exhausted_documents": 92,
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
                "treatment": None,
            },
            "budgets": [
                {"budget": 1, "baseline": {"classified": 100}},
                {"budget": 5, "baseline": {"classified": 482}},
            ],
        },
    }
    frozen = freeze_gate_carveout_baseline(payload)
    assert frozen["zero_false_complete"] is False
    assert frozen["headline"]["blocked_true_positive"] == ["Avtal_60_Pilotavtal_PoC.docx"]
    assert frozen["ready_for_default_controller"] is False
