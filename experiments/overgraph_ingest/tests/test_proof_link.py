from overgraph_ingest.coverage.proof_link import (
    LINKED_RELATION,
    NEEDS_NAVIGATION,
    NOT_GROUNDED,
    evaluate_passage,
    evaluate_passages,
    resolve_reference,
)
from overgraph_ingest.coverage.proof_link_run import (
    FALSE_COMPLETE_PAIRS,
    KEYWORD_PAIR,
    freeze_proof_link_baseline,
    run_proof_link,
)
from overgraph_ingest.coverage.proof_relation import relation_status
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_proof_link_baseline,
)


def test_one_sentence_can_ground_the_link() -> None:
    judged = evaluate_passage(
        "Begränsningarna gäller inte vid uppsåt, grov vårdslöshet eller brott mot sekretess."
    )
    assert judged["status"] == LINKED_RELATION
    assert "sekretess" in judged["linked_span"].lower()


def test_keyword_cooccurrence_across_units_is_not_a_relation() -> None:
    cap = "Begränsningarna gäller inte vid uppsåt eller grov vårdslöshet."
    heading = "8. Sekretess"
    assert relation_status(texts=[cap, heading], required_parts=()) == "complete_in_unit"
    judged = evaluate_passages([cap, heading])
    assert judged["status"] == NOT_GROUNDED
    assert judged["cooccurrence_only"] is True
    assert judged["grounding_passage"] is None


def test_unresolved_punkt_4_is_navigation_not_proof() -> None:
    source = "Begränsningarna gäller inte vid uppsåt, grov vårdslöshet eller brott mot punkt 4."
    assert evaluate_passage(source)["status"] == NEEDS_NAVIGATION
    dismissed = resolve_reference(source, "4. Informationssäkerhet och dataskydd")
    assert dismissed["referent_matches"] is True
    assert dismissed["status"] == NOT_GROUNDED
    stolen = resolve_reference(source, "8. Sekretess")
    assert stolen["referent_matches"] is False
    assert stolen["status"] == NOT_GROUNDED


def test_false_complete_pairs_stay_ungrounded() -> None:
    for _path, source, target in FALSE_COMPLETE_PAIRS:
        judged = evaluate_passages([source, target])
        assert judged["status"] != LINKED_RELATION
        resolved = resolve_reference(source, target)
        assert resolved["status"] != LINKED_RELATION


def test_proof_link_accepts_the_seven_and_rejects_controls() -> None:
    payload = run_proof_link()
    assert payload["coverage_v3_unchanged"] is True
    assert payload["proof_link_applied_to_v3"] is False
    assert payload["rule_b_rejected"] is True
    assert payload["positives_expected"] == 7
    assert payload["linked_positives"] == [
        "Avtal_05_Konsultavtal.docx",
        "Avtal_30_Ramavtal_tjanster.docx",
        "Avtal_36_Underleverantorsavtal.docx",
        "Avtal_46_SaaS_avtal.docx",
        "Avtal_48_Mjukvaruutvecklingsavtal.docx",
        "Avtal_59_Agilt_IT_konsultavtal.docx",
        "Avtal_60_Pilotavtal_PoC.docx",
    ]
    assert payload["false_linked_count"] == 0
    assert payload["cooccurrence_regression"]["texts"] == list(KEYWORD_PAIR)
    assert payload["cooccurrence_regression"]["status"] == NOT_GROUNDED
    assert payload["avtal_49_resolved"]["status"] == NOT_GROUNDED
    assert payload["avtal_46_split"]["status"] == LINKED_RELATION
    assert payload["ready_for_coverage_run"] is True
    assert RETRIEVAL_CONCLUSIONS["cooccurrence_is_not_a_relation"] is True
    assert RETRIEVAL_CONCLUSIONS["proof_link_live_zero_false"] is True
    assert RETRIEVAL_CONCLUSIONS["next_open_cost"] == "evidence_found_must_answer_dependencies"


def test_proof_link_baseline_is_frozen() -> None:
    frozen = load_proof_link_baseline()
    assert frozen["id"] == "phase2-proof-link-v1"
    assert frozen["ready_for_coverage_run"] is True
    assert frozen["headline"]["false_linked_count"] == 0
    assert frozen["headline"]["positives_expected"] == 7
    assert freeze_proof_link_baseline(run_proof_link())["ready_for_coverage_run"] is True
