from __future__ import annotations

import json
from pathlib import Path

import pytest

from overgraph_ingest.benchmarks.corpus import write_retrieval_corpus
from overgraph_ingest.config import IngestConfig, RetrievalConfig
from overgraph_ingest.graph.writer import GraphWriter, open_database
from overgraph_ingest.pipeline import run_ingest
from overgraph_ingest.retrieval.discovery import (
    AGGREGATIONS,
    aggregate_document_scores,
    run_document_discovery,
)
from overgraph_ingest.retrieval.encode import HashedDenseEncoder, LexicalSparseEncoder
from overgraph_ingest.retrieval.index import StoredUnit, embed_published_units


def _unit(key: str, path: str) -> StoredUnit:
    return StoredUnit(1, key, "doc", path, key, None, None, content_hash=key)


def test_top3_aggregation_reorders_documents() -> None:
    units = [
        _unit("a1", "a.docx"),
        _unit("a2", "a.docx"),
        _unit("a3", "a.docx"),
        _unit("b1", "b.docx"),
        _unit("b2", "b.docx"),
    ]
    scores = {"a1": 0.9, "a2": 0.1, "a3": 0.05, "b1": 0.6, "b2": 0.55}
    documents = aggregate_document_scores(units, scores)
    assert documents["a.docx"]["dense_top1"] == 0.9
    assert documents["b.docx"]["dense_top1"] == 0.6
    assert documents["b.docx"]["dense_top3_sum"] == pytest.approx(1.15)
    assert documents["a.docx"]["dense_top3_sum"] == pytest.approx(1.05)
    assert documents["b.docx"]["dense_top3_mean"] > documents["a.docx"]["dense_top3_mean"]


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
    finally:
        db.close()
    gold_dir = tmp_path / "gold"
    gold_dir.mkdir()
    (gold_dir / "index.json").write_text(
        json.dumps(
            {
                "id": "suite",
                "notes": "",
                "golds": [
                    {"id": "auto-renewal", "path": "auto.json", "status": "measured"}
                ],
            }
        )
    )
    (gold_dir / "auto.json").write_text(
        json.dumps(
            {
                "id": "auto-renewal",
                "query": "Vilka avtal innehåller bestämmelser om automatisk förlängning?",
                "relevant_units": [
                    {
                        "relative_path": "forlangning.docx",
                        "contains": "förlängs automatiskt med samma period",
                    }
                ],
                "hard_negatives": [
                    {
                        "relative_path": "ingen_forlangning.docx",
                        "contains": "förlängs inte automatiskt",
                    }
                ],
            }
        )
    )
    return {"db_path": db_path, "gold_dir": gold_dir}


def test_discovery_runs_all_arms_at_equal_budget(tiny_db) -> None:
    payload = run_document_discovery(
        RetrievalConfig(
            db_path=tiny_db["db_path"],
            dense_dimension=8,
            dense_model="hashed-dense-v1",
        ),
        gold_dir=tiny_db["gold_dir"],
    ).payload
    assert payload["status"] == "completed"
    assert payload["equal_budget_docs"] == 10
    assert set(payload["macro"]) >= set(AGGREGATIONS) | {
        "hybrid_units_20",
        "hybrid_units_50",
        "dense_units_20",
        "dense_units_50",
    }
    for arm in AGGREGATIONS:
        assert set(payload["macro"][arm]["document_recall_by_budget"]) == {"10", "20", "50"}
    row = payload["rows"][0]
    assert set(row["baselines"]) >= {"hybrid_units_50", "dense_units_50"}
    assert row["arms"]["dense_top3_sum"]["at_budget"]["10"]["units_examined"] > 0
    assert row["arms"]["dense_top1"]["ordered_documents"]


def test_discovery_reports_new_documents_vs_hybrid(tiny_db) -> None:
    payload = run_document_discovery(
        RetrievalConfig(
            db_path=tiny_db["db_path"],
            dense_dimension=8,
            dense_model="hashed-dense-v1",
        ),
        gold_dir=tiny_db["gold_dir"],
    ).payload
    arm = payload["rows"][0]["arms"]["dense_top1"]
    assert "new_documents_vs_hybrid50" in arm["at_budget"]["10"]
    assert "missed_vs_hybrid50" in arm["at_budget"]["10"]
    assert isinstance(arm["at_budget"]["10"]["new_documents_vs_hybrid50"], list)
