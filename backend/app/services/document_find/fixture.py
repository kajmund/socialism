"""Build representative tenant OverGraph fixtures for document-find tests."""

from __future__ import annotations

from collections.abc import Sequence

from app.services.document_find.category_index import apply_effective_type, ensure_document
from app.services.document_find.labels import CANONICAL_DOCUMENT, HAS_VERSION
from app.services.document_find.strategies import classify_and_index
from app.services.document_find.taxonomy import LEASE
from app.services.document_qa.catalog_write import write_document_units
from app.services.knowledge.scope import customer_scope
from app.services.knowledge.units import hash_text, make_text_unit_id
from app.services.overgraph.browse import catalog_summary
from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.labels import DOCUMENT_VERSION, TEXT_UNIT, scope_label
from app.services.overgraph.model import TextUnitWrite

DIM = 8
_BATCH = 500


def vector(*values: float) -> tuple[float, ...]:
    out = [0.0] * DIM
    for index, value in enumerate(values):
        out[index] = float(value)
    return tuple(out)


async def add_document(
    catalog: Catalog,
    *,
    document_id: str,
    title: str,
    passages: Sequence[tuple[str, Sequence[float]]],
    customer_id: int = 1,
    classify: bool = True,
    opening: str | None = None,
) -> str:
    """Insert document + TextUnits. Optionally run classification → category index."""
    version_id = f"{document_id}-v1"
    scope = customer_scope(customer_id)
    units: list[TextUnitWrite] = []
    for ordinal, (text, embedding) in enumerate(passages):
        digest = hash_text(text)
        unit_id = make_text_unit_id(
            document_version_id=version_id, locator=f"p{ordinal}", content_hash=digest,
        )
        units.append(TextUnitWrite(
            unit_id=unit_id,
            scope=scope,
            document_id=document_id,
            document_version_id=version_id,
            text=text,
            content_hash=digest,
            ordinal=ordinal,
            locator=f"p{ordinal}",
            embedding=tuple(embedding),
        ))
    await write_document_units(catalog, document_id=document_id, units=units)
    row = catalog.get_by_key(CANONICAL_DOCUMENT, document_id)
    props = dict(row.props) if row else {"document_id": document_id, "archived": 0}
    props["title"] = title
    catalog.upsert_node([CANONICAL_DOCUMENT], document_id, props=props)
    if classify:
        first = passages[0][0] if passages else ""
        classify_and_index(
            catalog,
            document_id=document_id,
            title=title,
            opening=opening if opening is not None else first,
        )
    return document_id


def seed_classified_documents(
    catalog: Catalog,
    *,
    count: int,
    document_type: str = LEASE,
    id_prefix: str = "scale-lease",
) -> list[str]:
    """Fast category-index seed: documents + type links, no TextUnits."""
    ids: list[str] = []
    for index in range(count):
        document_id = f"{id_prefix}-{index}"
        ensure_document(catalog, document_id)
        apply_effective_type(
            catalog, document_id=document_id, document_type=document_type,
        )
        ids.append(document_id)
    return ids


def seed_text_units_bulk(
    catalog: Catalog,
    *,
    document_ids: Sequence[str],
    units_per_document: int,
    customer_id: int = 1,
    embedding: Sequence[float] | None = None,
) -> int:
    """Bulk-insert TextUnit nodes to stress category independence."""
    emb = tuple(embedding) if embedding is not None else vector(0.1, 0.9)
    scope = scope_label(customer_scope(customer_id).scope_key)
    batch: list[dict] = []
    written = 0
    for document_id in document_ids:
        version_id = f"{document_id}-v1"
        for ordinal in range(units_per_document):
            text = f"{document_id} unit {ordinal}"
            digest = hash_text(text)
            unit_id = make_text_unit_id(
                document_version_id=version_id, locator=f"p{ordinal}", content_hash=digest,
            )
            batch.append({
                "labels": [TEXT_UNIT, scope],
                "key": unit_id,
                "props": {
                    "document_id": document_id,
                    "document_version_id": version_id,
                    "text": text,
                    "ordinal": ordinal,
                },
                "dense_vector": list(emb),
            })
            if len(batch) >= _BATCH:
                catalog.batch_upsert_nodes(batch)
                written += len(batch)
                batch.clear()
    if batch:
        catalog.batch_upsert_nodes(batch)
        written += len(batch)
    return written


def link_same_party(catalog: Catalog, document_ids: Sequence[str]) -> None:
    for document_id in document_ids:
        row = catalog.get_by_key(CANONICAL_DOCUMENT, document_id)
        if row is None:
            continue
        peers = [peer for peer in document_ids if peer != document_id]
        props = dict(row.props)
        props["same_party_document_ids"] = peers
        catalog.upsert_node([CANONICAL_DOCUMENT], document_id, props=props)


def count_text_units(catalog: Catalog) -> int:
    summary = catalog_summary(catalog)
    for row in summary["node_labels"]:
        if row["label"] == "TextUnit":
            return int(row["count"])
    return 0


def assert_has_version(catalog: Catalog, document_id: str) -> None:
    document = catalog.get_by_key(CANONICAL_DOCUMENT, document_id)
    assert document is not None and document.engine_id is not None
    versions = catalog.neighbors(
        document.engine_id, direction="outgoing", edge_label_filter=[HAS_VERSION],
    )
    assert versions
    version = catalog.get(versions[0])
    assert version is not None and DOCUMENT_VERSION in version.labels
