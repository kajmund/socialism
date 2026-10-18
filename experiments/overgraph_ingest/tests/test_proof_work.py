from pathlib import Path

from overgraph_ingest.coverage.proof_contract import COMPLETE_IN_UNIT, NEEDS_COMPLEMENTARY
from overgraph_ingest.coverage.proof_work import rule_b_work, run_proof_work
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_proof_work_baseline,
)

import pytest


def test_rule_b_work_does_not_claim_the_hundred() -> None:
    work = rule_b_work(
        {
            "positives": [
                {"relative_path": "a.docx", "rank": 3, "proposed": COMPLETE_IN_UNIT},
                {
                    "relative_path": "Avtal_46_SaaS_avtal.docx",
                    "rank": 2,
                    "proposed": NEEDS_COMPLEMENTARY,
                },
            ],
            "controls": [
                {
                    "relative_path": "Avtal_49_IT_drift_hostingavtal.docx",
                    "proposed": "unresolved_reference",
                }
            ],
        },
        coverage_v3={
            "golds": [
                {
                    "gold_id": "liability-secrecy-carveout",
                    "budgets": [
                        {
                            "classified": 482,
                            "timeline": [
                                {
                                    "classified": 50,
                                    "documents_found": 7,
                                    "unresolved_relevant": ["x"],
                                },
                                {
                                    "classified": 150,
                                    "documents_found": 7,
                                    "unresolved_relevant": [],
                                },
                            ],
                        }
                    ],
                }
            ]
        },
    )
    assert work["complete_from_first_candidate"] == 1
    assert work["necessary_hop_count"] == 1
    assert work["necessary_hops"][0]["relation"] == "PREVIOUS"
    assert work["c8_classifications_to_last_gold_signal"] == 3
    assert work["rule_b_replay_classifications"] == 4
    assert work["observed_v3_complete_at"] == 150
    assert work["later_coverage_run_with_same_budget"] == "not_run"
    assert work["does_not_claim_saved_classifications"] is True
    assert work["false_complete_count"] == 0


def test_evidence_layers_stay_outside_the_controller() -> None:
    assert RETRIEVAL_CONCLUSIONS["evidence_layers"] == (
        "retrieval",
        "proof_evaluation",
        "navigation",
    )
    assert RETRIEVAL_CONCLUSIONS["composite_describes_proof_not_unit_count"] is True
    assert RETRIEVAL_CONCLUSIONS["proof_contract_applied_to_v3"] is False
    assert RETRIEVAL_CONCLUSIONS["proof_relation_ready"] is False
    assert RETRIEVAL_CONCLUSIONS["reward_sufficient_evidence_not_more_steps"] is True
    frozen = load_proof_work_baseline()
    assert frozen["id"] == "phase2-proof-work-v1"
    assert frozen["headline"]["rule_b_replay_classifications"] == 14
    assert frozen["later_coverage_run_with_same_budget"] == "not_run"


def test_proof_work_reads_frozen_carveout() -> None:
    if not Path("data/jev-liability-secrecy-carveout-C8.json").is_file():
        pytest.skip("local carve-out C@8 is not in the checkout")
    payload = run_proof_work()
    work = payload["work"]
    assert payload["no_new_controller"] is True
    assert work["complete_from_first_candidate"] == 6
    assert work["necessary_hop_count"] == 1
    assert work["false_complete_count"] == 0
    assert work["c8_classifications_to_last_gold_signal"] == 13
    assert work["rule_b_replay_classifications"] == 14
    assert work["later_coverage_run_with_same_budget"] == "not_run"
