from __future__ import annotations

from pathlib import Path

import pytest

from overgraph_ingest.benchmarks.corpus import write_retrieval_corpus
from overgraph_ingest.config import IngestConfig, RetrievalConfig
from overgraph_ingest.graph.writer import GraphWriter, open_database
from overgraph_ingest.pipeline import run_ingest
from overgraph_ingest.retrieval.bm25_run import (
    ARM_IDS,
    _dedupe_branch,
    _k_to,
    _twenty_vs_fifty,
    run_bm25_experiment,
)
from overgraph_ingest.retrieval.encode import HashedDenseEncoder, LexicalSparseEncoder
from overgraph_ingest.retrieval.evidence_gold import (
    CellEvidenceGold,
    EvidenceAlternative,
    EvidenceGroup,
)
from overgraph_ingest.retrieval.gold import GoldSpan, RetrievalGold
from overgraph_ingest.retrieval.index import embed_published_units, load_published_units
from overgraph_ingest.retrieval.search import SearchHit, encode_query
from overgraph_ingest.tabular.gold import USER_QUESTIONS


@pytest.fixture
def tiny_db(tmp_path: Path):
    input_dir = tmp_path / "input"
    db_path = tmp_path / "db"
    write_retrieval_corpus(input_dir)
    run_ingest(
        IngestConfig(
            db_path=db_path,
            input_dir=input_dir,
            cache_dir=tmp_path / "cache",
            collection_id="test",
            dense_dimension=8,
            target_chars=2000,
            max_chars=4000,
        )
    )
    db = open_database(db_path, 8)
    try:
        writer = GraphWriter(db, batch_size=50)
        embed_published_units(
            writer,
            dense=HashedDenseEncoder(8),
            sparse=LexicalSparseEncoder(),
        )
        units = load_published_units(writer)
    finally:
        db.close()
    gold = RetrievalGold(
        id="test-renewal",
        query="Vilka avtal innehåller bestämmelser om automatisk förlängning?",
        relevant_units=[
            GoldSpan("forlangning.docx", "förlängs automatiskt med samma period")
        ],
        hard_negatives=[GoldSpan("ingen_forlangning.docx", "förlängs inte automatiskt")],
    )
    cell = CellEvidenceGold(
        question_id="auto-renewal",
        relative_path="forlangning.docx",
        split="development",
        answerability="answerable",
        positive_property=True,
        groups=(
            EvidenceGroup(
                "answer",
                (
                    EvidenceAlternative(
                        "forlangning.docx", "förlängs automatiskt med samma period"
                    ),
                ),
            ),
        ),
    )
    empty_cell = CellEvidenceGold(
        question_id="auto-renewal",
        relative_path="sekretess.docx",
        split="development",
        answerability="not_evaluated",
        positive_property=None,
        groups=(),
    )
    dense = HashedDenseEncoder(8)
    sparse = LexicalSparseEncoder()
    sparse.fit([unit.text for unit in units])
    queries = {
        f"global:{gold.id}": encode_query(gold.query, dense=dense, sparse=sparse),
        "doc:auto-renewal": encode_query(USER_QUESTIONS["auto-renewal"], dense=dense, sparse=sparse),
    }
    return {
        "db_path": db_path,
        "units": units,
        "gold": gold,
        "cells": [cell, empty_cell],
        "queries": queries,
        "tmp_path": tmp_path,
    }


def _run(env, *, analyzers=("sv_stem_v1",), scope="both", repeats=1):
    return run_bm25_experiment(
        RetrievalConfig(
            db_path=env["db_path"],
            dense_dimension=8,
            dense_model="hashed-dense-v1",
            ks=(5, 10, 20, 50),
        ),
        golds=[env["gold"]],
        cells=env["cells"],
        queries=env["queries"],
        units=env["units"],
        index_dir=env["tmp_path"] / "index",
        analyzers=analyzers,
        scope=scope,
        global_ks=(5, 10, 20, 50),
        local_ks=(1, 3, 5, 10),
        repeats=repeats,
    )


def test_all_arms_exist_and_main_is_dense_bm25(tiny_db) -> None:
    payload = _run(tiny_db, scope="global")
    row = payload["profiles"]["sv_stem_v1"]["global"]["rows"][0]
    assert set(row["arms"]) == set(ARM_IDS)
    assert "dense_bm25" in row["arms"]
    assert payload["manifest"]["rrf"]["k"] == 60
    assert payload["manifest"]["rrf"]["equal_weight"] is True
    assert payload["production_changed"] is False
    assert payload["default_retriever_unchanged"] is True


