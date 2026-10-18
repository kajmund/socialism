from overgraph_ingest.coverage.leftover_diagnosis import (
    CITATION_LABEL,
    EXCEPTION_PARAPHRASE,
    QUALITY_REFERENCE,
    ROWS,
    summarize,
)
from overgraph_ingest.coverage.leftover_run import (
    freeze_leftover_baseline,
    run_leftover_diagnosis,
)
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_leftover_diagnosis_baseline,
)


def test_quality_reference_stays_nineteen() -> None:
    assert QUALITY_REFERENCE == {
        "true_support": 19,
        "expected_yes": 53,
        "false_approvals": 0,
        "leftover_genuine": 34,
        "source": "phase2-anaphor-list-v1",
    }
    assert len(ROWS) == 34


def test_first_split_and_class_counts() -> None:
    summary = summarize()
    assert summary["examined"] == 20
    assert summary["unexamined"] == 14
    assert summary["documents_per_class"] == {
        "paraphrase": 10,
        "amendment": 2,
        "document_ranking": 5,
        "defined_term": 2,
        "other_unresolved_link": 21,
    }
    assert summary["same_document_may_have_several_classes"] is True
    assert summary["does_not_choose_next_ability"] is True


def test_unlock_if_one_ability_is_ranked_by_effect() -> None:
    summary = summarize()
    ranked = summary["ranked_unlock_if_one_ability"]
    assert ranked[0] == {
        "ability": EXCEPTION_PARAPHRASE,
        "count": 7,
        "documents": [
            "avtal_134.docx",
            "avtal_157.docx",
            "avtal_163.docx",
            "avtal_172.docx",
            "avtal_184.docx",
            "avtal_190.docx",
            "avtal_193.docx",
        ],
    }
    assert ranked[1]["ability"] == CITATION_LABEL
    assert ranked[1]["count"] == 5
    assert summary["unlocks_if_examined_with_current_abilities"] == [
        "avtal_135.docx",
        "avtal_159.docx",
        "avtal_168.docx",
    ]
    assert ROWS["avtal_120.docx"]["decidable_by_one"] is False
    assert ROWS["avtal_137.docx"]["decidable_by_one"] is False
    assert ROWS["avtal_194.docx"]["decidable_by_one"] is False


def test_leftover_baseline() -> None:
    frozen = load_leftover_diagnosis_baseline()
    headline = frozen["headline"]
    assert frozen["applied_to_v3"] is False
    assert frozen["no_new_jev"] is True
    assert frozen["does_not_start_next_ability"] is True
    assert headline["quality_reference"]["true_support"] == 19
    assert headline["summary"]["leftover"] == 34
    assert headline["summary"]["ranked_unlock_if_one_ability"][0]["count"] == 7
    assert RETRIEVAL_CONCLUSIONS["leftover_diagnosis_applied_to_v3"] is False
    assert RETRIEVAL_CONCLUSIONS["previous_quality_reference"] == "19/53"
    payload = run_leftover_diagnosis()
    if payload["live_leftover"] is not None:
        assert set(payload["live_leftover"]) == set(ROWS)
        assert payload["rows"]["avtal_157.docx"]["observed_why"] == (
            "cited_clause_does_not_support_relation"
        )
        assert payload["rows"]["avtal_135.docx"]["observed_why"] is None
    assert freeze_leftover_baseline(payload)["does_not_start_next_ability"] is True
