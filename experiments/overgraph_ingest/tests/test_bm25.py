from __future__ import annotations

from pathlib import Path

import pytest

from overgraph_ingest.retrieval.bm25 import (
    SV_PLAIN,
    SV_STEM,
    build_index,
    build_profile,
    open_index,
    verify_index,
)
from overgraph_ingest.retrieval.index import StoredUnit


def _unit(
    key: str,
    text: str,
    *,
    document_id: str = "doc",
    relative_path: str = "Avtal_1.docx",
    collection_id: str = "contracts",
    content_hash: str | None = None,
) -> StoredUnit:
    return StoredUnit(
        node_id=abs(hash(key)) % 100000,
        key=key,
        document_id=document_id,
        relative_path=relative_path,
        text=text,
        dense=None,
        sparse=None,
        content_hash=content_hash or key,
        collection_id=collection_id,
    )


def test_swedish_analyzer_preserves_negations_and_conditionals() -> None:
    profile = build_profile(SV_STEM)
    analyzer = profile.analyzer()
    assert analyzer.analyze("Förlängs automatiskt") == ["förläng", "automatisk"]
    for word in ("inte", "utan", "endast", "om"):
        assert analyzer.analyze(word), word
    assert analyzer.analyze("inte") != analyzer.analyze("om")


def test_plain_control_does_not_stem() -> None:
    stem = build_profile(SV_STEM).analyzer()
    plain = build_profile(SV_PLAIN).analyzer()
    assert stem.analyze("förlängs") == ["förläng"]
    assert plain.analyze("förlängs") == ["förlängs"]


def test_query_is_or_over_unique_terms_and_treats_syntax_as_text(tmp_path: Path) -> None:
    units = [
        _unit("a", "Sekretess gäller enligt avtalet.", document_id="d1"),
        _unit("b", "Uppsägningstiden är tre månader.", document_id="d2"),
        _unit("c", "Ingen av termerna finns här.", document_id="d3"),
    ]
    index = build_index(units, profile=build_profile(SV_STEM), index_dir=tmp_path / "index")
    result = index.search('sekretess OR "uppsägningstid"', limit=10)
    assert {hit.key for hit in result.hits} == {"a", "b"}
    assert result.tie.empty_query is False


def test_empty_query_returns_empty_list_not_all(tmp_path: Path) -> None:
    units = [_unit("a", "Sekretess gäller.", document_id="d1")]
    index = build_index(units, profile=build_profile(SV_STEM), index_dir=tmp_path / "index")
    result = index.search("!!!", limit=10)
    assert result.hits == []
    assert result.tie.empty_query is True


def test_document_filter_is_applied_before_top_k(tmp_path: Path) -> None:
    units = [
        *[_unit(f"a{i}", "Sekretess gäller i detta avtal.", document_id="d1") for i in range(5)],
        _unit("b", "Sekretess gäller också här.", document_id="d2"),
    ]
    index = build_index(units, profile=build_profile(SV_STEM), index_dir=tmp_path / "index")
    result = index.search("sekretess", limit=1, document_id="d2")
    assert [hit.key for hit in result.hits] == ["b"]


def test_filter_alone_is_not_a_lexical_hit(tmp_path: Path) -> None:
    units = [
        _unit("a", "Sekretess gäller.", document_id="d1"),
        _unit("b", "Helt annan text.", document_id="d2"),
    ]
    index = build_index(units, profile=build_profile(SV_STEM), index_dir=tmp_path / "index")
    assert index.search("sekretess", limit=10, document_id="d2").hits == []
    assert index.search("sekretess", limit=10, collection_id="missing").hits == []


def test_collection_filter_applies_before_top_k(tmp_path: Path) -> None:
    units = [
        _unit("a", "Sekretess gäller.", document_id="d1", collection_id="one"),
        _unit("b", "Sekretess gäller.", document_id="d2", collection_id="two"),
    ]
    index = build_index(units, profile=build_profile(SV_STEM), index_dir=tmp_path / "index")
    result = index.search("sekretess", limit=10, collection_id="two")
    assert [hit.key for hit in result.hits] == ["b"]


def test_index_verification_detects_changed_text_and_hash(tmp_path: Path) -> None:
    units = [_unit("a", "Sekretess gäller.", document_id="d1")]
    index = build_index(units, profile=build_profile(SV_STEM), index_dir=tmp_path / "index")
    verify_index(index, units)
    changed = [_unit("a", "Annan text.", document_id="d1")]
    with pytest.raises(RuntimeError):
        verify_index(index, changed)
    with pytest.raises(RuntimeError):
        open_index(
            index.path,
            profile=build_profile(SV_STEM),
            units=changed,
        )


def test_tie_at_branch_limit_is_overfetched_and_key_sorted(tmp_path: Path) -> None:
    units = [
        _unit(f"u{i}", "Sekretess gäller i avtalet.", document_id="d1", content_hash=f"h{i}")
        for i in range(5)
    ]
    index = build_index(units, profile=build_profile(SV_STEM), index_dir=tmp_path / "index")
    result = index.search("sekretess", limit=2)
    assert [hit.key for hit in result.hits] == ["u0", "u1"]
    assert result.tie.extra_fetched > 0
    assert result.tie.tie_boundary_score is not None


def test_index_is_reused_only_for_the_same_units(tmp_path: Path) -> None:
    units = [_unit("a", "Sekretess gäller.", document_id="d1")]
    first = build_index(units, profile=build_profile(SV_STEM), index_dir=tmp_path / "index")
    second = build_index(units, profile=build_profile(SV_STEM), index_dir=tmp_path / "index")
    assert first.path == second.path
    assert second.manifest["verification"]["verified_units"] == 1


def test_index_does_not_contain_gold_notes(tmp_path: Path) -> None:
    units = [_unit("a", "Sekretess gäller.", document_id="d1")]
    gold_note = "gold note must never be index text"
    index = build_index(units, profile=build_profile(SV_STEM), index_dir=tmp_path / "index")
    document = index.searcher.doc(index.searcher.search(__import__("tantivy").Query.all_query(), 1).hits[0][1])
    assert document.get_first("text") == units[0].text
    assert gold_note not in str(document.get_first("text"))
