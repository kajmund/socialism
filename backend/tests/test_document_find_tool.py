"""Unit tests for find_documents orchestration and presentation slicing."""

from app.services.document_find.tool import (
    PRESENTATION_CAP,
    needs_embedding,
    normalize_find_mode,
    presentation_slice,
    suggested_title,
)
from app.services.document_find.types import FindResult, OpCounters


def test_pure_category_query_skips_embedding():
    assert needs_embedding("Visa alla hyresavtal.", mode="replace", has_current_set=False) is False


def test_synonym_category_queries_skip_embedding():
    assert needs_embedding("andrahandsuthyrning", mode="replace", has_current_set=False) is False
    assert needs_embedding("lägenhetsarrende", mode="replace", has_current_set=False) is False
    assert needs_embedding("NDA", mode="replace", has_current_set=False) is False


def test_synonym_with_content_still_needs_embedding():
    assert needs_embedding(
        "arrendeavtal för åkermark",
        mode="replace",
        has_current_set=False,
    ) is True


def test_content_filter_within_set_needs_embedding():
    assert needs_embedding(
        "Visa bara dem med automatisk förlängning",
        mode="within",
        has_current_set=True,
    ) is True


def test_presentation_slice_keeps_full_list_elsewhere():
    ids = [f"s{i}" for i in range(PRESENTATION_CAP + 10)]
    shown, truncated = presentation_slice(ids)
    assert truncated is True
    assert len(shown) == PRESENTATION_CAP
    assert len(ids) == PRESENTATION_CAP + 10


def test_suggested_title_uses_type_label():
    result = FindResult(
        document_ids=("a",), strategy="category", completeness="complete", counters=OpCounters(),
    )
    assert suggested_title("Visa alla hyresavtal", result) == "Hyresavtal"


def test_normalize_find_mode_keeps_content_follow_ups_in_active_set():
    assert normalize_find_mode(
        "replace",
        has_current_set=True,
        query="automatisk förlängning",
    ) == "filter"
    assert normalize_find_mode(
        "filter",
        has_current_set=True,
        query="automatisk förlängning",
    ) == "filter"
    assert normalize_find_mode(
        "replace",
        has_current_set=True,
        query="hyresavtal",
    ) == "replace"
