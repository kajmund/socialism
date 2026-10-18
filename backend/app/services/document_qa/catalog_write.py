"""Write a persisted document version into a tenant OverGraph. No Q&A."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from app.services.document_qa.labels import CANONICAL_DOCUMENT, HAS_VERSION
from app.services.knowledge.scope import KnowledgeTenantScope, customer_scope
from app.services.knowledge.units import TextUnit
from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.ingest import ingest_document_units
from app.services.overgraph.labels import DOCUMENT_VERSION
from app.services.overgraph.model import GraphRecord, TextUnitWrite


async def write_document_units(
    catalog: Catalog,
    *,
    document_id: str,
    units: Sequence[TextUnitWrite],
) -> None:
    if not units:
        raise ValueError("document catalog write has no TextUnits")
    document = _upsert_document(catalog, document_id)
    await ingest_document_units(catalog, _with_next(units), ingest_mode=True)
    version = catalog.get_by_key(DOCUMENT_VERSION, units[0].document_version_id)
    if version is None or version.engine_id is None or document.engine_id is None:
        raise RuntimeError("document version missing after catalog ingest")
    catalog.upsert_edge(document.engine_id, version.engine_id, HAS_VERSION)


def unit_writes(
    units: Sequence[TextUnit],
    *,
    customer_id: int,
    embeddings: Sequence[Sequence[float]],
) -> tuple[TextUnitWrite, ...]:
    if len(units) != len(embeddings):
        raise ValueError("document catalog embeddings do not match TextUnits")
    scope = customer_scope(customer_id)
    return tuple(
        _unit_write(unit, scope, tuple(vector))
        for unit, vector in zip(units, embeddings, strict=True)
    )


def _unit_write(
    unit: TextUnit, scope: KnowledgeTenantScope, embedding: tuple[float, ...],
) -> TextUnitWrite:
    return TextUnitWrite(
        unit_id=unit.id,
        scope=scope,
        document_id=unit.document_id,
        document_version_id=unit.document_version_id,
        text=unit.text,
        content_hash=unit.content_hash,
        ordinal=unit.ordinal,
        section_id=unit.section_id,
        locator=unit.locator,
        page_start=unit.page_start,
        page_end=unit.page_end,
        char_start=unit.char_start,
        char_end=unit.char_end,
        valid_from=unit.valid_from,
        valid_to=unit.valid_to,
        ingested_at=unit.ingested_at,
        embedding=embedding,
    )


def _with_next(units: Sequence[TextUnitWrite]) -> list[TextUnitWrite]:
    if len(units) < 2:
        return list(units)
    linked = [
        replace(unit, next_id=units[index + 1].unit_id)
        for index, unit in enumerate(units[:-1])
    ]
    return list(reversed([*linked, units[-1]]))


def _upsert_document(catalog: Catalog, document_id: str) -> GraphRecord:
    existing = catalog.get_by_key(CANONICAL_DOCUMENT, document_id)
    archived = int((existing.props if existing else {}).get("archived") or 0)
    catalog.upsert_node(
        [CANONICAL_DOCUMENT],
        document_id,
        props={"document_id": document_id, "archived": archived},
    )
    row = catalog.get_by_key(CANONICAL_DOCUMENT, document_id)
    if row is None:
        raise RuntimeError("document node missing after catalog ingest")
    return row
