from __future__ import annotations

from pathlib import Path

import pytest

from overgraph_ingest.config import IngestConfig
from overgraph_ingest.graph.schema import TEXT_UNIT
from overgraph_ingest.graph.writer import GraphWriter, open_database
from overgraph_ingest.pipeline import run_ingest


@pytest.fixture
def ingest_paths(tmp_path: Path) -> dict[str, Path]:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    return {
        "input": input_dir,
        "db": tmp_path / "overgraph-data",
        "cache": tmp_path / "extract-cache",
    }


def make_config(paths: dict[str, Path], **overrides: object) -> IngestConfig:
    values = {
        "db_path": paths["db"],
        "input_dir": paths["input"],
        "cache_dir": paths["cache"],
        "collection_id": "test",
        "dense_dimension": 8,
        "write_batch_size": 50,
        "target_chars": 80,
        "max_chars": 160,
    }
    values.update(overrides)
    return IngestConfig(**values)  # type: ignore[arg-type]


def unit_keys(db_path: Path) -> list[str]:
    db = open_database(db_path, 8)
    try:
        writer = GraphWriter(db, batch_size=50)
        return sorted(node.key for node in writer.iter_nodes(TEXT_UNIT))
    finally:
        db.close()


def ingest(paths: dict[str, Path], **overrides: object):
    return run_ingest(make_config(paths, **overrides))
