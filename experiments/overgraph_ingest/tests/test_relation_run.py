from overgraph_ingest.coverage.proof_relation import (
    COMPLETE_IN_UNIT,
    UNRESOLVED_REFERENCE,
    relation_status,
)
from overgraph_ingest.coverage.relation_baseline import (
    FALSE_COMPLETE_REASON,
    RELATION_BASELINE_ID,
    freeze_relation_carveout_baseline,
    load_relation_carveout_baseline,
)
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_relation_coverage_baseline,
)


def test_joined_secrecy_heading_is_the_measured_failure() -> None:
    assert (
        relation_status(
            texts=[
                "Begränsningarna gäller inte vid uppsåt eller grov vårdslöshet.",
                "8. Sekretess",
            ],
            required_parts=(),
        )
        == COMPLETE_IN_UNIT
    )
    assert (
        relation_status(
            texts=[
                "Begränsningarna gäller inte vid uppsåt, grov vårdslöshet eller brott mot punkt 4.",
                "4. Informationssäkerhet och dataskydd",
            ],
            required_parts=(),
        )
        == UNRESOLVED_REFERENCE
    )


def test_relation_coverage_baseline_is_frozen_and_not_ready() -> None:
    frozen = load_relation_coverage_baseline()
    assert frozen["id"] == RELATION_BASELINE_ID
    assert frozen["ready_for_default_controller"] is False
    assert frozen["does_not_replace_coverage_v3"] is True
    assert frozen["replay_14_is_not_the_live_result"] is True
    assert frozen["false_complete_reason"] == FALSE_COMPLETE_REASON
    assert frozen["extra_classifications_are_mostly"] == "other_document_discovery"
    headline = frozen["headline"]
    assert headline["leftover_at_b1"] == ["Avtal_46_SaaS_avtal.docx"]
    assert headline["leftover_at_b2"] == ["Avtal_46_SaaS_avtal.docx"]
    assert headline["first_complete_classified"] == 143
    assert headline["baseline_first_complete_classified"] == 150
    assert headline["classified_b5"] == 468
    assert headline["baseline_classified_b5"] == 482
    assert headline["false_complete_count"] == 5
    assert headline["avtal_49_falsely_complete"] is False
    assert RETRIEVAL_CONCLUSIONS["proof_relation_ready"] is False
    assert RETRIEVAL_CONCLUSIONS["proof_contract_applied_to_v3"] is False
    assert RETRIEVAL_CONCLUSIONS["next_open_cost"] == "evidence_found_must_answer_dependencies"
    assert RETRIEVAL_CONCLUSIONS["rule_b_rejected"] is True
    assert RETRIEVAL_CONCLUSIONS["cooccurrence_is_not_a_relation"] is True


def test_freeze_relation_carveout_reads_live_shape() -> None:
    payload = {
        "proof_rule": "relation",
        "wall_seconds": 1.0,
        "golds": [
            {
                "gold_id": "liability-secrecy-carveout",
                "budgets": [
                    {
                        "budget": 1,
                        "classified": 100,
                        "document_recall": 0.85,
                        "unresolved_relevant_documents": ["Avtal_46_SaaS_avtal.docx"],
                        "evidence_found_nonrelevant": [],
                    },
                    {
                        "budget": 5,
                        "classified": 468,
                        "jev_calls": 178,
                        "hop_fetches": 6,
                        "document_recall": 1.0,
                        "first_complete_classified": 143,
                        "evidence_found_nonrelevant": ["Avtal_47_Programvarulicensavtal.docx"],
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
                    "budget": 3,
                    "first_complete_classified": 143,
                    "work_after_complete": 147,
                },
            },
            "budgets": [
                {"budget": 1, "baseline": {"classified": 100}},
                {"budget": 5, "baseline": {"classified": 482, "hop_fetches": 12}},
            ],
        },
    }
    frozen = freeze_relation_carveout_baseline(payload)
    assert frozen["headline"]["false_complete_count"] == 1
    assert frozen["headline"]["classified_b5"] == 468
    assert frozen["headline"]["baseline_classified_b5"] == 482
    assert load_relation_carveout_baseline()["id"] == RELATION_BASELINE_ID
