from overgraph_ingest.retrieval.gold import GoldSpan, span_matches
from overgraph_ingest.retrieval.gold_map import (
    AMBIGUOUS,
    SPACE_COLLAPSED,
    UNIQUE,
    locate_contains,
    map_span,
)
from overgraph_ingest.retrieval.gold_map_run import (
    AVTAL_160_GOLD,
    AVTAL_160_SOURCE,
    EXAMINED_SUPPORT,
    EXHAUSTIVE_ABSENCE,
    freeze_gold_map_baseline,
    run_gold_map,
)
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_gold_map_baseline,
)


def test_default_contains_still_requires_exact_spaces() -> None:
    span = GoldSpan(relative_path="avtal_160.docx", contains=AVTAL_160_GOLD)
    assert span_matches(AVTAL_160_SOURCE, span) is False
    assert AVTAL_160_GOLD in AVTAL_160_GOLD


def test_v2_grounds_original_two_spaces_and_keeps_meaning() -> None:
    hits = locate_contains(AVTAL_160_SOURCE, AVTAL_160_GOLD)
    assert len(hits) == 1
    start, end, quote, how = hits[0]
    assert how == SPACE_COLLAPSED
    assert quote == AVTAL_160_SOURCE
    assert quote[start:end] == quote
    assert "☒  " in quote
    assert "☒" in quote
    assert "gäller inte" in quote
    assert AVTAL_160_SOURCE[start:end] == quote


def test_ambiguous_hits_are_reported() -> None:
    source = "A ☒  B. extra A ☒  B."
    needle = "A ☒ B."
    hits = locate_contains(source, needle)
    assert len(hits) == 2
    unit = StoredUnit(1, "k", "d", "doc.docx", source, None, None)
    mapped = map_span([unit], GoldSpan(relative_path="doc.docx", contains=needle))
    assert mapped["status"] == AMBIGUOUS
    assert mapped["v1_exact"] is False


def test_newlines_are_not_collapsed() -> None:
    source = "gäller inte\nvid sekretess"
    needle = "gäller inte vid sekretess"
    assert locate_contains(source, needle) == []


def test_gold_map_run_and_baseline() -> None:
    payload = run_gold_map()
    assert payload["does_not_change_default_contains"] is True
    assert payload["does_not_rewrite_history"] is True
    assert payload["avtal_160"]["v1_exact"] is False
    assert payload["avtal_160"]["v2_status"] == UNIQUE
    assert payload["avtal_160"]["preserves_two_spaces_after_ballot"] is True
    assert payload["avtal_160"]["is_ranking_miss"] is False
    assert payload["answer_contract"]["examined_support"] == EXAMINED_SUPPORT
    assert payload["answer_contract"]["exhaustive_absence"] == EXHAUSTIVE_ABSENCE
    assert payload["answer_contract"]["examined_support_is_not_exhaustive_absence"] is True
    assert payload["next_completion_replaces_yes_plus_hop"] is True
    assert payload["failure_kinds_must_not_share_a_fix"] == [
        "wrong_decision_contract",
        "lacking_semantic_understanding",
        "gold_mapping_miss",
    ]
    frozen = load_gold_map_baseline()
    assert frozen["does_not_rewrite_history"] is True
    assert frozen["headline"]["avtal_160"]["v2_status"] == UNIQUE
    live = frozen["headline"]["avtal_160_in_graph"]
    assert live["status"] == UNIQUE
    assert live["v1_exact"] is False
    assert "☒  " in live["hits"][0]["exact_quote"]
    assert frozen["headline"]["rematch_counts"]["unique"] == 53
    assert frozen["headline"]["rematch_counts"]["v1_exact"] == 52
    assert RETRIEVAL_CONCLUSIONS["examined_support_is_not_exhaustive_absence"] is True
    assert RETRIEVAL_CONCLUSIONS["gold_map_v2_does_not_rewrite_history"] is True
    assert RETRIEVAL_CONCLUSIONS["next_completion_replaces_yes_plus_hop"] is True
    assert RETRIEVAL_CONCLUSIONS["failure_kinds_must_not_share_a_fix"] == (
        "wrong_decision_contract",
        "lacking_semantic_understanding",
        "gold_mapping_miss",
    )
    assert freeze_gold_map_baseline(payload)["headline"]["next_completion_replaces_yes_plus_hop"] is True
