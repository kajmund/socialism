"""Owner-backed document ingest for one tenant knowledge catalog.

The backend prepares TextUnits and embeddings, then publishes them in one
Owner batch. No backend process opens the tenant catalog.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from app.services.document_qa.labels import CANONICAL_DOCUMENT, HAS_VERSION
from app.services.overgraph.labels import CONTAINS, DOCUMENT_VERSION, NEXT, TEXT_UNIT, scope_label
from app.services.overgraph.model import TextUnitWrite
from app.services.overgraph.owner import OwnerClient
from app.services.overgraph.owner_graph import (
    GraphBatch,
    apply_batch,
    make_edge,
    make_node,
    read_nodes,
)


class OwnerIngestError(RuntimeError):
    pass


def _ms(value: datetime | None) -> int | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return int(value.timestamp() * 1000)


def _unit_props(unit: TextUnitWrite) -> dict[str, Any]:
    return {
        "scope_key": unit.scope.scope_key,
        "document_id": unit.document_id,
        "document_version_id": unit.document_version_id,
        "section_id": unit.section_id or "",
        "section_title": unit.section_title or "",
        "section_ordinal": unit.section_ordinal if unit.section_ordinal is not None else -1,
        "ordinal": unit.ordinal,
        "text": unit.text,
        "content_hash": unit.content_hash,
        "locator": unit.locator or "",
        "page_start": unit.page_start if unit.page_start is not None else -1,
        "page_end": unit.page_end if unit.page_end is not None else -1,
        "char_start": unit.char_start if unit.char_start is not None else -1,
        "char_end": unit.char_end if unit.char_end is not None else -1,
        "ingested_at": _ms(unit.ingested_at) or 0,
        "valid_from_ms": _ms(unit.valid_from) or 0,
        "valid_to_ms": _ms(unit.valid_to) or 0,
        "extra_json": json.dumps(unit.metadata or {}, ensure_ascii=False, sort_keys=True),
    }


def _document_props(existing: dict[str, Any] | None, document_id: str) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "archived": int((existing or {}).get("archived") or 0),
    }


async def persist_document_units(
    client: OwnerClient,
    *,
    document_id: str,
    units: Sequence[TextUnitWrite],
) -> None:
    """Publish document, version, TextUnits, embeddings and edges atomically."""
    if not units:
        raise OwnerIngestError("document ingest has no TextUnits")
    versions = {unit.document_version_id for unit in units}
    unit_ids = {unit.unit_id for unit in units}
    if any(unit.document_id != document_id for unit in units):
        raise OwnerIngestError("document ingest mixes document ids")
    response = await read_nodes(client, [(CANONICAL_DOCUMENT, document_id)])
    existing = response.get("values", {}).get(f"{CANONICAL_DOCUMENT}:{document_id}")
    next_refs = [
        (TEXT_UNIT, unit.next_id)
        for unit in units
        if unit.next_id and unit.next_id not in unit_ids
    ]
    next_response = await read_nodes(client, next_refs) if next_refs else {}
    batch = GraphBatch(nodes=[make_node(
        CANONICAL_DOCUMENT, document_id, _document_props(existing, document_id),
    )])
    for version in sorted(versions):
        scope_key = next(unit.scope.scope_key for unit in units
                         if unit.document_version_id == version)
        batch.nodes.append(make_node(
            [DOCUMENT_VERSION, scope_label(scope_key)], version,
            {
                "scope_key": scope_key,
                "document_id": document_id,
                "document_version_id": version,
            },
        ))
        batch.edges.append(make_edge(
            (CANONICAL_DOCUMENT, document_id), (DOCUMENT_VERSION, version), HAS_VERSION,
        ))
    for unit in units:
        labels = [TEXT_UNIT, scope_label(unit.scope.scope_key)]
        batch.nodes.append(make_node(
            labels, unit.unit_id, _unit_props(unit),
            dense_vector=list(unit.embedding) if unit.embedding is not None else None,
        ))
        batch.edges.append(make_edge(
            (DOCUMENT_VERSION, unit.document_version_id), (TEXT_UNIT, unit.unit_id), CONTAINS,
            valid_from=_ms(unit.valid_from), valid_to=_ms(unit.valid_to),
        ))
        if unit.next_id and (
            unit.next_id in unit_ids or _known(next_response, unit.next_id)
        ):
            batch.edges.append(make_edge(
                (TEXT_UNIT, unit.unit_id), (TEXT_UNIT, unit.next_id), NEXT,
            ))
    await apply_batch(client, "ingest:document", nodes=batch.nodes, edges=batch.edges)


def _known(response: dict[str, Any], key: str) -> bool:
    return response.get("values", {}).get(f"{TEXT_UNIT}:{key}") is not None
