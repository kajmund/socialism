"""Deterministic SSR ranking for Tabular Review — reuses cosine_similarity."""

from app.services.knowledge.units import TextUnit, hash_text
from app.services.ssr.similarity import cosine_similarity
from app.services.tabular_review.cache import ScoreCacheIdentity, score_cache_key
from app.services.tabular_review.locators import source_locator
from app.services.tabular_review.ranking import (
    ColumnScoreOptions,
    decide_cell,
    rank_candidates,
    score_document_column,
)
from app.services.tabular_review.types import RankedCandidate


def _unit(unit_id: str, text: str, *, page: int | None = 2, locator: str | None = "§3") -> TextUnit:
    return TextUnit(
        id=unit_id,
        document_version_id="ver-1",
        document_id="doc-1",
        section_id="sec-1",
        ordinal=0,
        text=text,
        content_hash=hash_text(text),
        locator=locator,
        page_start=page,
        page_end=page,
    )


def _candidate(unit_id: str, score: float) -> RankedCandidate:
    unit = _unit(unit_id, f"text {unit_id}")
    return RankedCandidate(
        text_unit_id=unit_id,
        exact_text=unit.text,
        similarity=score,
        polarity="positive",
        source=source_locator(unit),
    )


def test_ranking_is_deterministic_and_uses_cosine():
    left = [1.0, 0.0, 0.0]
    right = [0.0, 1.0, 0.0]
    assert cosine_similarity(left, left) == 1.0
    assert cosine_similarity(left, right) == 0.0
    ranked = rank_candidates([_candidate("b", 0.4), _candidate("a", 0.4), _candidate("c", 0.9)])
    assert [item.text_unit_id for item in ranked] == ["c", "a", "b"]


def test_below_threshold_is_no_hit_not_missing_clause():
    decision = decide_cell(
        [_candidate("a", 0.2)],
        threshold=0.35,
        polarity="positive",
        allow_abstain=False,
        abstain_margin=None,
    )
    assert decision.status == "no_hit"
    assert decision.selected is None


def test_close_scores_can_abstain_without_negative_evidence():
    decision = decide_cell(
        [_candidate("a", 0.81), _candidate("b", 0.80)],
        threshold=0.35,
        polarity="positive",
        allow_abstain=True,
        abstain_margin=0.05,
    )
    assert decision.status == "unknown"
    assert decision.selected is None


def test_negative_polarity_hit_is_not_inferred_from_absence():
    miss = decide_cell(
        [_candidate("a", 0.1)],
        threshold=0.35,
        polarity="negative",
        allow_abstain=False,
        abstain_margin=None,
    )
    assert miss.status == "no_hit"
    hit = decide_cell(
        [_candidate("a", 0.9)],
        threshold=0.35,
        polarity="negative",
        allow_abstain=False,
        abstain_margin=None,
    )
    assert hit.status == "negative_hit"
    assert hit.selected is not None


def test_score_document_column_shows_verbatim_clause():
    units = [
        _unit("keep", "Avtalet kan sägas upp med tre månaders uppsägningstid."),
        _unit("other", "Parterna ska samråda om leverans."),
    ]
    embeddings = {
        "keep": [1.0, 0.0],
        "other": [0.0, 1.0],
    }
    decision = score_document_column(
        units,
        embeddings,
        [[1.0, 0.0]],
        ColumnScoreOptions(polarity="positive", threshold=0.35),
    )
    assert decision.status == "hit"
    assert decision.selected is not None
    assert decision.selected.exact_text.startswith("Avtalet kan sägas upp")
    assert decision.selected.similarity == 1.0
    assert decision.selected.source.page_start == 2
    assert decision.selected.source.locator == "§3"


def test_locator_does_not_fabricate_page_or_rects():
    unit = _unit("plain", "bara text", page=None, locator=None)
    source = source_locator(unit)
    assert source.page_start is None
    assert source.rects == ()
    assert source.locator is None


def test_cache_key_includes_unit_set_version_and_model():
    first = score_cache_key(
        ScoreCacheIdentity(
            text_unit_id="u1",
            content_hash="abc",
            anchor_set_id=3,
            anchor_set_version="v1",
            pool_revision=0,
            embedding_model="text-embedding-3-large",
            label="uppsagning",
            polarity="positive",
        )
    )
    second = score_cache_key(
        ScoreCacheIdentity(
            text_unit_id="u1",
            content_hash="abc",
            anchor_set_id=3,
            anchor_set_version="v2",
            pool_revision=0,
            embedding_model="text-embedding-3-large",
            label="uppsagning",
            polarity="positive",
        )
    )
    assert first != second
    assert len(first) == 64
