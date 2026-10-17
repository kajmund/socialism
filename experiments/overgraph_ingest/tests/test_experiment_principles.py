from overgraph_ingest.coverage.experiment_principles import (
    EXPERIMENTAL_RULES_NOT_PRODUCTION,
    KNOWN_ISSUES_LEFT_IN_PLACE,
    PARTS,
    REQUIREMENTS,
    freeze_principles_baseline,
    principles_payload,
)
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_experiment_principles_baseline,
)


def test_three_parts_stay_separate() -> None:
    assert PARTS == {
        "coverage_v3": "frozen_yes_plus_hop",
        "experimental_evidence_chain": "19/53_on_frozen_material",
        "future_proof_evaluation": "not_decided",
    }
    assert set(REQUIREMENTS) == {
        "measurement_integrity",
        "independent_generalization",
        "later_architectural_consolidation",
    }
    assert "c8_cache_first_run_fallback" in KNOWN_ISSUES_LEFT_IN_PLACE
    assert "evidence_run_gold_snippet_fallback" in KNOWN_ISSUES_LEFT_IN_PLACE
    assert "anaphor_resolve" in EXPERIMENTAL_RULES_NOT_PRODUCTION


def test_principles_baseline() -> None:
    frozen = load_experiment_principles_baseline()
    assert frozen["applied_to_v3"] is False
    assert frozen["does_not_start_next_ability"] is True
    assert frozen["headline"]["search_is_closer_to_done_than_legal_verification"] is True
    assert RETRIEVAL_CONCLUSIONS["official_comparison_requires_named_c8"] is True
    assert RETRIEVAL_CONCLUSIONS["quality_metric_must_disclose_gold_supply"] is True
    assert RETRIEVAL_CONCLUSIONS["experimental_proof_rules_are_not_production"] is True
    payload = principles_payload()
    assert payload["quality_reference"]["true_support"] == 19
    assert freeze_principles_baseline(payload)["id"] == "phase2-experiment-principles-v1"