def test_empty_bm25_leaves_dense_order_unchanged(tiny_db) -> None:
    payload = _run(tiny_db, scope="document")
    rows = payload["profiles"]["sv_stem_v1"]["document"]["rows"]
    row = next(item for item in rows if item["relative_path"] == "sekretess.docx")
    assert row["branch_meta"]["bm25_empty"] is True
    dense_keys = [hit["key"] for hit in row["arms"]["dense"]["candidates"]]
    fused_keys = [hit["key"] for hit in row["arms"]["dense_bm25"]["candidates"]]
    assert fused_keys == dense_keys


def test_zero_score_sparse_is_visible(tiny_db) -> None:
    payload = _run(tiny_db, scope="document")
    rows = payload["profiles"]["sv_stem_v1"]["document"]["rows"]
    row = next(item for item in rows if item["relative_path"] == "sekretess.docx")
    assert row["branch_meta"]["sparse_zero_score_count"] > 0
    comparisons = payload["profiles"]["sv_stem_v1"]["comparisons"]["document"]
    assert "zero_score_sparse_hits" in comparisons["control_vs_positive"]


def test_prefix_consistency(tiny_db) -> None:
    payload = _run(tiny_db, scope="global")
    row = payload["profiles"]["sv_stem_v1"]["global"]["rows"][0]
    safe = [hit["key"] for hit in row["arms"]["dense_bm25"]["candidates"]]
    for k in (5, 10, 20, 50):
        top = [hit["key"] for hit in row["arms"]["dense_bm25"]["at_k"][str(k)]["hits"]]
        assert top == safe[:k]


def test_duplicate_hits_are_removed_before_fusion() -> None:
    hits = [
        SearchHit(1, "a", 1.0, 1, "d", "a.docx", "x"),
        SearchHit(1, "a", 1.0, 2, "d", "a.docx", "x"),
        SearchHit(2, "b", 0.5, 3, "d", "b.docx", "y"),
    ]
    deduped = _dedupe_branch(hits)
    assert [hit.key for hit in deduped] == ["a", "b"]
    assert [hit.rank for hit in deduped] == [1, 2]


def test_k_to_is_not_reached_without_gold() -> None:
    group = EvidenceGroup("g", (EvidenceAlternative("a.docx", "text"),))
    assert _k_to([], (group,), threshold=1.0, complete=False)["status"] == "not_reached"


def test_twenty_vs_fifty_marks_impossible_full_coverage() -> None:
    row = {
        "gold_id": "governing-law",
        "required_groups": 75,
        "arms": {
            "dense_bm25": {"at_k": {"20": {"document_recall": 0.2}}},
            "hybrid_current": {"at_k": {"50": {"document_recall": 0.6}}},
            "dense": {"at_k": {"50": {"document_recall": 0.5}}},
        },
    }
    payload = _twenty_vs_fifty([row], (5, 10, 20, 50))
    assert payload["governing-law"]["applicable"] is False
    assert payload["governing-law"]["ceiling_at_20"] == 20


def test_manifest_records_gold_units_and_limitations(tiny_db) -> None:
    payload = _run(tiny_db, scope="global")
    manifest = payload["manifest"]
    assert manifest["gold"]["written_before_bm25_results"] is True
    assert manifest["corpus"]["units_metadata"]["count"] == len(tiny_db["units"])
    assert manifest["tantivy"]["sv_stem_v1"]["index"]["verification"]["verified_units"] == len(
        tiny_db["units"]
    )
    assert payload["limitations"]


def test_paging_replay_uses_frozen_dense_bm25(tiny_db) -> None:
    from overgraph_ingest.retrieval.bm25_run import run_paging_test

    payload = _run(tiny_db, scope="document")
    result = run_paging_test(payload, page_size=20, profile="sv_stem_v1")
    assert result["status"] == "completed"
    assert result["replay"] is True
    assert result["page_size"] == 20
    assert result["rows"]


def test_freeze_never_overwrites_and_report_is_readable(tiny_db, tmp_path: Path) -> None:
    from overgraph_ingest.retrieval.bm25_run import (
        freeze_bm25_baseline,
        write_bm25_baseline,
        write_bm25_report,
    )

    payload = _run(tiny_db, scope="global")
    frozen = freeze_bm25_baseline(payload)
    assert frozen["do_not_overwrite"] is True
    assert frozen["does_not_replace_c8"] is True
    assert frozen["profiles"]["sv_stem_v1"]["global"]["rows"]
    target = tmp_path / "baseline.json"
    write_bm25_baseline(payload, target)
    with pytest.raises(FileExistsError):
        write_bm25_baseline(payload, target)
    report = write_bm25_report(payload, tmp_path / "report.md")
    text = report.read_text()
    assert "# Tantivy BM25 v1" in text
    assert "Limitations" in text
