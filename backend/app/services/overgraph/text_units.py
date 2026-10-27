"""Write and read domain TextUnits in OverGraph (authoritative TextUnit nodes).

Canonical ingest produces domain ``TextUnit`` objects; this module maps them to
``TextUnitWrite`` and upserts the OverGraph node, its ``DocumentVersion`` anchor,
and the ``CONTAINS`` structural edge. It also reads TextUnits back by version,
which the read-side cutover uses to hydrate original passages from OverGraph.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from app.services.knowledge.scope import KnowledgeTenantScope
from app.services.knowledge.units import TextUnit
from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.labels import TEXT_UNIT
from app.services.overgraph.model import GraphRecord, TextUnitWrite
from app.services.overgraph.write import upsert_text_unit


def text_unit_to_write(
    unit: TextUnit,
    scope: KnowledgeTenantScope,
    embedding: Sequence[float] | None,
    *,
    section_title: str | None,
    section_ordinal: int | None,
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
        section_title=section_title,
        section_ordinal=section_ordinal,
        locator=unit.locator,
        page_start=unit.page_start,
        page_end=unit.page_end,
        char_start=unit.char_start,
        char_end=unit.char_end,
        valid_from=unit.valid_from,
        valid_to=unit.valid_to,
        ingested_at=unit.ingested_at,
        embedding=tuple(embedding) if embedding is not None else None,
        metadata=dict(unit.metadata),
    )


def upsert_text_units(
    catalog: Catalog,
    units: Sequence[TextUnit],
    *,
    scope: KnowledgeTenantScope,
    embeddings: Sequence[Sequence[float]] | None = None,
    section_titles: Mapping[str, str] | None = None,
    section_ordinals: Mapping[str, int] | None = None,
) -> list[int]:
    """Write TextUnit nodes (+ DocumentVersion anchors, CONTAINS edges)."""
    if embeddings is not None and len(embeddings) != len(units):
        raise ValueError("embedding count does not match text unit count")
    titles = section_titles or {}
    ordinals = section_ordinals or {}
    engine_ids: list[int] = []
    for index, unit in enumerate(units):
        vector = embeddings[index] if embeddings is not None else None
        title = titles.get(unit.section_id or "", "") if unit.section_id else None
        section_ordinal = ordinals.get(unit.section_id or "") if unit.section_id else None
        node = upsert_text_unit(
            catalog,
            text_unit_to_write(
                unit, scope, vector, section_title=title, section_ordinal=section_ordinal,
            ),
        )
        if node.engine_id is None:
            raise RuntimeError(f"text unit {unit.id} was not assigned an engine id")
        engine_ids.append(node.engine_id)
    return engine_ids


def load_text_units(
    catalog: Catalog, *, document_version_id: str,
) -> list[GraphRecord]:
    """Read TextUnit nodes for a version in document order (section → ordinal)."""
    rows: list[GraphRecord] = []
    after: int | None = None
    while True:
        page, after = catalog.query_nodes(
            label_filter={"labels": [TEXT_UNIT], "mode": "all"},
            filter_spec={"property": "document_version_id", "eq": document_version_id},
            limit=1000,
            after=after,
        )
        rows.extend(page)
        if after is None or not page:
            break
    rows.sort(key=lambda row: (
        int(row.props.get("section_ordinal", -1)),
        int(row.props.get("ordinal", 0)),
        row.key,
    ))
    return rows


def load_domain_text_units(
    catalog: Catalog, *, document_version_id: str,
) -> list[TextUnit]:
    """Read TextUnit nodes back as domain ``TextUnit`` objects (decommission read side)."""
    return [
        _domain_unit(row)
        for row in load_text_units(catalog, document_version_id=document_version_id)
    ]


def load_domain_text_unit(catalog: Catalog, *, unit_id: str) -> TextUnit | None:
    """Read one TextUnit node back as a domain ``TextUnit`` (or ``None``)."""
    row = catalog.get_by_key(TEXT_UNIT, unit_id)
    return _domain_unit(row) if row is not None else None


def load_all_domain_text_units(catalog: Catalog) -> list[TextUnit]:
    """Every TextUnit node in the catalog as a domain ``TextUnit``."""
    rows: list[GraphRecord] = []
    after: int | None = None
    while True:
        page, after = catalog.query_nodes(
            label_filter={"labels": [TEXT_UNIT], "mode": "all"},
            limit=1000,
            after=after,
        )
        rows.extend(page)
        if after is None or not page:
            break
    return [_domain_unit(row) for row in rows]


def count_text_units(catalog: Catalog) -> int:
    """Number of TextUnit nodes in the catalog."""
    return catalog.count_nodes_by_labels([TEXT_UNIT])


def text_unit_ids_for_document(catalog: Catalog, *, document_id: str) -> list[str]:
    """TextUnit node keys for a document (all versions)."""
    ids: list[str] = []
    after: int | None = None
    while True:
        page, after = catalog.query_nodes(
            label_filter={"labels": [TEXT_UNIT], "mode": "all"},
            filter_spec={"property": "document_id", "eq": document_id},
            limit=1000,
            after=after,
        )
        ids.extend(row.key for row in page)
        if after is None or not page:
            break
    return ids


def delete_text_units_for_document(catalog: Catalog, *, document_id: str) -> int:
    """Delete every TextUnit node of a document. Returns the deleted count."""
    deleted = 0
    for unit_id in text_unit_ids_for_document(catalog, document_id=document_id):
        row = catalog.get_by_key(TEXT_UNIT, unit_id)
        if row is not None and row.engine_id is not None:
            catalog.delete_node(row.engine_id)
            deleted += 1
    return deleted


def domain_unit_from_props(key: str, props: dict[str, object]) -> TextUnit:
    """Map stored TextUnit props back to the domain object.

    Shared by the local reader and the owner-backed reader so both surfaces
    decode the same graph node identically.
    """
    return TextUnit(
        id=key,
        document_version_id=str(props.get("document_version_id") or ""),
        document_id=str(props.get("document_id") or ""),
        section_id=str(props.get("section_id") or "") or None,
        ordinal=int(props.get("ordinal") or 0),
        text=str(props.get("text") or ""),
        content_hash=str(props.get("content_hash") or ""),
        locator=str(props.get("locator") or "") or None,
        page_start=_positive(props.get("page_start")),
        page_end=_positive(props.get("page_end")),
        char_start=_positive(props.get("char_start")),
        char_end=_positive(props.get("char_end")),
        valid_from=_from_ms(props.get("valid_from_ms")),
        valid_to=_from_ms(props.get("valid_to_ms")),
        ingested_at=_from_ms(props.get("ingested_at")),
        metadata=_metadata(props.get("extra_json")),
    )


def _domain_unit(row: GraphRecord) -> TextUnit:
    return domain_unit_from_props(row.key, row.props)


def _positive(value: object) -> int | None:
    parsed = int(value) if value is not None else -1
    return parsed if parsed >= 0 else None


def _from_ms(value: object) -> datetime | None:
    parsed = int(value) if value is not None else 0
    return datetime.fromtimestamp(parsed / 1000, tz=UTC) if parsed else None


def _metadata(value: object) -> dict[str, object]:
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (ValueError, TypeError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}
