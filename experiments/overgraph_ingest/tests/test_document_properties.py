from __future__ import annotations

from overgraph_ingest.retrieval.document_properties import (
    SUPPORTED,
    UNDECIDED,
    extract_document_properties,
    load_gold_mapping,
    load_taxonomy,
    lookup_documents,
    run_document_properties,
)
from overgraph_ingest.retrieval.gold import GoldSpan, RetrievalGold
from overgraph_ingest.retrieval.index import StoredUnit


def _unit(key: str, path: str, text: str, *, document_id: str = "doc", structure_id: str = "") -> StoredUnit:
    return StoredUnit(1, key, document_id, path, text, None, None, content_hash=key, structure_id=structure_id)


def _structures(*titles: str, document_id: str = "doc") -> dict[str, dict[str, object]]:
    return {
        f"s{index}": {"title": title, "document_id": document_id}
        for index, title in enumerate(titles)
    }


def test_taxonomy_and_mapping_load_with_hashes() -> None:
    taxonomy = load_taxonomy()
    mapping = load_gold_mapping()
    assert "governing_law" in taxonomy
    assert "confidentiality_obligation" in taxonomy
    assert mapping["auto-renewal"] == ("automatic_renewal",)
    assert mapping["liability-secrecy-carveout"] == ("liability_secrecy_carveout",)


def test_negative_and_heading_only_are_not_positive() -> None:
    units = [
        _unit("a", "a.docx", "Konsulten ska hålla konfidentiell information hemlig.", document_id="a"),
        _unit("b", "b.docx", "Detta avtal innehåller ingen sekretessförpliktelse.", document_id="b"),
        _unit("c", "c.docx", "Parterna ska samarbeta.", document_id="c", structure_id="s0"),
    ]
    structures = {
        **{f"a{index}": {"title": "Sekretess", "document_id": "a"} for index in range(2)},
        "s0": {"title": "9. Sekretess", "document_id": "c"},
    }
    props = extract_document_properties(units, structures, load_taxonomy())
    positive = props["a.docx"][0]
    assert positive.class_id == "confidentiality_obligation"
    assert positive.polarity == "positive"
    assert positive.support == SUPPORTED
    negative = props["b.docx"][0]
    assert negative.class_id == "confidentiality_obligation"
    assert negative.polarity == "negative"
    heading = next(item for item in props["c.docx"] if item.class_id == "confidentiality_obligation")
    assert heading.support == UNDECIDED


def test_composite_carveout_requires_liability() -> None:
    units = [
        _unit("a", "a.docx", "Brott mot sekretess är undantaget.", document_id="a"),
        _unit("b1", "b.docx", "Ansvaret är begränsat.", document_id="b"),
        _unit("b2", "b.docx", "Brott mot sekretess är undantaget.", document_id="b"),
    ]
    props = extract_document_properties(units, {}, load_taxonomy())
    carve_a = next(item for item in props["a.docx"] if item.class_id == "liability_secrecy_carveout")
    carve_b = next(item for item in props["b.docx"] if item.class_id == "liability_secrecy_carveout")
    assert carve_a.support == UNDECIDED
    assert carve_b.support == SUPPORTED


def test_lookup_is_not_truncated_to_top_k() -> None:
    units = [_unit(f"u{i}", f"d{i}.docx", "Svensk lag gäller.", document_id=f"doc{i}") for i in range(60)]
    props = extract_document_properties(units, {}, load_taxonomy())
    found = lookup_documents(props, "governing_law")
    assert len(found) == 60


def test_run_reports_property_recall_and_precision() -> None:
    units = [
        _unit("p1", "p1.docx", "Sekretess gäller under avtalstiden.", document_id="doc1"),
        _unit("p2", "p2.docx", "Parterna har tystnadsplikt.", document_id="doc2"),
        _unit("p3", "p3.docx", "Konfidentiell information ska skyddas.", document_id="doc3"),
        _unit("neg", "neg.docx", "Detta avtal innehåller ingen sekretess.", document_id="doc4"),
        _unit("irr", "irr.docx", "Avtalet gäller tills vidare.", document_id="doc5"),
    ]
    gold = RetrievalGold(
        id="confidentiality",
        query="Vilka avtal innehåller en sekretessplikt?",
        relevant_units=[
            GoldSpan("p1.docx", "Sekretess gäller"),
            GoldSpan("p2.docx", "tystnadsplikt"),
            GoldSpan("p3.docx", "Konfidentiell information"),
        ],
        hard_negatives=[],
    )
    payload = run_document_properties(
        type("Cfg", (), {"db_path": __import__("pathlib").Path("/tmp/unused"), "dense_dimension": 8, "write_batch_size": 50})(),
        units=units,
        structures={},
        golds=[gold],
    ).payload
    row = payload["rows"][0]
    assert row["property_recall"] == 1.0
    assert row["property_precision"] == 1.0
    assert row["lookup_completeness"] == 1.0
    assert row["recovered_missed_count"] == 3
    assert row["verification"]["gold_supported"] == 3
    assert payload["taxonomy_hash"] and payload["mapping_hash"]


def test_false_positive_review_set_includes_context_and_null_judgments() -> None:
    from overgraph_ingest.retrieval.document_properties import (
        build_false_positive_review_set,
    )

    units = [
        _unit("gold1", "gold.docx", "Sekretess gäller under avtalstiden.", document_id="doc1"),
        _unit("fp1", "fp.docx", "Parterna ska samarbeta om sekretess.", document_id="doc2", structure_id="s0"),
    ]
    structures = {"s0": {"title": "4. Sekretess", "document_id": "doc2"}}
    gold = RetrievalGold(
        id="confidentiality",
        query="Vilka avtal innehåller en sekretessplikt?",
        relevant_units=[GoldSpan("gold.docx", "Sekretess gäller")],
        hard_negatives=[],
    )
    review = build_false_positive_review_set(
        type("Cfg", (), {"db_path": __import__("pathlib").Path("/tmp/unused"), "dense_dimension": 8, "write_batch_size": 50})(),
        units=units,
        structures=structures,
        golds=[gold],
    )
    assert review["count"] == 1
    entry = review["entries"][0]
    assert entry["relative_path"] == "fp.docx"
    assert entry["property_class"] == "confidentiality_obligation"
    assert entry["evidence"][0]["excerpt"]
    assert entry["evidence"][0]["clause_title"] == "4. Sekretess"
    assert entry["review"]["classification"] is None
    assert entry["review"]["property_judgment"] is None
