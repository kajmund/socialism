from collections import Counter

from overgraph_ingest.coverage.proof_link import LINKED_RELATION, evaluate_passage
from overgraph_ingest.coverage.proof_morph import (
    CASES,
    EVEN_CASE,
    GROUPS,
    INTE_CASE,
    judge_case,
    run_proof_morph,
)
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_proof_morph_baseline,
)


def test_morph_suite_has_forty_controlled_cases() -> None:
    assert len(CASES) == 40
    assert Counter(case["group"] for case in CASES) == {name: 10 for name in GROUPS}


def test_gäller_även_is_not_gäller_inte() -> None:
    even = evaluate_passage(
        "Ansvarsbegränsningen gäller även vid brott mot sekretessförpliktelserna."
    )
    inte = evaluate_passage("Ansvarsbegränsningen gäller inte vid sekretessbrott.")
    assert even["status"] != inte["status"]
    assert inte["status"] == LINKED_RELATION
    assert even["status"] != LINKED_RELATION


def test_morph_run_documents_formulation_bound_misses() -> None:
    payload = run_proof_morph()
    assert payload["case_count"] == 40
    assert payload["detector_unchanged"] is True
    assert payload["not_an_independent_blind_test"] is True
    assert payload["passed"] == 30
    assert payload["synonym_recall"] == 0.3
    assert payload["false_complete_count"] == 2
    assert "negation_split_same_unit" in payload["false_complete"]
    assert "negation_gäller_inte_utom_sekretess" in payload["false_complete"]
    assert payload["even_versus_inte"]["distinguishes"] is True
    assert judge_case(next(case for case in CASES if case["id"] == EVEN_CASE))["pass"]
    assert judge_case(next(case for case in CASES if case["id"] == INTE_CASE))["pass"]


def test_morph_baseline_is_frozen_and_not_blind() -> None:
    frozen = load_proof_morph_baseline()
    assert frozen["id"] == "phase2-proof-morph-v1"
    assert frozen["not_an_independent_blind_test"] is True
    assert frozen["detector_unchanged"] is True
    assert frozen["headline"]["passed"] == 30
    assert frozen["headline"]["false_complete_count"] == 2
    assert frozen["headline"]["synonym_recall"] == 0.3
    assert RETRIEVAL_CONCLUSIONS["link_detector_is_formulation_bound"] is True
    assert RETRIEVAL_CONCLUSIONS["next_open_cost"] == "evidence_found_must_answer_dependencies"
