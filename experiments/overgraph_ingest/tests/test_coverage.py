from overgraph_ingest.coverage.evaluate import coverage_curve, evaluate_selection
from overgraph_ingest.coverage.select import document_scoped, global_top_k, progressive_unexamined
from overgraph_ingest.coverage.status import (
    HAS_EVIDENCE,
    NEEDS_ANALYSIS,
    NOT_FOUND,
    UNEXAMINED,
    VERIFIED_ABSENT,
    assign_statuses,
)
from overgraph_ingest.retrieval.gold import CoverageGroup, GoldSpan, RetrievalGold
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.search import SearchHit


def _hit(key: str, path: str, rank: int, text: str) -> SearchHit:
    return SearchHit(rank, key, 1.0 / rank, rank, f"d-{path}", path, text)


def _unit(key: str, path: str, text: str, sequence: int) -> StoredUnit:
    return StoredUnit(sequence, key, f"d-{path}", path, text, None, None, "", sequence)


def _gold() -> RetrievalGold:
    return RetrievalGold(
        id="t",
        query="q",
        relevant_units=[
            GoldSpan("a.docx", "rätt klausul"),
            GoldSpan("b.docx", "andra rätt"),
        ],
        hard_negatives=[],
        document_gold=("a.docx", "b.docx"),
        coverage_groups=[
            CoverageGroup("a.docx", ("rätt klausul", "syskon")),
        ],
    )


def test_top_k_miss_is_unexamined_not_verified_absent() -> None:
    gold = _gold()
    units = [
        _unit("a1", "a.docx", "rätt klausul", 1),
        _unit("a2", "a.docx", "syskon", 2),
        _unit("b1", "b.docx", "andra rätt", 1),
        _unit("c1", "c.docx", "annat", 1),
    ]
    selected = [_hit("c1", "c.docx", 1, "annat")]
    statuses = assign_statuses(selected, units, gold, {"a1", "b1"})
    assert statuses["a.docx"].status == UNEXAMINED
    assert statuses["b.docx"].status == UNEXAMINED
    assert statuses["c.docx"].status == VERIFIED_ABSENT
    assert statuses["a.docx"].verified_absent is False


def test_partial_look_is_not_found_not_verified_absent() -> None:
    gold = _gold()
    units = [
        _unit("a1", "a.docx", "rätt klausul", 1),
        _unit("a2", "a.docx", "oviktigt", 2),
    ]
    selected = [_hit("a2", "a.docx", 1, "oviktigt")]
    statuses = assign_statuses(selected, units, gold, {"a1"})
    assert statuses["a.docx"].status == NOT_FOUND
    assert statuses["a.docx"].verified_absent is False


def test_incomplete_coverage_group_needs_analysis() -> None:
    gold = _gold()
    units = [
        _unit("a1", "a.docx", "rätt klausul", 1),
        _unit("a2", "a.docx", "syskon", 2),
    ]
    selected = [_hit("a1", "a.docx", 1, "rätt klausul")]
    statuses = assign_statuses(selected, units, gold, {"a1"})
    assert statuses["a.docx"].status == NEEDS_ANALYSIS
    assert statuses["a.docx"].has_evidence is True
    assert statuses["a.docx"].coverage_complete is False


def test_progressive_only_adds_unexamined_documents() -> None:
    ranked = [
        _hit("c1", "c.docx", 1, "annat"),
        _hit("a2", "a.docx", 2, "oviktigt"),
        _hit("a1", "a.docx", 3, "rätt klausul"),
        _hit("b1", "b.docx", 4, "andra rätt"),
    ]
    first, extra = progressive_unexamined(ranked, global_k=2, per_document=1)
    assert [hit.key for hit in first] == ["c1", "a2"]
    assert [hit.key for hit in extra] == ["b1"]
    assert all(hit.relative_path == "b.docx" for hit in extra)


def test_document_scoped_round_robin_keeps_a_budget_per_document() -> None:
    ranked = [
        _hit("a1", "a.docx", 1, "rätt klausul"),
        _hit("b1", "b.docx", 2, "andra rätt"),
        _hit("a2", "a.docx", 3, "syskon"),
        _hit("b2", "b.docx", 4, "mer"),
    ]
    scoped = document_scoped(ranked, 1)
    assert [hit.key for hit in scoped] == ["a1", "b1"]
    assert global_top_k(ranked, 2)[0].key == "a1"


def test_curve_counts_units_needed_for_full_document_recall() -> None:
    gold = _gold()
    selected = [
        _hit("noise", "c.docx", 1, "annat"),
        _hit("a1", "a.docx", 2, "rätt klausul"),
        _hit("b1", "b.docx", 3, "andra rätt"),
    ]
    curve = coverage_curve(selected, gold, {"a1", "b1"})
    assert curve["units_to_document_recall"]["0.8"] == 3
    assert curve["units_to_document_recall"]["1.0"] == 3
    metrics = evaluate_selection(
        name="global_top_k",
        selected=selected[:1],
        units=[
            _unit("a1", "a.docx", "rätt klausul", 1),
            _unit("b1", "b.docx", "andra rätt", 1),
            _unit("noise", "c.docx", "annat", 1),
        ],
        gold=gold,
        relevant_keys={"a1", "b1"},
    )
    assert metrics["document_recall"] == 0.0
    assert metrics["unexamined_relevant_documents"] == ["a.docx", "b.docx"]
    assert metrics["false_negative_documents"] == []
    assert HAS_EVIDENCE not in metrics["status_counts"]
