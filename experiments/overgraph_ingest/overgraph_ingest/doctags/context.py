"""Load tag documents, then close the database before Jev."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from overgraph_ingest.doctags.gold import DOCUMENTS
from overgraph_ingest.graph.writer import GraphWriter, open_database, resolve_dimension
from overgraph_ingest.retrieval.index import StoredUnit, load_published_units
from overgraph_ingest.tabular.run import DEFAULT_DB


@dataclass(frozen=True)
class TagDocument:
    document_id: str
    relative_path: str
    units: tuple[StoredUnit, ...]


def load_tag_documents(
    *,
    db_path: Path | None = None,
    dense_dimension: int | None = None,
    documents: tuple[str, ...] = DOCUMENTS,
    units: list[StoredUnit] | None = None,
) -> list[TagDocument]:
    if units is not None:
        return _group(units, documents)
    target = db_path or DEFAULT_DB
    dimension = resolve_dimension(target, dense_dimension)
    db = open_database(target, dimension)
    try:
        writer = GraphWriter(db, batch_size=500)
        stored = [
            unit
            for unit in load_published_units(writer)
            if unit.relative_path in documents
        ]
        return _group(stored, documents)
    finally:
        db.close()


def _group(units: list[StoredUnit], documents: tuple[str, ...]) -> list[TagDocument]:
    by_path: dict[str, list[StoredUnit]] = {}
    for unit in units:
        by_path.setdefault(unit.relative_path, []).append(unit)
    rows = []
    for path in documents:
        local = sorted(by_path.get(path, []), key=lambda item: item.sequence or 0)
        if not local:
            continue
        rows.append(
            TagDocument(
                document_id=local[0].document_id,
                relative_path=path,
                units=tuple(local),
            )
        )
    return rows
