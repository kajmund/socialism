from overgraph_ingest.coverage.proposed import (
    MISSING_SPAN,
    OTHER_RELATION,
    PARAPHRASE,
    PROPOSED_ROWS,
    classify_proposed,
)
from overgraph_ingest.coverage.proposed_run import (
    PROPOSED_BASELINE_ID,
    freeze_proof_proposed_baseline,
    run_proof_proposed,
)
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_proof_proposed_baseline,
)


def test_seventeen_proposed_are_three_problems() -> None:
    assert len(PROPOSED_ROWS) == 17
    payload = run_proof_proposed()
    assert payload["no_new_jev"] is True
    assert payload["no_looser_verified_rule"] is True
    assert payload["proposed_count"] == 17
    assert payload["more_information_can_verify_count"] == 0
    assert payload["semantic_paraphrase_count"] == 7
    assert payload["other_relation_count"] == 7
    assert payload["missing_relation_in_span_count"] == 3
    assert payload["incomplete_reference_count"] == 0
    assert payload["ambiguous_count"] == 0
    assert all(row["should_stay_undecided"] for row in payload["rows"])
    assert all(not row["supports_claim"] for row in payload["rows"])


def test_applies_is_another_relation_not_missing_info() -> None:
    row = classify_proposed(
        next(item for item in PROPOSED_ROWS if item["id"] == "negation_gäller_även")
    )
    assert row["cause"] == OTHER_RELATION
    assert row["more_information_can_verify"] is False


def test_resolved_pointer_is_not_a_carveout_span() -> None:
    row = classify_proposed(
        next(item for item in PROPOSED_ROWS if item["id"] == "reference_punkt_8_secrecy")
    )
    assert row["cause"] == MISSING_SPAN
    assert row["phase"] == "after"
    assert row["more_information_can_verify"] is False


def test_paraphrase_needs_semantics_not_hops() -> None:
    row = classify_proposed(
        next(item for item in PROPOSED_ROWS if item["id"] == "synonym_undantas")
    )
    assert row["cause"] == PARAPHRASE
    assert row["more_information_can_verify"] is False


def test_proof_proposed_baseline_is_frozen() -> None:
    frozen = load_proof_proposed_baseline()
    assert frozen["id"] == PROPOSED_BASELINE_ID
    assert frozen["no_new_jev"] is True
    assert frozen["no_looser_verified_rule"] is True
    headline = frozen["headline"]
    assert headline["proposed_count"] == 17
    assert headline["more_information_can_verify_count"] == 0
    assert headline["semantic_paraphrase_count"] == 7
    assert headline["other_relation_count"] == 7
    assert headline["missing_relation_in_span_count"] == 3
    assert RETRIEVAL_CONCLUSIONS["do_not_loosen_verified_for_proposed"] is True
    assert RETRIEVAL_CONCLUSIONS["more_hops_do_not_verify_proposed"] is True
    assert RETRIEVAL_CONCLUSIONS["next_open_cost"] == "evidence_found_must_answer_dependencies"
    assert freeze_proof_proposed_baseline(run_proof_proposed())["headline"][
        "more_information_can_verify_count"
    ] == 0