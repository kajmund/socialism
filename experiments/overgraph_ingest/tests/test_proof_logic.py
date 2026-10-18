from overgraph_ingest.coverage.logic_run import (
    AVTAL_60_UNIT,
    LOGIC_BASELINE_ID,
    freeze_proof_logic_baseline,
    run_proof_logic,
)
from overgraph_ingest.coverage.proof_logic import (
    CLAIM_FORM,
    INVERTED_FORM,
    UNDECIDED_FORM,
    judge_invariants,
    read_logic,
    split_predications,
)
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_proof_logic_baseline,
)


def test_direct_carveout_is_the_claim_form() -> None:
    logic = read_logic("Begränsningen gäller inte vid sekretessbrott.")
    assert logic.form == CLAIM_FORM
    assert logic.relation_validated is True


def test_inverted_exception_is_not_the_claim() -> None:
    judged = judge_invariants(
        "Begränsningen gäller inte, utom vid sekretessbrott.",
        jev_yes=True,
    )
    assert judged["form"] == INVERTED_FORM
    assert judged["span_validated"] is True
    assert judged["quote_and_yes"] is True
    assert judged["relation_validated"] is False


def test_avtal_60_is_direct_once_split_into_predications() -> None:
    parts = split_predications(AVTAL_60_UNIT)
    assert len(parts) == 2
    assert read_logic(parts[0]).form == UNDECIDED_FORM
    assert read_logic(parts[1]).form == CLAIM_FORM
    judged = judge_invariants(AVTAL_60_UNIT)
    assert judged["form"] == CLAIM_FORM
    assert judged["relation_validated"] is True


def test_paraphrase_stays_undecided() -> None:
    logic = read_logic("Brott mot sekretess undantas från ansvarsbegränsningen.")
    assert logic.form == UNDECIDED_FORM
    assert logic.relation_validated is False


def test_proof_logic_run_holds() -> None:
    payload = run_proof_logic()
    assert payload["does_not_change_evidence_contract"] is True
    assert payload["not_a_gate"] is True
    assert payload["not_a_parser"] is True
    assert payload["no_new_jev"] is True
    assert payload["all_positives_claim_form"] is True
    assert payload["pairs_match"] is True
    assert payload["stacked_all_inverted"] is True
    assert payload["avtal_60_claim_form"] is True
    assert payload["avtal_60_not_inverted"] is True
    assert payload["avtal_12_undecided"] is True
    assert payload["heading_not_a_relation"] is True
    assert payload["quote_and_yes_is_not_proof"] is True
    assert payload["logic_synonym_claim_count"] < 10
    assert payload["jev_synonym_recall"] == 1.0


def test_proof_logic_baseline_is_frozen() -> None:
    frozen = load_proof_logic_baseline()
    assert frozen["id"] == LOGIC_BASELINE_ID
    assert frozen["not_a_gate"] is True
    assert frozen["not_a_parser"] is True
    assert frozen["does_not_change_evidence_contract"] is True
    headline = frozen["headline"]
    assert headline["all_positives_claim_form"] is True
    assert headline["avtal_60_claim_form"] is True
    assert headline["quote_and_yes_is_not_proof"] is True
    assert RETRIEVAL_CONCLUSIONS["span_validation_is_not_relation_validation"] is True
    assert RETRIEVAL_CONCLUSIONS["quote_and_yes_is_not_proof"] is True
    assert RETRIEVAL_CONCLUSIONS["proof_logic_applied_to_v3"] is False
    assert RETRIEVAL_CONCLUSIONS["next_open_cost"] == "evidence_found_must_answer_dependencies"
    assert freeze_proof_logic_baseline(run_proof_logic())["headline"]["quote_and_yes_is_not_proof"] is True
