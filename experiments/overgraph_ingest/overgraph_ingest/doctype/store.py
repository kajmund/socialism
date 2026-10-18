"""Store document_type on Document only. Filter without touching TextUnits."""

from __future__ import annotations

import time
from pathlib import Path

from overgraph_ingest.doctype.taxonomy import TAXONOMY_VERSION
from overgraph_ingest.graph.schema import DOCUMENT, TEXT_UNIT
from overgraph_ingest.graph.writer import GraphWriter, open_database

DOCUMENT_TYPE_PROP = "document_type"
CLASSIFICATION_PROPS = (
    DOCUMENT_TYPE_PROP,
    "classification_method",
    "classification_model",
    "classification_score",
    "taxonomy_version",
)


def store_document_type(
    writer: GraphWriter,
    *,
    document_id: str,
    document_type: str,
    method: str,
    model: str = "",
    score: float | None = None,
    extra_props: dict[str, object] | None = None,
) -> dict[str, object]:
    view = writer.get_document(document_id)
    props = dict(view.props) if view is not None else {}
    if extra_props:
        props.update(extra_props)
    props[DOCUMENT_TYPE_PROP] = document_type
    props["classification_method"] = method
    props["classification_model"] = model
    props["classification_score"] = score
    props["taxonomy_version"] = TAXONOMY_VERSION
    writer.publish_document(document_id, props)
    return props


def filter_documents(writer: GraphWriter, document_type: str) -> list[str]:
    paths = []
    for node in writer.iter_nodes(DOCUMENT):
        props = dict(node.props)
        if props.get(DOCUMENT_TYPE_PROP) == document_type:
            paths.append(str(props.get("relative_path") or node.key))
    return paths


def text_unit_snapshot(writer: GraphWriter) -> dict[str, str]:
    rows = {}
    for node in writer.iter_nodes(TEXT_UNIT):
        props = dict(node.props)
        rows[str(node.key)] = str(props.get("text") or "")
    return rows


def prove_store_and_filter(
    rows: list[dict[str, object]],
    *,
    db_path: Path,
    dense_dimension: int = 8,
) -> dict[str, object]:
    db = open_database(db_path, dense_dimension)
    try:
        writer = GraphWriter(db, batch_size=50)
        before_units = text_unit_snapshot(writer)
        write_started = time.perf_counter()
        for row in rows:
            store_document_type(
                writer,
                document_id=str(row["document_id"]),
                document_type=str(row["document_type"]),
                method=str(row["method"]),
                model=str(row.get("model") or ""),
                score=row.get("score") if isinstance(row.get("score"), (int, float)) else None,
                extra_props={
                    "relative_path": row["relative_path"],
                    "document_id": row["document_id"],
                },
            )
        write_seconds = time.perf_counter() - write_started
        db.flush()
        after_units = text_unit_snapshot(writer)
        filter_started = time.perf_counter()
        by_type = {
            document_type: filter_documents(writer, document_type)
            for document_type in sorted({str(row["document_type"]) for row in rows})
        }
        filter_seconds = time.perf_counter() - filter_started
        return {
            "documents": len(rows),
            "text_units_before": len(before_units),
            "text_units_after": len(after_units),
            "text_units_unchanged": before_units == after_units,
            "write_seconds": write_seconds,
            "filter_seconds": filter_seconds,
            "filter_by_type": {key: len(value) for key, value in by_type.items()},
        }
    finally:
        db.close()
