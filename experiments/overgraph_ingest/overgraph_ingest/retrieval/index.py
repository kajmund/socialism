"""Write dense and sparse vectors onto published TextUnits, then flush."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from overgraph_ingest.graph.schema import DOCUMENT, TEXT_UNIT
from overgraph_ingest.graph.writer import GraphWriter
from overgraph_ingest.retrieval.encode import DenseEncoder, LexicalSparseEncoder


@dataclass(frozen=True)
class StoredUnit:
    node_id: int
    key: str
    document_id: str
    relative_path: str
    text: str
    dense: list[float] | None
    sparse: list[tuple[int, float]] | None
    structure_id: str = ""
    sequence: int | None = None


@dataclass
class IndexStats:
    units: int = 0
    embedded: int = 0


def load_published_units(writer: GraphWriter) -> list[StoredUnit]:
    paths = _document_paths(writer)
    units: list[StoredUnit] = []
    for node in writer.iter_nodes(TEXT_UNIT):
        props = dict(node.props)
        document_id = str(props.get("document_id") or "")
        relative_path = paths.get(document_id, "")
        if not relative_path:
            continue
        dense = _vector(getattr(node, "dense_vector", None))
        sparse = _sparse(getattr(node, "sparse_vector", None))
        units.append(
            StoredUnit(
                node_id=int(node.id),
                key=str(node.key),
                document_id=document_id,
                relative_path=relative_path,
                text=str(props.get("text") or ""),
                dense=dense,
                sparse=sparse,
                structure_id=str(props.get("structure_id") or ""),
                sequence=int(props["sequence"]) if props.get("sequence") is not None else None,
            )
        )
    return units


def embed_published_units(
    writer: GraphWriter,
    *,
    dense: DenseEncoder,
    sparse: LexicalSparseEncoder,
) -> IndexStats:
    units = load_published_units(writer)
    stats = IndexStats(units=len(units))
    if not units:
        return stats
    texts = [unit.text for unit in units]
    sparse.fit(texts)
    dense_vectors = dense.embed(texts)
    sparse_vectors = sparse.embed(texts)
    payloads = []
    for unit, dense_vector, sparse_vector in zip(units, dense_vectors, sparse_vectors, strict=True):
        view = writer.get_node(TEXT_UNIT, unit.key)
        if view is None:
            raise KeyError(f"missing TextUnit {unit.key}")
        props = dict(view.props)
        props["dense_model"] = dense.model
        props["sparse_encoder"] = sparse.encoder_id
        payloads.append(
            {
                "labels": [TEXT_UNIT],
                "key": unit.key,
                "props": props,
                "dense_vector": list(dense_vector),
                "sparse_vector": list(sparse_vector),
            }
        )
    writer.write_vectors(payloads)
    writer.db.flush()
    stats.embedded = len(payloads)
    return stats


def _document_paths(writer: GraphWriter) -> dict[str, str]:
    paths: dict[str, str] = {}
    for node in writer.iter_nodes(DOCUMENT):
        props = dict(node.props)
        document_id = str(props.get("document_id") or node.key)
        paths[document_id] = str(props.get("relative_path") or "")
    return paths


def _vector(raw: Any) -> list[float] | None:
    if not raw:
        return None
    return [float(value) for value in raw]


def _sparse(raw: Any) -> list[tuple[int, float]] | None:
    if not raw:
        return None
    return [(int(index), float(value)) for index, value in raw]
