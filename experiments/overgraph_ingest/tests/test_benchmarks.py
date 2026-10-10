import pytest

from overgraph_ingest.benchmarks.baseline import (
    BASELINE_ID,
    freeze_baseline,
    load_official_baseline,
)
from overgraph_ingest.benchmarks.corpus import write_pdf_contract
from overgraph_ingest.benchmarks.report import report_payload
from overgraph_ingest.benchmarks.suite import run_suite
from overgraph_ingest.config import IngestConfig
from overgraph_ingest.pipeline import prepare_documents, write_prepared
from tests.conftest import ingest, make_config


def test_official_baseline_is_the_sequential_100_docx_run() -> None:
    payload = load_official_baseline()
    assert payload["id"] == BASELINE_ID
    assert payload["document_count"] == 100
    assert payload["published"] == 100
    assert payload["failed"] == 0
    assert payload["headline"]["documents"] == "100/100"
    assert payload["total_seconds"] == pytest.approx(2.852701457682997)
    assert payload["documents_per_second"] == pytest.approx(35.054491850409526)
    assert payload["characters"] == 399936
    assert payload["text_coverage_mean"] == 1.0
    assert payload["reconstructed_documents"] == 100
    assert "Avtal_12_Uppsagningsbesked_overenskommelse_avslut.docx" in payload[
        "zero_clause_documents"
    ]
    assert "Avtal_70_Offertvillkor_orderbekraftelse.docx" in payload["zero_clause_documents"]


def test_freeze_baseline_keeps_zero_clause_paths() -> None:
    frozen = freeze_baseline(
        {
            "document_count": 2,
            "published": 2,
            "documents": [
                {
                    "relative_path": "a.docx",
                    "status": "PUBLISHED",
                    "clauses": 0,
                    "characters": 10,
                    "text_units": 1,
                    "structures": 1,
                    "coverage": 1.0,
                    "reconstructed": True,
                },
                {
                    "relative_path": "b.docx",
                    "status": "PUBLISHED",
                    "clauses": 4,
                    "characters": 20,
                    "text_units": 4,
                    "structures": 4,
                    "coverage": 1.0,
                    "reconstructed": True,
                },
            ],
        }
    )
    assert frozen["id"] == BASELINE_ID
    assert frozen["zero_clause_documents"] == ["a.docx"]
    assert "seconds" not in frozen["documents"][0]


def test_report_splits_finalize_and_batch_writes(ingest_paths) -> None:
    write_pdf_contract(ingest_paths["input"] / "avtal.pdf", 7)
    report = ingest(ingest_paths)
    assert report.finalize_seconds["end_ingest"] >= 0
    assert report.finalize_seconds["sync"] >= 0
    assert "end_ingest" in report.finalize_seconds
    assert report.write_batches
    assert any(batch["kind"] == "nodes" for batch in report.write_batches)
    payload = report_payload(make_config(ingest_paths), report)
    headline = payload["headline"]
    assert "overgraph_batch_write_seconds" in headline
    assert "end_ingest_seconds" in headline
    assert "sync_seconds" in headline
    assert payload["text_unit_size"]["median"] is not None
    assert payload["nodes_per_second"] > 0


def test_graph_only_write_excludes_extraction_time(ingest_paths) -> None:
    write_pdf_contract(ingest_paths["input"] / "avtal.pdf", 8)
    config = make_config(ingest_paths)
    prepared = prepare_documents(config)
    assert prepared[0].timings["extract"] > 0
    report = write_prepared(config, prepared)
    assert report.stage_seconds.get("extract", 0.0) == 0.0
    assert report.stage_seconds["write"] > 0
    assert report.outcomes[0].status == "PUBLISHED"


def test_suite_runs_small_matrix(tmp_path) -> None:
    config = IngestConfig(
        db_path=tmp_path / "unused-db",
        input_dir=tmp_path / "corpus",
        cache_dir=tmp_path / "cache",
        dense_dimension=8,
        write_batch_size=100,
        generate_corpus=4,
        repeats=1,
        output_path=tmp_path / "suite.json",
        gold_dir=tmp_path / "gold",
    )
    payload = run_suite(config)
    assert "A" in payload["experiments"]
    assert "F" in payload["experiments"]
    assert payload["quality"]["synthetic"]["case_count"] == 24
    assert "100" in payload["batch_sizes"]
    assert config.output_path is not None
    assert config.output_path.exists()
    assert payload["preparation"]["graph_construction_seconds"] >= 0
