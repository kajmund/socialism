from overgraph_ingest.coverage.leftover_29 import (
    DISCOVERY,
    REMOVED_BY_CITATION_LABELS,
    ROWS,
    SEMANTIC,
    STRUCTURE,
    freeze_leftover_29,
    run_leftover_29,
    summarize,
)
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_leftover_29_baseline,
)


def test_split_is_fifteen_and_fourteen() -> None:
    summary = summarize()
    assert summary["leftover"] == 29
    assert summary["examined"] == 15
    assert summary["unexamined"] == 14
    assert summary["tracks"][SEMANTIC]["count"] == 10
    assert summary["tracks"][DISCOVERY]["count"] == 14
    assert summary["tracks"][STRUCTURE]["count"] == 4
    assert summary["tracks"]["needs_two_abilities"]["documents"] == ["avtal_137.docx"]
    assert summary["unlocks_if_examined_with_current_abilities"] == [
        "avtal_135.docx",
        "avtal_159.docx",
        "avtal_168.docx",
    ]
    assert set(REMOVED_BY_CITATION_LABELS).isdisjoint(ROWS)
    assert ROWS["avtal_120.docx"]["blocking_ability"] == "higher_cap"
    assert ROWS["avtal_194.docx"]["blocking_ability"] == "higher_cap"
    assert summary["does_not_choose_next_ability"] is True
    assert summary["fork_is_semantics_versus_discovery"] is True


def test_leftover_29_baseline() -> None:
    frozen = load_leftover_29_baseline()
    assert frozen["applied_to_v3"] is False
    assert frozen["does_not_start_next_ability"] is True
    assert frozen["headline"]["quality_reference"]["true_support"] == 24
    assert frozen["headline"]["summary"]["examined"] == 15
    assert RETRIEVAL_CONCLUSIONS["latest_quality_reference"] == "24/53"
    assert RETRIEVAL_CONCLUSIONS["leftover_29_does_not_start_next_ability"] is True
    payload = run_leftover_29()
    if payload["live_leftover"] is not None:
        assert set(payload["live_leftover"]) == set(ROWS)
        assert payload["rows"]["avtal_120.docx"]["observed_why"] == (
            "cited_clause_does_not_support_relation"
        )
    assert freeze_leftover_29(payload)["does_not_add_another_parser_rule"] is True
