from overgraph_ingest.coverage.proof_requirements import (
    AMENDMENT_MUST_NOT_BE_IGNORED,
    EXISTING_LINK_WITHOUT_OBLIGATORY_HOP,
    MISSING_LINK_NEEDS_RIGHT_MATERIAL,
    PREVAILING_TERMS,
    REJECTED_FIXES,
    accounting,
    case_by_id,
    existing_link_in_yes_unit,
    freeze_proof_requirements_baseline,
    hop_resolves_cited_material,
    run_proof_requirements,
)
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_proof_requirements_baseline,
)


def test_accounting_keeps_uncertain_separate() -> None:
    counts = accounting()
    assert counts["gold_yes"] == 39
    assert counts["gold_no"] == 2
    assert counts["gold_uncertain"] == 3
    assert counts["total_evidence_found"] == 44
    assert counts["uncertain_is_not_false_complete"] is True
    assert counts["gold_yes_is_not_verified_proof"] is True


def test_amendment_cases_are_not_satisfied_by_current_completion() -> None:
    payload = run_proof_requirements()
    row = payload["requirements"][AMENDMENT_MUST_NOT_BE_IGNORED]
    assert row["documents"] == ["avtal_119.docx", "avtal_200.docx"]
    assert row["local_yes_may_be_reasonable"] is True
    assert row["document_decision_is_wrong"] is True
    assert row["current_completion_satisfies"] is False
    first = case_by_id("avtal_119.docx")
    assert "gäller inte heller vid brott mot punkt 1" in first["jev_yes_text"]
    assert "uppsåt" in first["hop_text"]


def test_missing_link_is_not_resolved_by_the_observed_hop() -> None:
    missing = case_by_id("avtal_103.docx")
    assert "avsnitt 4" in missing["jev_yes_text"]
    assert hop_resolves_cited_material(missing) is False
    assert "2 500 000" in missing["hop_text"]


def test_existing_links_do_not_need_the_observed_hop() -> None:
    for path in ("avtal_106.docx", "avtal_113.docx", "avtal_140.docx"):
        row = case_by_id(path)
        assert existing_link_in_yes_unit(row) is True
        assert row["why_evidence_found"] == "jev_yes_after_hop"


def test_rejected_fixes_are_not_the_solution() -> None:
    payload = run_proof_requirements()
    assert payload["answer_contract"] == PREVAILING_TERMS
    assert payload["applied_to_v3"] is False
    assert payload["no_new_proof_engine"] is True
    assert "no_always_wins_over_yes" in payload["rejected_fixes"]
    assert "any_successful_hop_resolves_reference" in REJECTED_FIXES
    assert payload["unmapped_gold_quote"]["relative_path"] == "avtal_160.docx"
    assert payload["unmapped_gold_quote"]["is_ranking_miss"] is False


def test_proof_requirements_baseline_is_frozen() -> None:
    frozen = load_proof_requirements_baseline()
    assert frozen["applied_to_v3"] is False
    assert frozen["headline"]["answer_contract"] == PREVAILING_TERMS
    assert frozen["headline"]["requirements_current_completion_satisfies"] == {
        AMENDMENT_MUST_NOT_BE_IGNORED: False,
        MISSING_LINK_NEEDS_RIGHT_MATERIAL: False,
        EXISTING_LINK_WITHOUT_OBLIGATORY_HOP: False,
    }
    assert RETRIEVAL_CONCLUSIONS["gold_tests_prevailing_terms"] is True
    assert RETRIEVAL_CONCLUSIONS["proof_requirements_applied_to_v3"] is False
    assert RETRIEVAL_CONCLUSIONS["next_open_cost"] == "evidence_found_must_answer_dependencies"
    assert freeze_proof_requirements_baseline(run_proof_requirements())["no_new_proof_engine"] is True
