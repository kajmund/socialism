"""Archive hides a document and keeps Q&A. Purge removes the stored analysis."""

from __future__ import annotations

from app.services.document_qa.access import QaPermissionError, Viewer
from app.services.document_qa.labels import (
    CANONICAL_DOCUMENT,
    CONTAINS,
    HAS_ANSWER,
    HAS_POST,
    HAS_QUESTION,
    HAS_REVIEW,
    HAS_VERSION,
    QUESTION,
    TEXT_UNIT,
)
from app.services.overgraph.catalogs import Catalog


def archive_document(catalog: Catalog, viewer: Viewer, document_id: str) -> None:
    _require_document(viewer, document_id)
    row = catalog.get_by_key(CANONICAL_DOCUMENT, document_id)
    if row is None:
        return
    props = dict(row.props)
    props["archived"] = 1
    catalog.upsert_node(list(row.labels), row.key, props=props)
    if row.engine_id is None:
        return
    for question_id in catalog.neighbors(row.engine_id, edge_label_filter=[HAS_QUESTION]):
        _mark_question_archived(catalog, question_id)


def purge_document(
    catalog: Catalog,
    viewer: Viewer,
    document_id: str,
) -> None:
    _require_document(viewer, document_id)
    row = catalog.get_by_key(CANONICAL_DOCUMENT, document_id)
    if row is None or row.engine_id is None:
        return
    for question_id in catalog.neighbors(row.engine_id, edge_label_filter=[HAS_QUESTION]):
        _delete_question(catalog, question_id)
    for version_id in catalog.neighbors(row.engine_id, edge_label_filter=[HAS_VERSION]):
        _delete_version(catalog, version_id)
    catalog.delete_node(row.engine_id)


def _require_document(viewer: Viewer, document_id: str) -> None:
    if document_id not in viewer.readable_document_ids:
        raise QaPermissionError("workspace or document is not readable")


def _mark_question_archived(catalog: Catalog, engine_id: int) -> None:
    row = catalog.get(engine_id)
    if row is None or QUESTION not in row.labels:
        return
    props = dict(row.props)
    props["archived"] = 1
    catalog.upsert_node(list(row.labels), row.key, props=props, dense_vector=row.dense_vector)


def _delete_question(catalog: Catalog, engine_id: int) -> None:
    row = catalog.get(engine_id)
    if row is None:
        return
    for answer_id in catalog.neighbors(engine_id, edge_label_filter=[HAS_ANSWER]):
        _delete_answer(catalog, answer_id)
    catalog.delete_node(engine_id)


def _delete_answer(catalog: Catalog, engine_id: int) -> None:
    for post_id in catalog.neighbors(engine_id, edge_label_filter=[HAS_POST]):
        catalog.delete_node(post_id)
    for review_id in catalog.neighbors(engine_id, edge_label_filter=[HAS_REVIEW]):
        catalog.delete_node(review_id)
    catalog.delete_node(engine_id)


def _delete_version(catalog: Catalog, engine_id: int) -> None:
    for unit_id in catalog.neighbors(engine_id, edge_label_filter=[CONTAINS]):
        unit = catalog.get(unit_id)
        if unit is not None and TEXT_UNIT in unit.labels:
            catalog.delete_node(unit_id)
    catalog.delete_node(engine_id)


def document_is_archived(catalog: Catalog, document_id: str) -> bool:
    row = catalog.get_by_key(CANONICAL_DOCUMENT, document_id)
    if row is None:
        return False
    return bool(int(row.props.get("archived") or 0))


def document_exists(catalog: Catalog, document_id: str) -> bool:
    return catalog.get_by_key(CANONICAL_DOCUMENT, document_id) is not None


