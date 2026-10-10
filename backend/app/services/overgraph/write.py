"""Upsert Graph v2 identities as OverGraph fact and TextUnit nodes."""

import json
from datetime import UTC, datetime

from app.services.graph_v2.errors import PermanentGraphError
from app.services.graph_v2.identity import (
    fact_identity,
    namespaced,
    normalized,
    stable_id,
    weak_node_identity,
)
from app.services.graph_v2.types import FactInput, NodeInput, SourceRef
from app.services.knowledge.scope import KnowledgeTenantScope
from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.isolation import can_reference
from app.services.overgraph.labels import (
    CONTEXT,
    CONTRADICTS,
    DOCUMENT_VERSION,
    ENTITY,
    FACT,
    IDENTIFIER,
    NEXT,
    OBJECT,
    SUBJECT,
    SUPPORTS,
    TEXT_UNIT,
    CONTAINS,
    scope_label,
)
from app.services.overgraph.model import GraphRecord, TextUnitWrite


def _ms(value: datetime | None) -> int | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return int(value.timestamp() * 1000)


def _labels(kind: str, scope_key: str) -> list[str]:
    return [kind, scope_label(scope_key)]


def _require(catalog: Catalog, label: str, key: str) -> GraphRecord:
    row = catalog.get_by_key(label, key)
    if row is None:
        raise PermanentGraphError(f"missing graph node {label}:{key}")
    return row


def upsert_entity(catalog: Catalog, proposed: NodeInput) -> GraphRecord:
    namespaced(proposed.node_type)
    name = normalized(proposed.name)
    if proposed.identifier_namespace is not None:
        identity = f"{namespaced(proposed.identifier_namespace)}:{normalized(proposed.identifier or '')}"
    else:
        identity = weak_node_identity(proposed.context_key, name)
    key = stable_id(proposed.scope.scope_key, proposed.node_type, identity)
    catalog.upsert_node(
        _labels(ENTITY, proposed.scope.scope_key),
        key,
        props={
            "scope_key": proposed.scope.scope_key,
            "node_type": proposed.node_type,
            "identity_key": identity,
            "name": proposed.name.strip(),
            "normalized_name": name,
            "attributes_json": json.dumps(proposed.attributes, ensure_ascii=False, sort_keys=True),
        },
    )
    if proposed.identifier_namespace is not None:
        alias = stable_id(
            proposed.scope.scope_key, namespaced(proposed.identifier_namespace),
            normalized(proposed.identifier or ""),
        )
        catalog.upsert_node(
            _labels(IDENTIFIER, proposed.scope.scope_key),
            alias,
            props={
                "scope_key": proposed.scope.scope_key,
                "namespace": proposed.identifier_namespace,
                "identifier": proposed.identifier,
                "node_key": key,
            },
        )
    return _require(catalog, ENTITY, key)


def upsert_text_unit(catalog: Catalog, unit: TextUnitWrite) -> GraphRecord:
    version_key = unit.document_version_id
    catalog.upsert_node(
        _labels(DOCUMENT_VERSION, unit.scope.scope_key),
        version_key,
        props={
            "scope_key": unit.scope.scope_key,
            "document_id": unit.document_id,
            "document_version_id": unit.document_version_id,
        },
    )
    catalog.upsert_node(
        _labels(TEXT_UNIT, unit.scope.scope_key),
        unit.unit_id,
        props={
            "scope_key": unit.scope.scope_key,
            "document_id": unit.document_id,
            "document_version_id": unit.document_version_id,
            "section_id": unit.section_id or "",
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
            "extra_json": "{}",
        },
        dense_vector=unit.embedding,
    )
    version = _require(catalog, DOCUMENT_VERSION, version_key)
    node = _require(catalog, TEXT_UNIT, unit.unit_id)
    catalog.upsert_edge(
        version.engine_id, node.engine_id, CONTAINS,
        valid_from=_ms(unit.valid_from), valid_to=_ms(unit.valid_to),
    )
    if unit.next_id:
        nxt = catalog.get_by_key(TEXT_UNIT, unit.next_id)
        if nxt is not None and nxt.engine_id is not None:
            catalog.upsert_edge(node.engine_id, nxt.engine_id, NEXT)
    return node


def _endpoint(catalog: Catalog, node_id: str, owner: KnowledgeTenantScope) -> GraphRecord:
    row = catalog.get_by_key(ENTITY, node_id)
    if row is None or not can_reference(owner, str(row.props.get("scope_key") or "")):
        raise PermanentGraphError("fact endpoint is missing or outside tenant scope")
    return row


def _source_node(catalog: Catalog, source: SourceRef, owner: KnowledgeTenantScope) -> GraphRecord:
    if source.kind == "text_unit":
        row = catalog.get_by_key(TEXT_UNIT, source.ref)
        if row is None or not can_reference(owner, str(row.props.get("scope_key") or "")):
            raise PermanentGraphError("TextUnit provenance is missing or outside tenant scope")
        return row
    if source.kind != "episode":
        raise PermanentGraphError("unsupported provenance kind")
    key = f"episode:{source.ref}"
    catalog.upsert_node(
        _labels(ENTITY, owner.scope_key),
        key,
        props={"scope_key": owner.scope_key, "node_type": "research.episode", "name": source.ref},
    )
    return _require(catalog, ENTITY, key)


def fact_key(proposed: FactInput) -> str:
    return fact_identity(
        scope_key=proposed.scope.scope_key, source_id=proposed.source_id,
        target_id=proposed.target_id, predicate=proposed.predicate,
        context_id=proposed.context_id, occurrence_key=proposed.occurrence_key,
        fact_text=proposed.fact_text,
    )


