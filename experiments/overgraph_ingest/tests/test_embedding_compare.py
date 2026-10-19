import json
from pathlib import Path

import pytest
from overgraph import OverGraph

from overgraph_ingest.benchmarks.corpus import write_pdf_contract
from overgraph_ingest.config import RetrievalConfig
from overgraph_ingest.graph.schema import TEXT_UNIT
from overgraph_ingest.graph.writer import GraphWriter, open_database
from overgraph_ingest.retrieval import compare_run
from overgraph_ingest.retrieval.compare_run import (
    REFERENCE_VARIANT,
    VARIANTS,
    EmbeddingVariant,
    run_embedding_compare,
)
from overgraph_ingest.retrieval.encode import (
    HashedDenseEncoder,
    LexicalSparseEncoder,
    build_dense_encoder,
    build_sparse_encoder,
)
from overgraph_ingest.retrieval.gold import RetrievalGold
from overgraph_ingest.retrieval.index import embed_published_units, load_published_units
from tests.conftest import ingest


GOLD_DIR = Path(__file__).resolve().parents[1] / "retrieval_gold"


def test_embedding_variants_only_swap_encoders() -> None:
    assert [item.id for item in VARIANTS] == [
        "openai-tfidf",
        "bge-m3-tfidf",
        "bge-m3",
        "openai-bge-sparse",
    ]
    reference = VARIANTS[0]
    assert reference.id == REFERENCE_VARIANT
    assert reference.reuse_reference is True
    assert reference.write_dense is False
    assert reference.write_sparse is False
    assert {item.dimension for item in VARIANTS} == {1024, 3072}


def test_unknown_encoders_fail_loudly() -> None:
    with pytest.raises(ValueError, match="unknown dense model"):
        build_dense_encoder(model="mystery", dimension=8)
    with pytest.raises(ValueError, match="unknown sparse encoder"):
        build_sparse_encoder("mystery")
    with pytest.raises(ValueError, match="requires dense dimension 1024"):
        build_dense_encoder(model="bge-m3", dimension=3072)


def test_compare_requires_the_official_3072_reference(tmp_path: Path) -> None:
    db = tmp_path / "wrong-dim"
    db.mkdir()
    (db / "manifest.current").write_text(
        json.dumps({"dense_vector": {"dimension": 8}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="3072"):
        run_embedding_compare(RetrievalConfig(db_path=db), gold_dir=GOLD_DIR)


def test_sparse_rewrite_keeps_existing_dense(ingest_paths) -> None:
    write_pdf_contract(ingest_paths["input"] / "avtal.pdf", 7)
    ingest(ingest_paths)
    db = open_database(ingest_paths["db"], 8)
    try:
        writer = GraphWriter(db, batch_size=50)
        first = embed_published_units(
            writer,
            dense=HashedDenseEncoder(8),
            sparse=LexicalSparseEncoder(),
        )
        before = {unit.key: unit.dense for unit in load_published_units(writer)}
        second = embed_published_units(
            writer,
            dense=HashedDenseEncoder(8),
            sparse=LexicalSparseEncoder(),
            write_dense=False,
            write_sparse=True,
        )
        after = load_published_units(writer)
        assert first.embedded == second.embedded
        assert {unit.key: unit.dense for unit in after} == before
        view = writer.get_node(TEXT_UNIT, after[0].key)
        assert view is not None
        assert dict(view.props)["sparse_encoder"] == "lexical-tfidf-hash-v1"
    finally:
        db.close()


def test_run_variant_keeps_the_database_closed_during_encoder_calls(
    monkeypatch: pytest.MonkeyPatch, ingest_paths
) -> None:
    write_pdf_contract(ingest_paths["input"] / "avtal.pdf", 7)
    ingest(ingest_paths)
    db = open_database(ingest_paths["db"], 8)
    try:
        writer = GraphWriter(db, batch_size=50)
        embed_published_units(
            writer,
            dense=HashedDenseEncoder(8),
            sparse=LexicalSparseEncoder(),
        )
    finally:
        db.close()

    open_handles = {"count": 0}
    real_open = compare_run.open_database
    real_close = OverGraph.close

    def tracked_open(path: Path, dimension: int) -> OverGraph:
        open_handles["count"] += 1
        return real_open(path, dimension)

    def tracked_close(self: OverGraph) -> None:
        open_handles["count"] -= 1
        real_close(self)

    monkeypatch.setattr(compare_run, "open_database", tracked_open)
    monkeypatch.setattr(OverGraph, "close", tracked_close)

    class RecordingDense:
        model = "hashed-dense-v1"
        dimension = 8

        def __init__(self) -> None:
            self._inner = HashedDenseEncoder(8)

        def embed(self, texts):
            assert open_handles["count"] == 0, "database must be closed during dense encoding"
            return self._inner.embed(texts)

    class RecordingSparse:
        encoder_id = "lexical-tfidf-hash-v1"

        def __init__(self) -> None:
            self._inner = LexicalSparseEncoder()

        def fit(self, texts) -> None:
            assert open_handles["count"] == 0, "database must be closed during sparse fitting"
            self._inner.fit(texts)

        def embed(self, texts):
            assert open_handles["count"] == 0, "database must be closed during sparse encoding"
            return self._inner.embed(texts)

    monkeypatch.setattr(compare_run, "build_dense_encoder", lambda **kwargs: RecordingDense())
    monkeypatch.setattr(compare_run, "build_sparse_encoder", lambda name: RecordingSparse())

    variant = EmbeddingVariant(
        "reuse-test",
        "hashed-dense-v1",
        "lexical-tfidf-hash-v1",
        8,
        False,
        False,
        True,
        False,
        "",
    )
    gold = RetrievalGold(
        id="release-check",
        query="förlängs automatiskt",
        relevant_units=[],
        hard_negatives=[],
    )
    payload = compare_run._run_variant(
        variant,
        config=RetrievalConfig(
            db_path=ingest_paths["db"],
            dense_dimension=8,
            write_batch_size=50,
        ),
        golds=[gold],
        input_dir=None,
        cache_dir=None,
        collection_id="test",
        query_repeats=0,
    )
    assert open_handles["count"] == 0
    assert payload["units"] >= 1
    assert payload["golds"][0]["gold_id"] == "release-check"
    assert payload["embedded"] is None
