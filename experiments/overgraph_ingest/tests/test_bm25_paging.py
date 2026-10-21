from __future__ import annotations

import pytest

from overgraph_ingest.retrieval.bm25_paging import (
    CANCELLED,
    CANDIDATE_BUDGET_EXHAUSTED,
    LEXICAL_MATCHES_EXHAUSTED,
    FrozenCandidateList,
    candidate_list_from_arm,
    consume_all,
    consume_page,
)


def _frozen(n: int = 45, *, strategy: str = "dense_bm25") -> FrozenCandidateList:
    entries = tuple(
        {
            "rank": index + 1,
            "key": f"u{index}",
            "relative_path": f"d{index // 30}.docx",
            "document_id": f"doc{index // 30}",
            "score": 1.0 / (index + 1),
            "branch": {},
            "label": "relevant" if index == 0 else "other",
        }
        for index in range(n)
    )
    return FrozenCandidateList(
        experiment_id="phase2-tantivy-bm25-v1",
        query_id="q",
        query="fråga",
        strategy=strategy,
        index_snapshot_hash="snap",
        strategy_config_hash="cfg",
        entries=entries,
    )


def test_pages_are_twenty_and_prefix_consistent() -> None:
    frozen = _frozen()
    stats, processed, reason = consume_all(frozen, page_size=20)
    assert [row.returned for row in stats] == [20, 20, 5]
    assert len(processed) == 45
    assert reason == CANDIDATE_BUDGET_EXHAUSTED
    assert stats[0].next_position == 20
    assert stats[-1].next_position == 45


def test_resume_does_not_duplicate_processed_units() -> None:
    frozen = _frozen()
    cursor = frozen.cursor(page_size=20)
    first = consume_page(frozen, cursor)
    second = consume_page(frozen, first.cursor)
    first_keys = {entry["key"] for entry in first.entries}
    second_keys = {entry["key"] for entry in second.entries}
    assert not (first_keys & second_keys)
    assert len(first_keys | second_keys) == 40


def test_cursor_rejects_changed_query_snapshot_strategy_or_ranking() -> None:
    frozen = _frozen()
    cursor = frozen.cursor()
    changed = _frozen(45)
    changed = FrozenCandidateList(
        **{**changed.__dict__, "query": "annan fråga"}
    )
    with pytest.raises(ValueError):
        consume_page(changed, cursor)
    changed = FrozenCandidateList(**{**frozen.__dict__, "index_snapshot_hash": "other"})
    with pytest.raises(ValueError):
        consume_page(changed, cursor)
    changed = FrozenCandidateList(**{**frozen.__dict__, "strategy_config_hash": "other"})
    with pytest.raises(ValueError):
        consume_page(changed, cursor)
    changed = FrozenCandidateList(**{**frozen.__dict__, "entries": frozen.entries[:-1]})
    with pytest.raises(ValueError):
        consume_page(changed, cursor)


def test_cancel_and_resume_are_explicit() -> None:
    frozen = _frozen()
    stats, processed, reason = consume_all(frozen, page_size=20, cancel_after_pages=1)
    assert len(stats) == 1
    assert len(processed) == 20
    assert reason == CANCELLED
    cursor = frozen.cursor(page_size=20)
    first = consume_page(frozen, cursor)
    second = consume_page(frozen, first.cursor)
    assert first.returned == 20
    assert second.returned == 20


def test_lexical_end_is_not_absence() -> None:
    frozen = _frozen(3, strategy="bm25")
    stats, processed, reason = consume_all(frozen, page_size=20)
    assert reason == LEXICAL_MATCHES_EXHAUSTED
    assert len(processed) == 3
    assert stats[-1].stop_reason == LEXICAL_MATCHES_EXHAUSTED


def test_late_passage_from_seen_document_is_kept() -> None:
    frozen = _frozen(45)
    cursor = frozen.cursor(page_size=20)
    first = consume_page(frozen, cursor, relevant_paths={"d0.docx"})
    second = consume_page(frozen, first.cursor, relevant_paths={"d0.docx"}, seen_documents={"d0.docx"})
    assert first.new_documents == 1
    assert second.unique_documents == 2
    assert second.new_documents == 1  # d1 starts on page 2; the earlier d0 passage still stays
    assert len(second.entries) == 20
    assert any(entry["relative_path"] == "d0.docx" for entry in second.entries)


def test_candidate_list_from_arm_keeps_branch_and_label() -> None:
    frozen = candidate_list_from_arm(
        experiment_id="e",
        query_id="q",
        query="q",
        strategy="dense_bm25",
        index_snapshot_hash="s",
        strategy_config={"arm": "dense_bm25"},
        hits=[
            {
                "rank": 1,
                "key": "u1",
                "relative_path": "a.docx",
                "document_id": "d",
                "score": 0.5,
                "branch": {"dense": {"rank": 2}},
                "label": "relevant",
            }
        ],
    )
    assert frozen.entries[0]["branch"] == {"dense": {"rank": 2}}
    assert frozen.entries[0]["label"] == "relevant"
