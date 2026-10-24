"""TextUnit mutations through the single-writer Overgraph owner."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from app.services.knowledge.scope import KnowledgeTenantScope
from app.services.knowledge.units import TextUnit
from app.services.overgraph.labels import CONTAINS, DOCUMENT_VERSION, NEXT, TEXT_UNIT, scope_label
from app.services.overgraph.owner import OwnerClient
from app.services.overgraph.text_units import text_unit_to_write
from app.services.overgraph.write import _ms


def _text_unit_payload(
    unit: TextUnit,
    scope: KnowledgeTenantScope,
    vector: Sequence[float] | None,
    *,
    section_title: str | None,
    section_ordinal: int | None,
) -> dict[str, object]:
    write = text_unit_to_write(
        unit, scope, vector, section_title=section_title, section_ordinal=section_ordinal,
    )
    version_node = {
        "labels": [DOCUMENT_VERSION, scope_label(scope.scope_key)],
        "key": write.document_version_id,
        "props": {
            "scope_key": scope.scope_key,
            "document_id": write.document_id,
            "document_version_id": write.document_version_id,
        },
    }
    node = {
        "labels": [TEXT_UNIT, scope_label(scope.scope_key)],
        "key": write.unit_id,
        "props": {
            "scope_key": scope.scope_key,
            "document_id": write.document_id,
            "document_version_id": write.document_version_id,
            "section_id": write.section_id or "",
            "section_title": write.section_title or "",
            "section_ordinal": write.section_ordinal if write.section_ordinal is not None else -1,
            "ordinal": write.ordinal,
            "text": write.text,
            "content_hash": write.content_hash,
            "locator": write.locator or "",
            "page_start": write.page_start if write.page_start is not None else -1,
            "page_end": write.page_end if write.page_end is not None else -1,
            "char_start": write.char_start if write.char_start is not None else -1,
            "char_end": write.char_end if write.char_end is not None else -1,
            "ingested_at": _ms(write.ingested_at) or 0,
            "valid_from_ms": _ms(write.valid_from) or 0,
            "valid_to_ms": _ms(write.valid_to) or 0,
            "extra_json": json.dumps(write.metadata or {}, ensure_ascii=False, sort_keys=True),
        },
        "dense_vector": list(vector) if vector is not None else None,
    }
    edges = [
        {
            "from": {"label": DOCUMENT_VERSION, "key": write.document_version_id},
            "to": {"label": TEXT_UNIT, "key": write.unit_id},
            "label": CONTAINS,
            "valid_from": _ms(write.valid_from),
            "valid_to": _ms(write.valid_to),
        }
    ]
    if write.next_id:
        edges.append({
            "from": {"label": TEXT_UNIT, "key": write.unit_id},
            "to": {"label": TEXT_UNIT, "key": write.next_id},
            "label": NEXT,
        })
    return {"version": version_node, "unit": node, "edges": edges}


def build_text_unit_batch(
    units: Sequence[TextUnit],
    *,
    scope: KnowledgeTenantScope,
    embeddings: Sequence[Sequence[float] | None],
    section_titles: Mapping[str, str] | None = None,
    section_ordinals: Mapping[str, int] | None = None,
) -> dict[str, object]:
    titles = section_titles or {}
    ordinals = section_ordinals or {}
    nodes: list[dict[str, object]] = []
    edges: list[dict[str, object]] = []
    versions: set[str] = set()
    for unit, vector in zip(units, embeddings, strict=True):
        payload = _text_unit_payload(
            unit,
            scope,
            vector,
            section_title=titles.get(unit.section_id or "") if unit.section_id else None,
            section_ordinal=ordinals.get(unit.section_id or "") if unit.section_id else None,
        )
        version = payload["version"]
        if version["key"] not in versions:
            versions.add(str(version["key"]))
            nodes.append(version)
        nodes.append(payload["unit"])
        edges.extend(payload["edges"])
    return {"upsert_nodes": nodes, "upsert_edges": edges}


def mutation_id_for(
    batch: Mapping[str, object], *, catalog_id: str | None = None, scope_key: str | None = None,
) -> str:
    import hashlib

    canonical = json.dumps(
        {"operation": "upsert-text-units", "catalog_id": catalog_id, "scope_key": scope_key, "batch": batch},
        sort_keys=True, separators=(",", ":"), default=str,
    )
    return "text-units:" + hashlib.sha256(canonical.encode()).hexdigest()


async def write_text_unit_embeddings_via_owner(
    client: OwnerClient,
    units: Sequence[TextUnit],
    vectors: Sequence[Sequence[float]],
    *,
    mutation_id: str | None = None,
) -> dict[str, object]:
    updates = [
        {
            "label": TEXT_UNIT,
            "key": unit.id,
            "content_hash": unit.content_hash,
            "vector": list(vector),
        }
        for unit, vector in zip(units, vectors, strict=True)
    ]
    batch = {"embedding_updates": updates}
    if mutation_id is None:
        import hashlib

        canonical = json.dumps(
            {"operation": "embed-text-units", "catalog_id": client.catalog_id, "updates": updates},
            sort_keys=True, separators=(",", ":"), default=str,
        )
        mutation_id = "embeddings:" + hashlib.sha256(canonical.encode()).hexdigest()
    return await client.mutate(mutation_id, batch, kind="embedding")


async def write_text_units_via_owner(
    client: OwnerClient,
    units: Sequence[TextUnit],
    *,
    scope: KnowledgeTenantScope,
    embeddings: Sequence[Sequence[float] | None],
    section_titles: Mapping[str, str] | None = None,
    section_ordinals: Mapping[str, int] | None = None,
    mutation_id: str | None = None,
) -> dict[str, object]:
    batch = build_text_unit_batch(
        units,
        scope=scope,
        embeddings=embeddings,
        section_titles=section_titles,
        section_ordinals=section_ordinals,
    )
    return await client.mutate(
        mutation_id or mutation_id_for(batch, catalog_id=client.catalog_id, scope_key=scope.scope_key),
        batch,
        kind="batch",
    )


async def delete_text_units_via_owner(
    client: OwnerClient,
    units: Sequence[TextUnit],
    *,
    mutation_id: str,
) -> dict[str, object]:
    """Delete TextUnit nodes with an explicit new logical-operation id."""
    payload = {
        "delete_nodes": [
            {"label": TEXT_UNIT, "key": unit.id}
            for unit in units
        ]
    }
    return await client.mutate(mutation_id, payload, kind="batch")


async def delete_nodes_via_owner(
    client: OwnerClient,
    nodes: Sequence[tuple[str, str]],
    *,
    mutation_id: str,
) -> dict[str, object]:
    return await client.mutate(
        mutation_id,
        {"delete_nodes": [{"label": label, "key": key} for label, key in nodes]},
        kind="batch",
    )


async def unlink_document_versions_via_owner(
    client: OwnerClient,
    evidence_keys: Sequence[str],
    *,
    mutation_id: str,
) -> dict[str, object]:
    from app.services.overgraph.legal_claims import EVIDENCE

    return await delete_nodes_via_owner(
        client, [(EVIDENCE, key) for key in evidence_keys], mutation_id=mutation_id,
    )


async def delete_text_units_by_ids_via_owner(
    client: OwnerClient,
    unit_ids: Sequence[str],
    *,
    mutation_id: str,
) -> dict[str, object]:
    return await delete_nodes_via_owner(
        client, [(TEXT_UNIT, unit_id) for unit_id in unit_ids], mutation_id=mutation_id,
    )