def attach_sources(catalog: Catalog, fact: GraphRecord, sources: tuple[SourceRef, ...]) -> None:
    if fact.engine_id is None:
        raise PermanentGraphError("fact node is missing an engine id")
    owner = _scope_from_props(fact.props)
    recorded = _source_ref_list(fact.props)
    seen = {(item["kind"], item["ref"]) for item in recorded}
    for source in sources:
        origin = _source_node(catalog, source, owner)
        if origin.engine_id is None:
            raise PermanentGraphError("provenance node is missing an engine id")
        catalog.upsert_edge(
            origin.engine_id, fact.engine_id, SUPPORTS,
            props={
                "source_kind": source.kind,
                "source_ref": source.ref,
                "recorded_at": _ms(datetime.now(UTC)),
            },
        )
        if (source.kind, source.ref) not in seen:
            recorded.append({"kind": source.kind, "ref": source.ref})
            seen.add((source.kind, source.ref))
    props = dict(fact.props)
    props["source_refs_json"] = json.dumps(recorded, ensure_ascii=False)
    catalog.upsert_node(list(fact.labels), fact.key, props=props, dense_vector=fact.dense_vector)


def _source_ref_list(props: dict[str, object]) -> list[dict[str, str]]:
    raw = props.get("source_refs_json") or "[]"
    parsed = json.loads(str(raw))
    return [dict(item) for item in parsed]


def _scope_from_props(props: dict[str, object]) -> KnowledgeTenantScope:
    key = str(props.get("scope_key") or "")
    if key == "shared":
        return KnowledgeTenantScope(scope_type="shared", customer_id=None)
    return KnowledgeTenantScope(scope_type="customer", customer_id=int(key.split(":", 1)[1]))


def upsert_exact_fact(catalog: Catalog, proposed: FactInput) -> GraphRecord | None:
    namespaced(proposed.predicate)
    normalized(proposed.fact_text)
    if not proposed.sources:
        raise PermanentGraphError("fact requires at least one episode or TextUnit")
    _endpoint(catalog, proposed.source_id, proposed.scope)
    _endpoint(catalog, proposed.target_id, proposed.scope)
    if proposed.context_id:
        _endpoint(catalog, proposed.context_id, proposed.scope)
    key = fact_key(proposed)
    existing = catalog.get_by_key(FACT, key)
    if existing is None:
        return None
    attach_sources(catalog, existing, proposed.sources)
    return existing


def write_fact(
    catalog: Catalog, proposed: FactInput, *, contradiction_key: str | None = None,
    key: str | None = None,
) -> GraphRecord:
    source = _endpoint(catalog, proposed.source_id, proposed.scope)
    target = _endpoint(catalog, proposed.target_id, proposed.scope)
    context = (
        _endpoint(catalog, proposed.context_id, proposed.scope)
        if proposed.context_id else None
    )
    key = key or fact_key(proposed)
    catalog.upsert_node(
        _labels(FACT, proposed.scope.scope_key),
        key,
        props={
            "scope_key": proposed.scope.scope_key,
            "predicate": proposed.predicate,
            "fact_text": proposed.fact_text.strip(),
            "normalized_text": normalized(proposed.fact_text),
            "occurrence_key": proposed.occurrence_key,
            "source_key": proposed.source_id,
            "target_key": proposed.target_id,
            "context_key": proposed.context_id or "",
            "status": "active",
            "valid_at_ms": _ms(proposed.valid_at) or 0,
            "invalid_at_ms": 0,
            "attributes_json": json.dumps(
                proposed.attributes, ensure_ascii=False, sort_keys=True,
            ),
            "source_refs_json": json.dumps(
                [{"kind": item.kind, "ref": item.ref} for item in proposed.sources],
                ensure_ascii=False,
            ),
        },
        dense_vector=proposed.embedding,
    )
    fact = _require(catalog, FACT, key)
    if fact.engine_id is None or source.engine_id is None or target.engine_id is None:
        raise PermanentGraphError("fact endpoints are missing engine ids")
    valid_from = _ms(proposed.valid_at)
    catalog.upsert_edge(fact.engine_id, source.engine_id, SUBJECT, valid_from=valid_from)
    catalog.upsert_edge(fact.engine_id, target.engine_id, OBJECT, valid_from=valid_from)
    if context is not None and context.engine_id is not None:
        catalog.upsert_edge(fact.engine_id, context.engine_id, CONTEXT, valid_from=valid_from)
    attach_sources(catalog, fact, proposed.sources)
    if contradiction_key:
        other = catalog.get_by_key(FACT, contradiction_key)
        if other is not None and other.engine_id is not None:
            left, right = sorted((fact.engine_id, other.engine_id))
            catalog.upsert_edge(left, right, CONTRADICTS)
    return fact


def same_endpoint_facts(catalog: Catalog, proposed: FactInput) -> list[GraphRecord]:
    source = catalog.get_by_key(ENTITY, proposed.source_id)
    if source is None or source.engine_id is None:
        return []
    rows: list[GraphRecord] = []
    for neighbor in catalog.neighbors(source.engine_id, direction="incoming", edge_label_filter=[SUBJECT]):
        row = catalog.get(neighbor)
        if row is None or FACT not in row.labels:
            continue
        if row.props.get("status") != "active":
            continue
        if row.props.get("target_key") != proposed.target_id:
            continue
        if row.props.get("predicate") != proposed.predicate:
            continue
        if row.props.get("occurrence_key") != proposed.occurrence_key:
            continue
        if row.props.get("context_key") != (proposed.context_id or ""):
            continue
        if row.props.get("scope_key") != proposed.scope.scope_key:
            continue
        rows.append(row)
    return rows
